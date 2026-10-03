"""Single entry point for every Claude call, with two interchangeable backends.

- "subscription" (default): runs the `claude` CLI headless (`claude -p`), so
  calls count against your Claude plan's usage limits instead of API billing.
  Personal use only: Anthropic doesn't allow offering claude.ai login to others.
- "api": the Anthropic SDK with ANTHROPIC_API_KEY, billed per token.

Both take the same requests: each task maps to a model (Sonnet where quality
matters, Haiku for cheap bulk work), and structured results are validated
into a Pydantic model. Every call is logged to api_usage with its backend;
only API calls count toward the monthly budget.
"""

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError
from sqlalchemy import func
from sqlmodel import Session, select

from app.config import get_config
from app.models import ApiUsage, Setting

T = TypeVar("T", bound=BaseModel)


class Task(str, Enum):
    feedback = "feedback"
    roleplay = "roleplay"
    roleplay_corrections = "roleplay_corrections"
    enrichment = "enrichment"
    drill_generation = "drill_generation"
    drill_review = "drill_review"
    answer_check = "answer_check"
    deck_generation = "deck_generation"


SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-4-5"

TASK_MODELS: dict[Task, str] = {
    Task.feedback: SONNET,
    Task.roleplay: SONNET,
    Task.roleplay_corrections: SONNET,
    Task.enrichment: HAIKU,
    Task.drill_generation: SONNET,  # answer keys must be right; Haiku slipped on Russian
    Task.drill_review: SONNET,
    Task.answer_check: HAIKU,
    Task.deck_generation: HAIKU,
}

# Effort for Sonnet tasks (Haiku 4.5 doesn't take effort). Chat stays snappy.
TASK_EFFORT: dict[Task, str] = {
    Task.feedback: "medium",
    Task.roleplay: "low",
    Task.roleplay_corrections: "low",
    Task.drill_generation: "low",
    Task.drill_review: "medium",
}

# On the subscription, per-token price doesn't matter, so every task uses Sonnet:
# in testing (2026-10-02) Haiku's Russian examples had wrong words, cases and
# stress, while Sonnet at low effort was correct and about as fast (~4-5 s).
SUBSCRIPTION_EFFORT: dict[Task, str] = {
    Task.feedback: "medium",
    Task.roleplay: "low",
    Task.roleplay_corrections: "low",
    Task.enrichment: "low",
    Task.drill_generation: "low",
    Task.drill_review: "medium",
    Task.answer_check: "low",
    Task.deck_generation: "low",
}


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input: float
    output: float
    cache_read: float
    cache_write: float


PRICES: dict[str, Price] = {
    SONNET: Price(input=2.00, output=10.00, cache_read=0.20, cache_write=2.50),
    HAIKU: Price(input=1.00, output=5.00, cache_read=0.10, cache_write=1.25),
}

BUDGET_WARNING_RATIO = 0.8


class ClaudeError(RuntimeError):
    """Any failure talking to Claude; the message is safe to show in the UI."""


class ClaudeUnavailable(ClaudeError):
    """The selected backend isn't set up (no API key, or no `claude` CLI)."""


class ClaudeRefusal(ClaudeError):
    """The model declined the request (stop_reason == "refusal")."""


class ClaudeTruncated(ClaudeError):
    """The response hit max_tokens before finishing."""


# --- Backend selection -----------------------------------------------------------

class Backend(str, Enum):
    subscription = "subscription"
    api = "api"


BACKEND_LABELS = {
    Backend.subscription: "Claude subscription (via Claude Code)",
    Backend.api: "Anthropic API key (pay per use)",
}

# Mirrors the "ai_backend" setting so templates can check it without a DB session.
_current = {"backend": Backend.subscription}


def current_backend() -> Backend:
    return _current["backend"]


def load_backend(session: Session) -> Backend:
    row = session.get(Setting, "ai_backend")
    _current["backend"] = Backend(row.value) if row and row.value in Backend._value2member_map_ else Backend.subscription
    return _current["backend"]


def set_backend(session: Session, backend: Backend) -> None:
    row = session.get(Setting, "ai_backend") or Setting(key="ai_backend", value=backend.value)
    row.value = backend.value
    session.add(row)
    session.commit()
    _current["backend"] = backend


def claude_cli() -> str | None:
    return shutil.which("claude")


def ai_status(backend: Backend | None = None) -> tuple[bool, str]:
    """(available, reason if not) for the given or current backend."""
    backend = backend or current_backend()
    if backend == Backend.api:
        if get_config().has_api_key:
            return True, ""
        return False, "AI is off: set ANTHROPIC_API_KEY and restart, or switch to your Claude subscription in Settings."
    if claude_cli():
        return True, ""
    return False, "AI is off: install Claude Code (the `claude` command) and log in, or switch to an API key in Settings."


# --- Client --------------------------------------------------------------------

@contextmanager
def _friendly_errors():
    """Turn SDK exceptions (after its own retries) into ClaudeError messages."""
    try:
        yield
    except anthropic.AuthenticationError as e:
        raise ClaudeError("Your ANTHROPIC_API_KEY was rejected. Check it and restart.") from e
    except anthropic.RateLimitError as e:
        raise ClaudeError("Rate limited by the API. Wait a minute and try again.") from e
    except anthropic.APIStatusError as e:
        raise ClaudeError(f"Claude API error ({e.status_code}). Try again shortly.") from e
    except anthropic.APIConnectionError as e:
        raise ClaudeError("Couldn't reach the Claude API. Check your internet connection.") from e


Runner = Callable[[list[str], str, dict], subprocess.CompletedProcess]
# Yields the CLI's stdout line by line as it is produced (live streaming for role-play).
LineStreamer = Callable[[list[str], str, dict], Iterator[str]]


# Every request: English the learner reads uses American spelling.
SPELLING = "\n\nWrite all English in American spelling (color, practice as a verb, theater, traveler)."


class ClaudeClient:
    """`client` injects a fake Anthropic SDK client (API backend); `runner` a fake `claude` process;
    `streamer` a fake live line stream (without one, an injected runner also serves streaming)."""

    def __init__(
        self,
        session: Session,
        client: anthropic.Anthropic | None = None,
        *,
        backend: Backend | None = None,
        runner: Runner | None = None,
        streamer: LineStreamer | None = None,
    ):
        self.session = session
        self.backend = backend or (Backend.api if client else Backend.subscription if runner else current_backend())
        if self.backend == Backend.api:
            if client is None:
                available, reason = ai_status(Backend.api)
                if not available:
                    raise ClaudeUnavailable(reason)
                client = anthropic.Anthropic(api_key=get_config().api_key, max_retries=4)
            self.client = client
        else:
            if runner is None:
                cli = claude_cli()
                if cli is None:
                    raise ClaudeUnavailable(ai_status(Backend.subscription)[1])
                runner = _cli_runner(cli)
                streamer = streamer or _cli_streamer(cli)
            self.runner = runner
            self.streamer = streamer

    def ask_structured(
        self,
        task: Task,
        system: str,
        messages: list[dict] | str,
        output_model: type[T],
        max_tokens: int = 16000,
    ) -> T:
        """One request whose answer is validated into `output_model`."""
        system += SPELLING
        if self.backend == Backend.subscription:
            return self._cli_structured(task, system, messages, output_model)
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        with _friendly_errors():
            response = self.client.beta.messages.parse(
                **self._request_args(task, system, max_tokens),
                messages=messages,
                output_format=output_model,
            )
        self._log_api_usage(task, response)
        self._check_stop(response)
        return response.parsed_output

    def stream_text(
        self,
        task: Task,
        system: str,
        messages: list[dict],
        max_tokens: int = 4000,
    ) -> Iterator[str]:
        """Yield text chunks as they arrive (for the role-play chat)."""
        system += SPELLING
        if self.backend == Backend.subscription:
            yield from self._cli_stream(task, system, messages)
            return
        args = self._request_args(task, system, max_tokens)
        with _friendly_errors(), self.client.beta.messages.stream(**args, messages=messages) as stream:
            yield from stream.text_stream
            response = stream.get_final_message()
        self._log_api_usage(task, response)
        self._check_stop(response)

    # --- API backend -------------------------------------------------------------

    def _request_args(self, task: Task, system: str, max_tokens: int) -> dict:
        model = TASK_MODELS[task]
        args: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "cache_control": {"type": "ephemeral"},
        }
        if model == SONNET:
            args["output_config"] = {"effort": TASK_EFFORT.get(task, "medium")}
            args["betas"] = ["server-side-fallback-2026-07-01"]
            args["fallbacks"] = "default"
        return args

    @staticmethod
    def _check_stop(response) -> None:
        if response.stop_reason == "refusal":
            raise ClaudeRefusal("Claude declined this request. Try rephrasing it.")
        if response.stop_reason == "max_tokens":
            raise ClaudeTruncated("The response was cut off. Try a shorter text.")

    def _log_api_usage(self, task: Task, response) -> None:
        usage = response.usage
        model = response.model
        price = PRICES.get(model, PRICES[TASK_MODELS[task]])
        cache_read = usage.cache_read_input_tokens or 0
        cache_write = usage.cache_creation_input_tokens or 0
        cost = (
            usage.input_tokens * price.input
            + usage.output_tokens * price.output
            + cache_read * price.cache_read
            + cache_write * price.cache_write
        ) / 1_000_000
        self._record(task, model, usage.input_tokens, usage.output_tokens, cache_read, cache_write, cost,
                     getattr(response, "_request_id", None))

    # --- Subscription backend (claude -p) --------------------------------------------

    def _cli_args(self, task: Task, system: str) -> list[str]:
        return [
            "-p", "--model", SONNET, "--effort", SUBSCRIPTION_EFFORT.get(task, "low"), "--system-prompt", system,
            "--tools", "", "--no-session-persistence", "--setting-sources", "", "--strict-mcp-config",
        ]

    def _cli_structured(self, task: Task, system: str, messages: list[dict] | str, output_model: type[T]) -> T:
        args = self._cli_args(task, system) + [
            "--output-format", "json", "--json-schema", json.dumps(output_model.model_json_schema()),
        ]
        proc = self.runner(args, _as_prompt(messages), _cli_env())
        result = _parse_cli_json(proc)
        self._log_cli_usage(task, result)
        if result.get("is_error"):
            raise ClaudeError(_cli_error_message(str(result.get("result", ""))))
        data = result.get("structured_output")
        if data is None:
            raise ClaudeError("Claude Code returned no structured result. Try again.")
        try:
            return output_model.model_validate(data)
        except ValidationError as e:
            raise ClaudeError("Claude Code's answer didn't match the expected format. Try again.") from e

    def _cli_stream(self, task: Task, system: str, messages: list[dict] | str) -> Iterator[str]:
        """Parse `--output-format stream-json` text deltas, live when a streamer is available."""
        args = self._cli_args(task, system) + ["--output-format", "stream-json", "--verbose", "--include-partial-messages"]
        if self.streamer is not None:
            lines: Iterator[str] = self.streamer(args, _as_prompt(messages), _cli_env())
        else:
            lines = iter((self.runner(args, _as_prompt(messages), _cli_env()).stdout or "").splitlines())
        final: dict = {}
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "stream_event":
                delta = event.get("event", {}).get("delta", {})
                if delta.get("type") == "text_delta":
                    yield delta.get("text", "")
            elif event.get("type") == "result":
                final = event
        self._log_cli_usage(task, final)
        if not final or final.get("is_error"):
            raise ClaudeError(_cli_error_message(str(final.get("result", ""))))

    def _log_cli_usage(self, task: Task, result: dict) -> None:
        usage = result.get("usage") or {}
        if not usage.get("input_tokens") and not usage.get("output_tokens"):
            return
        model = next(iter(result.get("modelUsage") or {}), SONNET)
        self._record(
            task, model, usage.get("input_tokens", 0), usage.get("output_tokens", 0),
            usage.get("cache_read_input_tokens", 0), usage.get("cache_creation_input_tokens", 0),
            0.0, result.get("session_id"),
        )

    def _record(self, task: Task, model: str, input_tokens: int, output_tokens: int, cache_read: int,
                cache_write: int, cost: float, request_id: str | None) -> None:
        self.session.add(
            ApiUsage(
                task=task.value, model=model, backend=self.backend.value,
                input_tokens=input_tokens, output_tokens=output_tokens,
                cache_read_tokens=cache_read, cache_write_tokens=cache_write,
                cost_usd=cost, request_id=request_id,
            )
        )
        self.session.commit()


CLI_TIMEOUT_SECONDS = 300


def _cli_runner(cli: str) -> Runner:
    def run(args: list[str], prompt: str, env: dict) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                [cli, *args], input=prompt, capture_output=True, text=True, encoding="utf-8",
                env=env, cwd=tempfile.gettempdir(), timeout=CLI_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as e:
            raise ClaudeError("Claude Code took too long to answer. Try again.") from e
        except OSError as e:
            raise ClaudeUnavailable(f"Couldn't start Claude Code: {e}") from e

    return run


def _cli_env() -> dict:
    """The environment for `claude -p`, without API credentials.

    Claude Code prefers ANTHROPIC_API_KEY over your login when it's set, which
    would silently bill the API instead of your subscription.
    """
    return {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}


def _cli_streamer(cli: str) -> LineStreamer:
    def stream(args: list[str], prompt: str, env: dict) -> Iterator[str]:
        try:
            proc = subprocess.Popen(
                [cli, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", env=env, cwd=tempfile.gettempdir(),
            )
        except OSError as e:
            raise ClaudeUnavailable(f"Couldn't start Claude Code: {e}") from e
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
            yield from proc.stdout  # errors arrive as an is_error result event, not on stderr
            proc.wait(timeout=CLI_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as e:
            raise ClaudeError("Claude Code took too long to answer. Try again.") from e
        finally:
            if proc.poll() is None:
                proc.kill()

    return stream


def _as_prompt(messages: list[dict] | str) -> str:
    if isinstance(messages, str):
        return messages
    if len(messages) == 1:
        return str(messages[0]["content"])
    lines = [f"{m['role'].upper()}: {m['content']}" for m in messages]
    return "Conversation so far:\n\n" + "\n\n".join(lines) + "\n\nWrite the next ASSISTANT reply only."


def _parse_cli_json(proc: subprocess.CompletedProcess) -> dict:
    try:
        return json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError):
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise ClaudeError(f"Claude Code failed: {detail[-1] if detail else 'no output'}")


def _cli_error_message(result: str) -> str:
    text = result.lower()
    if any(word in text for word in ("oauth", "authenticate", "log in", "login", "not logged")):
        return "Claude Code isn't logged in, or its login expired. In a terminal, run `claude`, then /login."
    if "limit" in text:
        return "You've reached your Claude plan's usage limit. Try again later, or switch to an API key in Settings."
    return f"Claude Code error: {result or 'unknown error'}"


# --- Spend ---------------------------------------------------------------------

@dataclass(frozen=True)
class SpendStatus:
    spent_usd: float
    budget_usd: float | None

    @property
    def warning(self) -> bool:
        return bool(self.budget_usd) and self.spent_usd >= self.budget_usd * BUDGET_WARNING_RATIO


def month_spend(session: Session, now: datetime | None = None) -> SpendStatus:
    """API spend this month; subscription calls cost nothing extra."""
    now = now or datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    spent = session.exec(
        select(func.coalesce(func.sum(ApiUsage.cost_usd), 0.0)).where(
            ApiUsage.created_at >= month_start, ApiUsage.backend == Backend.api.value
        )
    ).one()
    budget = session.get(Setting, "api_budget_usd_month")
    return SpendStatus(spent_usd=float(spent), budget_usd=float(budget.value) if budget else None)

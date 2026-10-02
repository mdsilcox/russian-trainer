"""Single entry point for every Claude API call.

- The key comes from ANTHROPIC_API_KEY (via app.config); nothing is stored.
- Each task maps to a model: Sonnet where quality matters (story feedback,
  role-play), Haiku for cheap bulk work (card enrichment, drill generation).
- Structured results use structured outputs (`output_format=<Pydantic model>`),
  which guarantees schema-valid JSON.
- System prompts are cached (top-level cache_control), so repeated calls with
  the same tutor prompt pay ~10% for that prefix.
- Sonnet calls opt into server-side refusal fallbacks.
- The SDK retries 408/409/429/5xx/connection errors with exponential backoff.
- Every call's token usage and estimated cost go to the api_usage table.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TypeVar

import anthropic
from pydantic import BaseModel
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
    answer_check = "answer_check"
    deck_generation = "deck_generation"


SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-4-5"

TASK_MODELS: dict[Task, str] = {
    Task.feedback: SONNET,
    Task.roleplay: SONNET,
    Task.roleplay_corrections: SONNET,
    Task.enrichment: HAIKU,
    Task.drill_generation: HAIKU,
    Task.answer_check: HAIKU,
    Task.deck_generation: HAIKU,
}

# Effort for Sonnet tasks (Haiku 4.5 doesn't take effort). Chat stays snappy.
TASK_EFFORT: dict[Task, str] = {
    Task.feedback: "medium",
    Task.roleplay: "low",
    Task.roleplay_corrections: "low",
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
    """ANTHROPIC_API_KEY isn't set, so AI features are off."""


class ClaudeRefusal(ClaudeError):
    """The model declined the request (stop_reason == "refusal")."""


class ClaudeTruncated(ClaudeError):
    """The response hit max_tokens before finishing."""


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


class ClaudeClient:
    def __init__(self, session: Session, client: anthropic.Anthropic | None = None):
        self.session = session
        if client is None:
            config = get_config()
            if not config.has_api_key:
                raise ClaudeUnavailable("Set ANTHROPIC_API_KEY and restart to use AI features.")
            client = anthropic.Anthropic(api_key=config.api_key, max_retries=4)
        self.client = client

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

    def ask_structured(
        self,
        task: Task,
        system: str,
        messages: list[dict] | str,
        output_model: type[T],
        max_tokens: int = 16000,
    ) -> T:
        """One request whose answer is validated into `output_model`."""
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        with _friendly_errors():
            response = self.client.beta.messages.parse(
                **self._request_args(task, system, max_tokens),
                messages=messages,
                output_format=output_model,
            )
        self._log_usage(task, response)
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
        args = self._request_args(task, system, max_tokens)
        with _friendly_errors(), self.client.beta.messages.stream(**args, messages=messages) as stream:
            yield from stream.text_stream
            response = stream.get_final_message()
        self._log_usage(task, response)
        self._check_stop(response)

    @staticmethod
    def _check_stop(response) -> None:
        if response.stop_reason == "refusal":
            raise ClaudeRefusal("Claude declined this request. Try rephrasing it.")
        if response.stop_reason == "max_tokens":
            raise ClaudeTruncated("The response was cut off. Try a shorter text.")

    def _log_usage(self, task: Task, response) -> None:
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
        self.session.add(
            ApiUsage(
                task=task.value,
                model=model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
                cost_usd=cost,
                request_id=getattr(response, "_request_id", None),
            )
        )
        self.session.commit()


@dataclass(frozen=True)
class SpendStatus:
    spent_usd: float
    budget_usd: float | None

    @property
    def warning(self) -> bool:
        return bool(self.budget_usd) and self.spent_usd >= self.budget_usd * BUDGET_WARNING_RATIO


def month_spend(session: Session, now: datetime | None = None) -> SpendStatus:
    now = now or datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    spent = session.exec(
        select(func.coalesce(func.sum(ApiUsage.cost_usd), 0.0)).where(ApiUsage.created_at >= month_start)
    ).one()
    budget = session.get(Setting, "api_budget_usd_month")
    return SpendStatus(spent_usd=float(spent), budget_usd=float(budget.value) if budget else None)

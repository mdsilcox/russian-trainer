import json
import subprocess

import pytest
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session, select

from app.db import MIGRATIONS, make_engine, migrate
from app.models import ApiUsage, Setting
from app.services import claude
from app.services.claude import Backend, ClaudeClient, ClaudeError, Task


class Word(BaseModel):
    ru_stressed: str
    en: str


def cli_result(structured=None, is_error=False, result="", usage=None):
    return {
        "type": "result", "is_error": is_error, "result": result, "structured_output": structured,
        "session_id": "sess-1", "usage": usage if usage is not None else {"input_tokens": 120, "output_tokens": 40},
        "modelUsage": {"claude-sonnet-5-5": {}}, "total_cost_usd": 0.001,
    }


class FakeCli:
    def __init__(self, stdout: str, stderr: str = ""):
        self.stdout, self.stderr, self.calls = stdout, stderr, []

    def __call__(self, args, prompt, env):
        self.calls.append((args, prompt, env))
        return subprocess.CompletedProcess(args, 0, self.stdout, self.stderr)


def test_structured_call_args_prompt_and_env(session, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    fake = FakeCli(json.dumps(cli_result({"ru_stressed": "вокза\u0301л", "en": "station"})))
    word = ClaudeClient(session, runner=fake).ask_structured(Task.enrichment, "Be a tutor.", "вокзал", Word)

    assert word == Word(ru_stressed="вокза\u0301л", en="station")
    args, prompt, env = fake.calls[0]
    assert prompt == "вокзал"
    assert args[args.index("--model") + 1] == claude.SONNET  # subscription: Sonnet for everything
    assert args[args.index("--effort") + 1] == "low"
    assert args[args.index("--system-prompt") + 1] == "Be a tutor." + claude.SPELLING
    assert args[args.index("--tools") + 1] == ""
    assert json.loads(args[args.index("--json-schema") + 1])["required"] == ["ru_stressed", "en"]
    assert "--no-session-persistence" in args
    assert "ANTHROPIC_API_KEY" not in env  # otherwise Claude Code would bill the API


def test_feedback_uses_medium_effort(session):
    fake = FakeCli(json.dumps(cli_result({"ru_stressed": "a", "en": "b"})))
    ClaudeClient(session, runner=fake).ask_structured(Task.feedback, "s", "x", Word)
    args = fake.calls[0][0]
    assert args[args.index("--model") + 1] == claude.SONNET
    assert args[args.index("--effort") + 1] == "medium"


def test_usage_logged_as_subscription_and_free(session):
    fake = FakeCli(json.dumps(cli_result({"ru_stressed": "a", "en": "b"})))
    ClaudeClient(session, runner=fake).ask_structured(Task.enrichment, "s", "x", Word)
    row = session.exec(select(ApiUsage)).one()
    assert (row.backend, row.cost_usd, row.input_tokens, row.model) == ("subscription", 0.0, 120, "claude-sonnet-5-5")
    session.add(ApiUsage(task="feedback", model=claude.SONNET, backend="api", input_tokens=1, output_tokens=1, cost_usd=0.5))
    session.commit()
    assert claude.month_spend(session).spent_usd == pytest.approx(0.5)


@pytest.mark.parametrize("result, expected", [
    ("Failed to authenticate: OAuth session expired and could not be refreshed", "/login"),
    ("Claude usage limit reached. Resets at 5pm", "usage limit"),
    ("Something odd", "Claude Code error: Something odd"),
])
def test_cli_errors_become_friendly_messages(session, result, expected):
    fake = FakeCli(json.dumps(cli_result(is_error=True, result=result, usage={})))
    with pytest.raises(ClaudeError, match=expected.replace("/", "/")):
        ClaudeClient(session, runner=fake).ask_structured(Task.enrichment, "s", "x", Word)


def test_missing_or_invalid_structured_output(session):
    with pytest.raises(ClaudeError, match="no structured result"):
        ClaudeClient(session, runner=FakeCli(json.dumps(cli_result(None)))).ask_structured(Task.enrichment, "s", "x", Word)
    with pytest.raises(ClaudeError, match="didn't match"):
        ClaudeClient(session, runner=FakeCli(json.dumps(cli_result({"en": "only"})))).ask_structured(
            Task.enrichment, "s", "x", Word)


def test_non_json_output_reports_stderr(session):
    with pytest.raises(ClaudeError, match="boom"):
        ClaudeClient(session, runner=FakeCli("", "line one\nboom")).ask_structured(Task.enrichment, "s", "x", Word)


def test_stream_yields_text_deltas(session):
    events = [
        {"type": "system", "subtype": "init"},
        {"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": "Здравствуйте"}}},
        {"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": "!"}}},
        cli_result(),
    ]
    fake = FakeCli("\n".join(json.dumps(e) for e in events))
    chunks = list(ClaudeClient(session, runner=fake).stream_text(
        Task.roleplay, "s", [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}, {"role": "user", "content": "c"}]))
    assert "".join(chunks) == "Здравствуйте!"
    args, prompt, _ = fake.calls[0]
    assert "stream-json" in args and "USER: a" in prompt and "ASSISTANT: b" in prompt


def test_backend_setting_round_trip(session, monkeypatch):
    claude.set_backend(session, Backend.subscription)
    assert session.get(Setting, "ai_backend").value == "subscription"
    monkeypatch.setitem(claude._current, "backend", Backend.api)
    assert claude.load_backend(session) == Backend.subscription


def test_ai_status_for_subscription_depends_on_cli(monkeypatch):
    monkeypatch.setattr(claude, "claude_cli", lambda: None)
    available, reason = claude.ai_status(Backend.subscription)
    assert not available and "install Claude Code" in reason
    monkeypatch.setattr(claude, "claude_cli", lambda: "C:/claude.exe")
    assert claude.ai_status(Backend.subscription) == (True, "")


def test_settings_toggle(client, session, monkeypatch):
    monkeypatch.setattr(claude, "claude_cli", lambda: "C:/claude.exe")
    page = client.get("/settings").text
    assert "Claude subscription (via Claude Code)" in page and "Anthropic API key" in page
    client.post("/settings/ai-backend", data={"backend": "subscription"})
    assert claude.current_backend() == Backend.subscription
    assert session.get(Setting, "ai_backend").value == "subscription"
    client.post("/settings/ai-backend", data={"backend": "nonsense"})
    assert claude.current_backend() == Backend.subscription


def test_migration_adds_backend_column_to_existing_db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:  # a database as it was at schema version 3
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version VALUES (3)"))
        conn.execute(text("CREATE TABLE settings (key VARCHAR PRIMARY KEY, value JSON)"))
        conn.execute(text(
            "CREATE TABLE api_usage (id INTEGER PRIMARY KEY, task VARCHAR, model VARCHAR, input_tokens INTEGER, "
            "output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER, cost_usd FLOAT, "
            "request_id VARCHAR, created_at DATETIME)"))
        conn.execute(text("INSERT INTO api_usage (task, model, input_tokens, output_tokens, cost_usd) VALUES ('f','m',1,1,0.1)"))
    assert migrate(engine) == len(MIGRATIONS)
    with Session(engine) as s:
        assert s.exec(text("SELECT backend FROM api_usage")).one()[0] == "api"
        assert s.get(Setting, "ai_backend").value == "subscription"

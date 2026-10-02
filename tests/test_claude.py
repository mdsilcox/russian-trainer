from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from sqlmodel import select

from app.config import get_config
from app.models import ApiUsage
from app.services.claude import (
    HAIKU,
    SONNET,
    ClaudeClient,
    ClaudeRefusal,
    ClaudeTruncated,
    ClaudeUnavailable,
    Task,
    month_spend,
)


class Answer(BaseModel):
    ok: bool


def fake_response(model=SONNET, stop_reason="end_turn", parsed=None, **usage):
    usage = {"input_tokens": 1000, "output_tokens": 500, "cache_read_input_tokens": 0,
             "cache_creation_input_tokens": 0, **usage}
    return SimpleNamespace(model=model, stop_reason=stop_reason, parsed_output=parsed,
                           usage=SimpleNamespace(**usage), _request_id="req_test")


class FakeAnthropic:
    def __init__(self, response):
        self.calls = []
        self.response = response
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def test_missing_key_raises(session, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_config.cache_clear()
    try:
        with pytest.raises(ClaudeUnavailable):
            ClaudeClient(session)
    finally:
        get_config.cache_clear()


def test_sonnet_task_request_shape_and_usage_logged(session):
    fake = FakeAnthropic(fake_response(parsed=Answer(ok=True)))
    result = ClaudeClient(session, client=fake).ask_structured(Task.feedback, "system", "hi", Answer)

    assert result.ok
    call = fake.calls[0]
    assert call["model"] == SONNET
    assert call["output_format"] is Answer
    assert call["cache_control"] == {"type": "ephemeral"}
    assert call["fallbacks"] == "default"
    assert call["output_config"] == {"effort": "medium"}
    assert call["messages"] == [{"role": "user", "content": "hi"}]

    row = session.exec(select(ApiUsage)).one()
    assert row.task == "feedback"
    assert row.cost_usd == pytest.approx((1000 * 2.00 + 500 * 10.00) / 1_000_000)


def test_haiku_task_omits_effort_and_fallbacks(session):
    fake = FakeAnthropic(fake_response(model=HAIKU, parsed=Answer(ok=True)))
    ClaudeClient(session, client=fake).ask_structured(Task.enrichment, "system", "hi", Answer)
    call = fake.calls[0]
    assert call["model"] == HAIKU
    assert "output_config" not in call and "fallbacks" not in call and "betas" not in call


@pytest.mark.parametrize("stop_reason, error", [("refusal", ClaudeRefusal), ("max_tokens", ClaudeTruncated)])
def test_bad_stop_reasons_raise_but_still_log(session, stop_reason, error):
    fake = FakeAnthropic(fake_response(stop_reason=stop_reason))
    with pytest.raises(error):
        ClaudeClient(session, client=fake).ask_structured(Task.feedback, "s", "hi", Answer)
    assert len(session.exec(select(ApiUsage)).all()) == 1


def test_month_spend_and_budget_warning(session):
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    session.add(ApiUsage(task="feedback", model=SONNET, input_tokens=0, output_tokens=0, cost_usd=9.0,
                         created_at=datetime(2026, 10, 2, tzinfo=timezone.utc)))
    session.add(ApiUsage(task="feedback", model=SONNET, input_tokens=0, output_tokens=0, cost_usd=5.0,
                         created_at=datetime(2026, 9, 30, tzinfo=timezone.utc)))
    session.commit()
    status = month_spend(session, now=now)
    assert status.spent_usd == pytest.approx(9.0)
    assert status.budget_usd == 10
    assert status.warning

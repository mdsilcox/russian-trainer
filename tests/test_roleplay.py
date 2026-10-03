from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from app.models import Card, Category, Conversation, Mistake, Module, Scenario
from app.services import roleplay
from app.services.claude import Task
from app.services.feedback import Issue
from app.services.roleplay import Debrief, DebriefPhrase, Hint, TurnReview

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, reply="Куда́ е́дем?", structured=None):
        self.reply, self.structured = reply, structured or {}
        self.calls = []

    def stream_text(self, task, system, messages, max_tokens=4000):
        self.calls.append((task, system, messages))
        yield from [self.reply[: len(self.reply) // 2], self.reply[len(self.reply) // 2:]]

    def ask_structured(self, task, system, prompt, model, max_tokens=16000):
        self.calls.append((task, system, prompt))
        return self.structured[model]


def taxi(db) -> Scenario:
    s = Scenario(slug="taxi", title="Taxi to the theater", setting="You get into a taxi at your hotel.",
                 partner_role="taxi driver", persona="A chatty driver in his fifties.",
                 opening_ru="Здра́вствуйте! Куда́ е́дем?", goals_json=["Give the address", "Ask the price", "Pay"])
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def chat(db, level=1):
    conv = roleplay.start(db, taxi(db), level, NOW)
    return conv


def test_start_saves_the_opening_line_and_validates_level(session):
    conv = chat(session, 2)
    [opening] = roleplay.messages(session, conv)
    assert (opening.role, opening.content, conv.level) == ("partner", "Здра́вствуйте! Куда́ е́дем?", 2)
    with pytest.raises(ValueError):
        roleplay.start(session, session.get(Scenario, conv.scenario_id), 4)


def test_partner_messages_open_with_a_stage_direction_and_alternate(session):
    conv = chat(session)
    roleplay.add_learner_turn(session, conv, "В Большо́й теа́тр.", NOW + timedelta(seconds=1))
    msgs = roleplay.partner_messages(roleplay.messages(session, conv))
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[1]["content"].startswith("Здра́вствуйте")


def test_partner_stream_yields_chunks_saves_reply_and_uses_level_style(session):
    conv = chat(session, 3)
    roleplay.add_learner_turn(session, conv, "В Большо́й теа́тр.", NOW + timedelta(seconds=1))
    client = FakeClient("Поня́л, щас пое́дем.")
    assert "".join(roleplay.partner_stream(session, client, conv, NOW + timedelta(seconds=2))) == "Поня́л, щас пое́дем."
    task, system, _ = client.calls[0]
    assert task == Task.roleplay and "taxi driver" in system and "colloquial" in system and "Speak ONLY Russian" in system
    assert roleplay.messages(session, conv)[-1].content == "Поня́л, щас пое́дем."


def test_partner_only_replies_to_a_learner_turn(session):
    conv = chat(session)
    with pytest.raises(ValueError):
        list(roleplay.partner_stream(session, FakeClient(), conv))


def test_review_stores_corrections_routes_mistakes_and_accumulates_goals(session):
    conv = chat(session)
    msg = roleplay.add_learner_turn(session, conv, "Я хочу в Большой театре. Сколько стоит?", NOW + timedelta(seconds=1))
    review = TurnReview(issues=[
        Issue(wrong="в Большой театре", right="в Большо́й теа́тр", category="case", subcategory="accusative for direction",
              explanation="в + accusative for where you are going.", severity="error"),
        Issue(wrong="not in the line", right="x", category="case", subcategory="", explanation="", severity="error"),
        Issue(wrong="Я хочу", right="Мне", category="idiom", subcategory="", explanation="", severity="style"),
    ], better="Мне в Большо́й теа́тр. Ско́лько сто́ит?", goals_met=[0, 1, 7])
    out = roleplay.review_turn(session, FakeClient(structured={TurnReview: review}), conv, msg)

    assert [i.wrong for i in out.issues] == ["в Большой театре", "Я хочу"]  # unplaceable issue dropped
    issues, better = roleplay.corrections(session.get(type(msg), msg.id))
    assert [i.right for i in issues] == ["в Большо́й теа́тр", "Мне"] and better.startswith("Мне")
    assert session.get(Conversation, conv.id).goals_met_json == [0, 1]  # out-of-range goal ignored
    logged = session.exec(select(Mistake)).all()
    assert [(m.module, m.category, m.ref_id) for m in logged] == [(Module.scenario, Category.case, conv.id)]  # style not logged
    assert logged[0].wrong == "в Большой театре"

    msg2 = roleplay.add_learner_turn(session, conv, "Вот деньги.", NOW + timedelta(seconds=5))
    roleplay.review_turn(session, FakeClient(structured={TurnReview: TurnReview(issues=[], better=None, goals_met=[2])}), conv, msg2)
    assert session.get(Conversation, conv.id).goals_met_json == [0, 1, 2]  # goals accumulate


def test_vocabulary_mistakes_become_cards(session):
    conv = chat(session)
    msg = roleplay.add_learner_turn(session, conv, "Я хочу оплатить картой кредит.", NOW + timedelta(seconds=1))
    review = TurnReview(issues=[Issue(wrong="картой кредит", right="креди́тной ка́ртой", category="word_choice",
                                      subcategory="paying by card", explanation="Say креди́тной ка́ртой.", severity="error")],
                        better=None, goals_met=[])
    roleplay.review_turn(session, FakeClient(structured={TurnReview: review}), conv, msg)
    card = session.exec(select(Card)).one()
    assert card.source_module == Module.scenario and card.example_ru == "Я хочу оплатить картой кредит."


def test_hint_mentions_only_open_goals(session):
    conv = chat(session)
    conv.goals_met_json = [0]
    client = FakeClient(structured={Hint: Hint(ru="Ско́лько сто́ит?", en="How much is it?", tip="сто́ит")})
    assert roleplay.hint(session, client, conv).ru == "Ско́лько сто́ит?"
    prompt = client.calls[0][2]
    assert "Ask the price; Pay" in prompt and "Give the address;" not in prompt


def test_debrief_is_computed_once_and_capped(session):
    conv = chat(session)
    phrase = DebriefPhrase(ru="сда́ча", en="change", example_ru="Сда́чи не на́до.", example_en="Keep the change.", why="paying")
    client = FakeClient(structured={Debrief: Debrief(summary="Good.", phrases=[phrase] * 7, next_level_tip="Try level 2.")})
    first = roleplay.debrief(session, client, conv)
    assert len(first.phrases) == 5 and session.get(Conversation, conv.id).debrief_json["summary"] == "Good."

    class Boom:
        def ask_structured(self, *a, **k):
            raise AssertionError("should be cached")

    assert roleplay.debrief(session, Boom(), conv).summary == "Good."


def test_ended_conversation_takes_no_turns(session):
    conv = chat(session)
    roleplay.end(session, conv, NOW)
    with pytest.raises(ValueError):
        roleplay.add_learner_turn(session, conv, "Ещё?")


def test_live_cli_streamer_is_used_when_present(session):
    """The subscription backend streams line by line through the streamer, not the buffered runner."""
    import json

    from app.services.claude import Backend, ClaudeClient

    events = [json.dumps({"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": t}}}) for t in ("При", "вет")]
    events.append(json.dumps({"type": "result", "usage": {}, "is_error": False}))

    def runner(*a):
        raise AssertionError("buffered runner should not be used")

    client = ClaudeClient(session, backend=Backend.subscription, runner=runner, streamer=lambda *a: iter(events))
    assert "".join(client.stream_text(Task.roleplay, "s", [{"role": "user", "content": "x"}])) == "Привет"

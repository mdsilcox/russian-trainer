"""Feature 1: the activity table, its service and the writers."""

from datetime import timedelta

import pytest
from sqlalchemy import text

from tc_compare import act, local_day_of
from tc_helpers import (NOON, TODAY, add_attempt, add_conversation, add_drill_answer, add_drill_set, add_input,
                     add_message, add_review, add_session, add_story, all_kinds_world, at_local, naive_utc,
                     new_card_state)

D = TODAY - timedelta(days=2)


# --- table, record, between -------------------------------------------------------------------


def test_f1_activity_table_and_kinds(engine):
    from sqlalchemy import inspect
    from sqlmodel import SQLModel

    from app.services import activity

    assert tuple(activity.KINDS) == ("session", "review", "drill_answer", "story_attempt", "roleplay_turn", "input")
    assert "activity" in inspect(engine).get_table_names()
    cols = {c["name"] for c in inspect(engine).get_columns("activity")}
    assert {"id", "kind", "ref_id", "at", "day", "minutes", "detail"} <= cols
    assert "activity" in SQLModel.metadata.tables


def test_f1_record_upserts(session):
    from app.services import activity

    first = activity.record(session, "input", 9001, at_local(D), D, 10.0, {"kind": "reading"})
    session.commit()
    second = activity.record(session, "input", 9001, at_local(D, 14), D + timedelta(days=1), 25.0, {"kind": "watching"})
    session.commit()
    other = activity.record(session, "review", 9001, at_local(D), D, 0.0, {"rating": 3, "state_before": 0})
    session.commit()
    rows = [r for r in act(session) if r["ref_id"] == 9001]
    assert len(rows) == 2
    inp = next(r for r in rows if r["kind"] == "input")
    assert inp["day"] == D + timedelta(days=1) and inp["minutes"] == 25.0 and inp["detail"] == {"kind": "watching"}
    assert first.id == second.id != other.id
    assert inp["at"] == naive_utc(at_local(D, 14))


def test_f1_between_filters_and_orders(session):
    from app.services import activity

    for i, (kind, offset) in enumerate([("review", 5), ("input", 3), ("review", 1), ("session", 4), ("review", 9)]):
        day = TODAY - timedelta(days=offset)
        activity.record(session, kind, 100 + i, at_local(day), day, 0.0, None)
    session.commit()
    got = activity.between(session, TODAY - timedelta(days=5), TODAY - timedelta(days=1))
    assert [a.day for a in got] == [TODAY - timedelta(days=d) for d in (5, 4, 3, 1)]
    only = activity.between(session, TODAY - timedelta(days=9), TODAY, kinds=["review"])
    assert [a.ref_id for a in only] == [104, 100, 102]
    both = activity.between(session, TODAY - timedelta(days=9), TODAY, kinds=("input", "session"))
    assert {a.kind for a in both} == {"input", "session"}
    assert activity.between(session, TODAY + timedelta(days=1), TODAY + timedelta(days=5)) == []


def test_f1_kind_ref_unique(session):
    from sqlalchemy.exc import IntegrityError

    from app.services import activity

    activity.record(session, "input", 77, at_local(D), D, 5.0, None)
    session.commit()
    with pytest.raises(IntegrityError):
        session.exec(text(
            "INSERT INTO activity (kind, ref_id, at, day, minutes, detail) "
            "VALUES ('input', 77, '2026-10-01 10:00:00.000000', '2026-10-01', 1.0, '{}')"))
        session.commit()
    session.rollback()


# --- direct ORM inserts (trap 1) ---------------------------------------------------------------


def test_f1_orm_insert_creates_activity_session(session):
    row = add_session(session, D, 25.5, True, reviews=4, new_cards=2)
    rows = act(session, "session")
    assert len(rows) == 1
    assert (rows[0]["ref_id"], rows[0]["day"], rows[0]["minutes"]) == (row.id, D, 25.5)
    assert rows[0]["detail"] == {"completed": True, "reviews": 4, "new_cards": 2}


def test_f1_orm_insert_creates_activity_incomplete_session(session):
    row = add_session(session, D, 12.0, False)
    rows = act(session, "session")
    assert len(rows) == 1 and rows[0]["minutes"] == 12.0 and rows[0]["detail"]["completed"] is False
    assert rows[0]["ref_id"] == row.id


def test_f1_orm_insert_creates_activity_review(session):
    cs = new_card_state(session)
    row = add_review(session, cs, D, rating=1, state_before=2, hour=22)
    rows = act(session, "review")
    assert len(rows) == 1
    assert (rows[0]["ref_id"], rows[0]["day"], rows[0]["minutes"]) == (row.id, D, 0)
    assert rows[0]["detail"] == {"rating": 1, "state_before": 2}
    assert rows[0]["at"] == naive_utc(row.reviewed_at)


def test_f1_orm_insert_creates_activity_input(session):
    row = add_input(session, D, 30, "listening")
    rows = act(session, "input")
    assert len(rows) == 1
    assert (rows[0]["ref_id"], rows[0]["day"], rows[0]["minutes"]) == (row.id, D, 30)
    assert rows[0]["detail"] == {"kind": "listening"}


def test_f1_orm_insert_creates_activity_story_attempt(session):
    story = add_story(session)
    row = add_attempt(session, story, D)
    rows = act(session, "story_attempt")
    assert len(rows) == 1 and (rows[0]["ref_id"], rows[0]["day"], rows[0]["minutes"]) == (row.id, D, 0)
    assert rows[0]["detail"] == {"story_id": story.id}


def test_f1_orm_insert_creates_activity_drill_answer(session):
    ds = add_drill_set(session)
    add_drill_answer(session, ds, D, correct=False)
    rows = act(session, "drill_answer")
    assert len(rows) == 1 and rows[0]["day"] == D and rows[0]["detail"] == {"correct": False}


def test_f1_orm_insert_creates_activity_roleplay_turn(session):
    conv = add_conversation(session)
    row = add_message(session, conv, "user", D)
    rows = act(session, "roleplay_turn")
    assert len(rows) == 1 and (rows[0]["ref_id"], rows[0]["day"]) == (row.id, D)
    assert rows[0]["detail"] == {"conversation_id": conv.id}


def test_f1_orm_update_session_updates_row(session):
    row = add_session(session, D, 10.0, False)
    row.minutes, row.completed, row.reviews = 40.0, True, 7
    session.add(row)
    session.commit()
    rows = act(session, "session")
    assert len(rows) == 1
    assert rows[0]["minutes"] == 40.0 and rows[0]["detail"] == {"completed": True, "reviews": 7, "new_cards": 0}


def test_f1_partner_messages_not_recorded(session):
    from app.models import Scenario
    from app.services import roleplay

    conv = add_conversation(session)
    add_message(session, conv, "partner", D)
    add_message(session, conv, "partner", D, hour=13)
    assert act(session, "roleplay_turn") == []
    # starting a conversation says the opening line as the partner
    scenario = session.get(Scenario, conv.scenario_id)
    roleplay.start(session, scenario, 1, now=at_local(D))
    assert act(session, "roleplay_turn") == []
    roleplay.add_learner_turn(session, conv, "Здравствуйте", now=at_local(D, 13))
    assert len(act(session, "roleplay_turn")) == 1


# --- through the services ------------------------------------------------------------------------


def test_f1_service_review_creates_activity(session):
    from fsrs import Rating

    from app.services import srs

    cs = new_card_state(session)
    log = srs.review(session, cs, Rating.Good, now=at_local(D))
    rows = act(session, "review")
    assert len(rows) == 1
    assert (rows[0]["ref_id"], rows[0]["day"]) == (log.id, D)
    assert rows[0]["detail"] == {"rating": int(Rating.Good), "state_before": log.state_before}


def test_f1_service_drill_answers_create_activity(session):
    from sqlmodel import select

    from app.models import DrillAnswer
    from app.services import drill_player

    def item(answer):
        return {"format": "numeral", "prompt_ru": "Биле́т сто́ит пять ___.", "cue": "рубль", "translation_en": "x",
                "answer": answer, "accepted": [], "rule": "r", "topic": "", "topic_label": "L", "category": "case"}

    ds = add_drill_set(session)
    ds.items_json = [item("рублей"), item("книг")]
    session.add(ds)
    session.commit()
    drill_player.submit(session, ds, 0, "рублей", 1, now=NOON)
    drill_player.submit(session, ds, 1, "wrong", 1, now=NOON)  # first miss: not stored yet
    assert len(act(session, "drill_answer")) == 1
    drill_player.submit(session, ds, 1, "wrong", 2, now=NOON)
    rows = act(session, "drill_answer")
    stored = session.exec(select(DrillAnswer).order_by(DrillAnswer.id)).all()
    assert len(rows) == 2 == len(stored)
    assert [r["detail"] for r in rows] == [{"correct": True}, {"correct": False}]
    assert [r["day"] for r in rows] == [local_day_of(s.created_at) for s in stored]


def test_f1_service_add_attempt_creates_activity(session):
    from app.services import workshop

    story = add_story(session)
    attempt = workshop.add_attempt(session, story, "Моя история")
    rows = act(session, "story_attempt")
    assert len(rows) == 1 and rows[0]["ref_id"] == attempt.id
    assert rows[0]["day"] == local_day_of(attempt.created_at) and rows[0]["detail"] == {"story_id": story.id}


def test_f1_service_log_minutes_creates_activity(session):
    from app.services import shelf

    entry = shelf.log_minutes(session, 20, "reading", now=at_local(D))
    rows = act(session, "input")
    assert len(rows) == 1 and rows[0]["ref_id"] == entry.id
    assert (rows[0]["day"], rows[0]["minutes"], rows[0]["detail"]) == (D, 20, {"kind": "reading"})


def test_f1_service_learner_turn_creates_activity(session):
    from app.models import Scenario
    from app.services import roleplay

    conv = add_conversation(session)
    scenario = session.get(Scenario, conv.scenario_id)
    conv2 = roleplay.start(session, scenario, 1, now=at_local(D))
    msg = roleplay.add_learner_turn(session, conv2, "Привет", now=at_local(D, 15))
    rows = act(session, "roleplay_turn")
    assert len(rows) == 1 and rows[0]["ref_id"] == msg.id
    assert (rows[0]["day"], rows[0]["detail"]) == (D, {"conversation_id": conv2.id})


def test_f1_finish_session_updates_row(session):
    """Trap 3: one activity row per session; finishing updates it."""
    from fsrs import Rating

    from app.services import srs, today

    t0 = at_local(TODAY, 10)
    row = today.start_session(session, now=t0)
    rows = act(session, "session")
    assert len(rows) == 1 and rows[0]["ref_id"] == row.id
    assert rows[0]["detail"]["completed"] is False and rows[0]["minutes"] == 0
    srs.review(session, new_card_state(session), Rating.Good, now=t0 + timedelta(minutes=10))
    done = today.finish_session(session, now=t0 + timedelta(minutes=30))
    assert done is not None and done.completed
    rows = act(session, "session")
    assert len(rows) == 1, "finishing a session must not add a second row"
    assert rows[0]["ref_id"] == row.id and rows[0]["minutes"] == done.minutes == 30.0
    assert rows[0]["detail"] == {"completed": True, "reviews": 1, "new_cards": done.new_cards}
    assert rows[0]["day"] == TODAY


def test_f1_session_day_is_session_date(session):
    """Trap 4: started 23:50 local, finished 00:20 the next day: the row counts for Session.date."""
    from app.services import today

    t0 = at_local(D, 23, 50)
    today.start_session(session, now=t0)
    done = today.finish_session(session, now=t0 + timedelta(minutes=30))
    assert done is not None and done.date == D
    assert local_day_of(t0 + timedelta(minutes=30)) == D + timedelta(days=1)
    rows = act(session, "session")
    assert len(rows) == 1 and rows[0]["day"] == D and rows[0]["minutes"] == 30.0


def test_f1_deleting_sources_keeps_activity(session):
    from sqlalchemy import delete

    from app.models import Conversation, Message
    from app.services import cards, workshop

    world = all_kinds_world(session)
    before = {k: len(act(session, k)) for k in ("review", "story_attempt", "roleplay_turn")}
    assert before == {"review": 1, "story_attempt": 1, "roleplay_turn": 1}
    workshop.delete_story(session, world["story"].id)
    cards.delete_card(session, world["cs"].card_id)
    session.exec(delete(Message).where(Message.conversation_id == world["conv"].id))
    session.exec(delete(Conversation).where(Conversation.id == world["conv"].id))
    session.commit()
    after = {k: len(act(session, k)) for k in before}
    assert after == before

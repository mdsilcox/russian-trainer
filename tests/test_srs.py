from datetime import datetime, timedelta, timezone

import pytest
from fsrs import Rating, State
from sqlmodel import select

from app.models import Card, CardState, ReviewLog, Setting
from app.services import srs

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def add_card(session, ru, *, state=srs.NEW, due=NOW, created=NOW, suspended=False):
    card = Card(ru=ru, en=ru, created_at=created, suspended=suspended)
    session.add(card)
    session.commit()
    cs = CardState(card_id=card.id, state=state, due=due)
    if state != srs.NEW:
        cs.stability, cs.difficulty, cs.last_review = 5.0, 5.0, due - timedelta(days=5)
    session.add(cs)
    session.commit()
    return cs


def test_new_card_good_enters_learning_then_review(session):
    cs = add_card(session, "вокзал")
    log = srs.review(session, cs, Rating.Good, NOW, duration_ms=4200)
    assert log.state_before == srs.NEW and log.duration_ms == 4200
    assert cs.state == State.Learning and cs.reps == 1
    assert srs._utc(cs.due) > NOW

    srs.review(session, cs, Rating.Good, srs._utc(cs.due))
    assert cs.state == State.Review
    assert srs._utc(cs.due) - NOW >= timedelta(days=1)


def test_easy_on_new_card_skips_learning(session):
    cs = add_card(session, "ехать")
    srs.review(session, cs, Rating.Easy, NOW)
    assert cs.state == State.Review


def test_again_on_review_card_counts_lapse(session):
    cs = add_card(session, "идти", state=int(State.Review))
    srs.review(session, cs, Rating.Again, NOW)
    assert cs.state == State.Relearning
    assert cs.lapses == 1
    assert srs._utc(cs.due) < NOW + timedelta(hours=1)


def test_state_survives_db_round_trip(session):
    cs = add_card(session, "молоко")
    srs.review(session, cs, Rating.Good, NOW)
    session.expire_all()
    reloaded = session.get(CardState, cs.id)
    card = srs.to_fsrs(reloaded)
    assert card.state == State.Learning and card.due.tzinfo is not None
    assert len(session.exec(select(ReviewLog)).all()) == 1


def test_retention_setting_used(session):
    session.get(Setting, "desired_retention").value = 0.85
    session.commit()
    assert srs.make_scheduler(session).desired_retention == 0.85


def test_queue_orders_due_reviews_and_excludes_future_and_suspended(session):
    later = add_card(session, "b", state=2, due=NOW - timedelta(hours=1))
    oldest = add_card(session, "a", state=2, due=NOW - timedelta(days=3))
    add_card(session, "future", state=2, due=NOW + timedelta(days=1))
    add_card(session, "suspended", state=2, due=NOW - timedelta(days=9), suspended=True)
    session.get(Setting, "daily_new_cards").value = 0
    session.commit()
    assert [cs.id for cs in srs.build_queue(session, NOW)] == [oldest.id, later.id]


def test_new_card_limit_counts_cards_already_started_today(session):
    session.get(Setting, "daily_new_cards").value = 3
    session.commit()
    first = add_card(session, "n0", created=NOW - timedelta(days=2))
    for i in range(1, 5):
        add_card(session, f"n{i}", created=NOW - timedelta(days=1, minutes=-i))
    srs.review(session, first, Rating.Good, NOW - timedelta(minutes=5))
    queue = srs.build_queue(session, NOW)
    new = [cs for cs in queue if cs.state == srs.NEW]
    assert len(new) == 2
    assert [session.get(Card, cs.card_id).ru for cs in new] == ["n1", "n2"]


def test_new_cards_are_interleaved():
    assert srs.interleave(list("rrrrrr"), list("NN")) == list("rrrNrrrN")
    assert srs.interleave(list("r"), list("NNN")) == list("rNNN")
    assert srs.interleave([], list("NN")) == list("NN")
    assert srs.interleave(list("rr"), []) == list("rr")


def test_max_cards_caps_session(session):
    session.get(Setting, "daily_new_cards").value = 5
    session.commit()
    for i in range(6):
        add_card(session, f"r{i}", state=2, due=NOW - timedelta(days=i + 1))
    for i in range(3):
        add_card(session, f"n{i}")
    assert len(srs.build_queue(session, NOW, max_cards=4)) == 4
    assert len(srs.build_queue(session, NOW, max_cards=8)) == 8


def test_forecast_buckets_overdue_into_today(session):
    add_card(session, "overdue", state=2, due=NOW - timedelta(days=2))
    add_card(session, "tomorrow", state=2, due=srs.day_start(NOW) + timedelta(days=1, hours=3))
    add_card(session, "new-not-counted")
    assert srs.forecast(session, 3, NOW) == [1, 1, 0]

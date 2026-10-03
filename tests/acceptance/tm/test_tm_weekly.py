"""Feature 2: weekly summary."""

from datetime import date, datetime, timedelta, timezone

import pytest

from tm_helpers import day_at, element_with_attr, page_text

MON = date(2026, 9, 14)  # a Monday
WED = MON + timedelta(days=2)
PREV_MON = MON - timedelta(days=7)
SUN_BEFORE = MON - timedelta(days=1)
NEW, LEARNING, REVIEW = 0, 1, 2


def summary(session, now_day, hour=12):
    from app.services import stats

    return stats.weekly_summary(session, day_at(now_day, hour))


def add_session(session, day, minutes, completed=True):
    from app.models import Session as StudySession

    session.add(StudySession(date=day, minutes=minutes, completed=completed))
    session.commit()


def add_input(session, day, minutes):
    from app.models import InputLog

    session.add(InputLog(date=day, minutes=minutes, kind="reading"))
    session.commit()


def card_state(session, key="a"):
    """One recognition card state per key."""
    from sqlmodel import select

    from app.models import Card, CardState

    card = session.exec(select(Card).where(Card.en == key)).first()
    if card is None:
        card = Card(ru=f"слово{key}", en=key)
        session.add(card)
        session.commit()
        session.add(CardState(card_id=card.id))
        session.commit()
    return session.exec(select(CardState).where(CardState.card_id == card.id)).one().id


def add_review(session, when, rating=3, state_before=REVIEW, key="a"):
    from app.models import ReviewLog

    session.add(
        ReviewLog(card_state_id=card_state(session, key), rating=rating, reviewed_at=when, state_before=state_before, due_before=when)
    )
    session.commit()


def test_f2_empty_week(session):
    from app.services import stats

    s = summary(session, WED)
    assert isinstance(s, stats.WeeklySummary)
    assert s.week_start == MON
    assert (s.days_practiced, s.reviews, s.new_cards, s.input_minutes) == (0, 0, 0, 0)
    assert s.minutes == 0
    assert (s.prev_minutes, s.prev_reviews) == (0, 0)
    assert s.retention is None


def test_f2_default_now_uses_current_week(session):
    from app.services import stats

    s = stats.weekly_summary(session)
    today = stats.local_date()
    assert s.week_start.weekday() == 0
    assert 0 <= (today - s.week_start).days <= 6


def test_f2_week_starts_monday(session):
    # Sunday is the last day of its week; Monday starts a new one.
    assert summary(session, SUN_BEFORE).week_start == PREV_MON
    assert summary(session, MON).week_start == MON
    assert summary(session, MON + timedelta(days=6)).week_start == MON
    assert summary(session, MON + timedelta(days=7)).week_start == MON + timedelta(days=7)


def test_f2_sunday_and_monday_boundary_for_sessions(session):
    add_session(session, SUN_BEFORE, 20)
    add_session(session, MON, 7)
    s = summary(session, WED)
    assert s.minutes == pytest.approx(7)
    assert s.prev_minutes == pytest.approx(20)
    # Sunday of the current week counts for the current week when "now" is that Sunday.
    sunday = MON + timedelta(days=6)
    add_session(session, sunday, 11)
    s = summary(session, sunday)
    assert s.minutes == pytest.approx(18)


def test_f2_previous_week(session):
    add_session(session, PREV_MON, 10)
    add_session(session, PREV_MON + timedelta(days=6), 5)
    add_session(session, PREV_MON - timedelta(days=1), 99)  # two weeks ago
    add_session(session, MON, 3)
    add_review(session, day_at(PREV_MON, 9))
    add_review(session, day_at(SUN_BEFORE, 20))
    add_review(session, day_at(PREV_MON - timedelta(days=1), 20))  # two weeks ago
    add_review(session, day_at(WED))
    s = summary(session, WED)
    assert s.prev_minutes == pytest.approx(15)
    assert s.prev_reviews == 2
    assert s.minutes == pytest.approx(3)
    assert s.reviews == 1


def test_f2_review_uses_local_date_of_reviewed_at(session):
    add_review(session, day_at(SUN_BEFORE, 23, 30))
    add_review(session, day_at(MON, 0, 30))
    s = summary(session, WED)
    assert s.reviews == 1
    assert s.prev_reviews == 1


def test_f2_minutes_only_completed_and_rounded(session):
    add_session(session, MON, 12.34)
    add_session(session, WED, 5.0)
    add_session(session, WED, 40.0, completed=False)
    s = summary(session, WED)
    assert s.minutes == pytest.approx(17.3, abs=0.001)
    assert round(s.minutes, 1) == s.minutes
    add_session(session, PREV_MON, 30.0, completed=False)
    assert summary(session, WED).prev_minutes == 0


def test_f2_days_practiced(session):
    add_session(session, MON, 5)
    add_input(session, MON, 20)  # same day: counted once
    add_input(session, MON + timedelta(days=1), 15)
    add_session(session, WED, 8, completed=False)  # incomplete: not a practice day
    add_session(session, PREV_MON, 8)  # last week: not counted
    add_input(session, SUN_BEFORE, 10)
    s = summary(session, MON + timedelta(days=4))
    assert s.days_practiced == 2


def test_f2_input_minutes(session):
    add_input(session, MON, 20)
    add_input(session, WED, 25)
    add_input(session, SUN_BEFORE, 60)
    s = summary(session, WED)
    assert s.input_minutes == 45
    assert isinstance(s.input_minutes, int)


def test_f2_reviews_and_new_cards(session):
    add_review(session, day_at(MON), state_before=NEW, key="a")
    add_review(session, day_at(MON + timedelta(days=1)), state_before=LEARNING, key="a")
    add_review(session, day_at(MON + timedelta(days=1)), state_before=NEW, key="b")
    add_review(session, day_at(PREV_MON), state_before=NEW, key="c")  # introduced last week
    add_review(session, day_at(MON + timedelta(days=1)), state_before=REVIEW, key="c")
    s = summary(session, WED)
    assert s.reviews == 4
    assert s.new_cards == 2
    assert s.prev_reviews == 1


def test_f2_retention_excludes_new(session):
    # Non-new: 2 of 3 not Again (Hard counts as remembered). New reviews must not count.
    add_review(session, day_at(MON), rating=3, state_before=REVIEW, key="a")
    add_review(session, day_at(MON), rating=2, state_before=REVIEW, key="b")
    add_review(session, day_at(WED), rating=1, state_before=LEARNING, key="c")
    for i in range(5):
        add_review(session, day_at(WED), rating=3, state_before=NEW, key=f"n{i}")
    add_review(session, day_at(WED), rating=1, state_before=NEW, key="n9")
    s = summary(session, WED)
    assert s.retention == pytest.approx(2 / 3)


def test_f2_retention_none_with_only_new_reviews(session):
    add_review(session, day_at(MON), rating=3, state_before=NEW)
    assert summary(session, WED).retention is None


def test_f2_retention_this_week_only(session):
    add_review(session, day_at(PREV_MON), rating=1, state_before=REVIEW, key="a")
    add_review(session, day_at(MON), rating=3, state_before=REVIEW, key="b")
    assert summary(session, WED).retention == pytest.approx(1.0)


def test_f2_summary_is_frozen_dataclass(session):
    import dataclasses

    s = summary(session, WED)
    assert dataclasses.is_dataclass(s)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.minutes = 1


# --- dashboard panel --------------------------------------------------------------------------


def test_f2_dashboard_panel_present_and_first(client):
    html = client.get("/dashboard").text
    assert "data-weekly-summary" in html
    assert html.index("data-weekly-summary") < html.index("Streak")


def test_f2_dashboard_panel_says_not_enough_reviews(client):
    html = client.get("/dashboard").text
    el = element_with_attr(html, "data-weekly-summary")
    assert el is not None
    assert "not enough" in el[0].lower()


def test_f2_dashboard_panel_with_data(client, session):
    from app.services import stats

    now = datetime.now(timezone.utc)
    today = stats.local_date(now)
    add_session(session, today, 25)
    for i in range(8):
        add_review(session, now, rating=3, state_before=REVIEW, key=f"k{i}")
    el = element_with_attr(client.get("/dashboard").text, "data-weekly-summary")
    assert el is not None
    assert "not enough" not in el[0].lower()
    assert "25" in el[0]

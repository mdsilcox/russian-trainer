from datetime import date, datetime, timedelta, timezone

from app.models import Card, CardState, Direction, InputLog, ReviewLog, Session as StudySession
from app.services import stats

# Friday 2 October 2026 at noon local time; its week starts Monday 28 September.
NOW = datetime(2026, 10, 2, 12, 0).astimezone()
MONDAY = date(2026, 9, 28)
SUNDAY_BEFORE = date(2026, 9, 27)


def at(day: date, hour: int = 12) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0).astimezone()


def add_session(session, day, minutes=10.0, completed=True):
    session.add(StudySession(date=day, minutes=minutes, completed=completed))
    session.commit()


def add_input(session, day, minutes=20):
    session.add(InputLog(date=day, minutes=minutes, kind="reading"))
    session.commit()


def add_card(session, directions=(Direction.recognition,)):
    card = Card(ru="а", en="a")
    session.add(card)
    session.commit()
    states = []
    for direction in directions:
        cs = CardState(card_id=card.id, direction=direction)
        session.add(cs)
        session.commit()
        states.append(cs)
    return states


def add_review(session, cs, when, rating=3, state_before=2):
    utc = when.astimezone(timezone.utc)
    session.add(ReviewLog(card_state_id=cs.id, rating=rating, state_before=state_before, reviewed_at=utc, due_before=utc))
    session.commit()


# --- empty and basic ----------------------------------------------------------------------


def test_empty_week(session):
    summary = stats.weekly_summary(session, NOW)
    assert summary == stats.WeeklySummary(MONDAY, 0, 0.0, 0, 0, None, 0, 0.0, 0)


def test_week_start_is_monday_even_on_sunday_and_monday():
    sunday = datetime(2026, 10, 4, 12, 0).astimezone()
    monday = datetime(2026, 10, 5, 12, 0).astimezone()
    assert stats.local_date(sunday) == date(2026, 10, 4)
    assert stats._week_start(stats.local_date(sunday)) == MONDAY
    assert stats._week_start(stats.local_date(monday)) == date(2026, 10, 5)


# --- sessions, minutes, days ----------------------------------------------------------------


def test_minutes_and_days_use_completed_sessions_in_this_week(session):
    add_session(session, MONDAY, 12.25)
    add_session(session, MONDAY, 5.0)
    add_session(session, date(2026, 10, 2), 25.3)
    add_session(session, date(2026, 10, 1), 99.0, completed=False)  # not completed: ignored
    summary = stats.weekly_summary(session, NOW)
    assert summary.minutes == 42.5
    assert summary.days_practiced == 2  # Monday and Friday; Thursday's session is incomplete


def test_input_only_day_counts_as_practiced(session):
    add_session(session, MONDAY)
    add_input(session, date(2026, 9, 30), 25)
    add_input(session, MONDAY, 5)  # same day as a session: still one day
    summary = stats.weekly_summary(session, NOW)
    assert summary.days_practiced == 2
    assert summary.input_minutes == 30
    assert summary.minutes == 10.0  # input minutes are not session minutes


def test_previous_week_and_boundaries(session):
    add_session(session, SUNDAY_BEFORE, 30.0)  # last week
    add_session(session, MONDAY - timedelta(days=7), 10.0)  # last week's Monday
    add_session(session, MONDAY - timedelta(days=8), 50.0)  # two weeks ago: ignored
    add_session(session, MONDAY, 7.0)
    summary = stats.weekly_summary(session, NOW)
    assert summary.minutes == 7.0
    assert summary.prev_minutes == 40.0
    assert summary.days_practiced == 1
    add_input(session, SUNDAY_BEFORE, 60)
    assert stats.weekly_summary(session, NOW).input_minutes == 0


def test_sunday_belongs_to_the_week_that_ends_and_monday_starts_a_new_one(session):
    add_session(session, date(2026, 10, 4), 20.0)  # Sunday
    sunday = datetime(2026, 10, 4, 22, 0).astimezone()
    monday = datetime(2026, 10, 5, 9, 0).astimezone()
    on_sunday = stats.weekly_summary(session, sunday)
    assert (on_sunday.week_start, on_sunday.minutes, on_sunday.prev_minutes) == (MONDAY, 20.0, 0.0)
    on_monday = stats.weekly_summary(session, monday)
    assert (on_monday.week_start, on_monday.minutes, on_monday.prev_minutes) == (date(2026, 10, 5), 0.0, 20.0)
    assert on_monday.days_practiced == 0


# --- reviews ------------------------------------------------------------------------------


def test_reviews_counted_by_local_day_and_previous_week(session):
    (cs,) = add_card(session)
    add_review(session, cs, at(MONDAY, 0))  # just after local midnight on Monday: this week
    add_review(session, cs, at(date(2026, 10, 2)))
    add_review(session, cs, at(SUNDAY_BEFORE, 23))  # just before Monday: last week
    add_review(session, cs, at(SUNDAY_BEFORE - timedelta(days=3)))
    add_review(session, cs, at(MONDAY - timedelta(days=8)))  # too old
    summary = stats.weekly_summary(session, NOW)
    assert summary.reviews == 2
    assert summary.prev_reviews == 2


def test_reviews_include_first_reviews_of_new_cards(session):
    (cs,) = add_card(session)
    add_review(session, cs, at(MONDAY), state_before=0)
    add_review(session, cs, at(date(2026, 9, 29)), state_before=1)
    assert stats.weekly_summary(session, NOW).reviews == 2


# --- new cards ----------------------------------------------------------------------------


def test_new_cards_counts_distinct_cards_not_directions(session):
    rec, prod = add_card(session, (Direction.recognition, Direction.production))
    add_review(session, rec, at(MONDAY), state_before=0)
    add_review(session, prod, at(date(2026, 9, 29)), state_before=0)
    add_review(session, rec, at(date(2026, 9, 30)))
    summary = stats.weekly_summary(session, NOW)
    assert summary.new_cards == 1
    assert summary.reviews == 3


def test_new_cards_excludes_cards_first_seen_last_week(session):
    rec, prod = add_card(session, (Direction.recognition, Direction.production))
    add_review(session, rec, at(SUNDAY_BEFORE), state_before=0)
    # The production direction's first review is this week, but the card is not new.
    add_review(session, prod, at(MONDAY), state_before=0)
    summary = stats.weekly_summary(session, NOW)
    assert summary.new_cards == 0
    assert summary.reviews == 1
    assert summary.prev_reviews == 1


def test_new_cards_counts_each_new_card_once(session):
    (a,) = add_card(session)
    (b,) = add_card(session)
    (c,) = add_card(session)
    add_review(session, a, at(MONDAY), state_before=0)
    add_review(session, b, at(date(2026, 10, 1)), state_before=0)
    add_review(session, c, at(SUNDAY_BEFORE), state_before=0)
    assert stats.weekly_summary(session, NOW).new_cards == 2


# --- retention ----------------------------------------------------------------------------


def test_retention_none_without_non_new_reviews(session):
    assert stats.weekly_summary(session, NOW).retention is None
    (cs,) = add_card(session)
    add_review(session, cs, at(MONDAY), rating=3, state_before=0)  # first reviews don't measure memory
    assert stats.weekly_summary(session, NOW).retention is None


def test_retention_share_of_this_weeks_non_new_reviews(session):
    (cs,) = add_card(session)
    add_review(session, cs, at(MONDAY), rating=3)
    add_review(session, cs, at(MONDAY), rating=2)
    add_review(session, cs, at(date(2026, 9, 30)), rating=4)
    add_review(session, cs, at(date(2026, 10, 1)), rating=1)
    add_review(session, cs, at(SUNDAY_BEFORE), rating=1)  # last week: ignored
    add_review(session, cs, at(date(2026, 10, 2)), rating=1, state_before=0)  # new: ignored
    assert stats.weekly_summary(session, NOW).retention == 0.75


# --- dashboard panel ----------------------------------------------------------------------


def _panel(html: str) -> str:
    start = html.index("data-weekly-summary")
    return html[start : html.index("</section>", start)]


def _text(fragment: str) -> str:
    import re

    return " ".join(re.sub(r"<[^>]+>", " ", fragment).split())


def test_dashboard_panel_is_first_and_empty_state(client):
    html = client.get("/dashboard").text
    assert "data-weekly-summary" in html
    assert html.index("data-weekly-summary") < html.index("Streak")
    text = _text(_panel(html))
    assert "This week so far" in text
    assert "since Monday" in text
    assert "Practiced on 0 days" in text
    assert "0 minutes of practice, same as last week" in text
    assert "0 reviews, same as last week" in text
    assert "0 new cards" in text
    assert "Not enough reviews yet to measure how much you remember" in text
    assert "0 minutes of reading, listening and watching" in text
    assert "—" not in text


def test_dashboard_panel_shows_numbers(client, session):
    today = stats.local_date()
    monday = stats._week_start(today)
    last_week = monday - timedelta(days=1)
    add_session(session, monday, 42.5)
    add_session(session, last_week, 30.5)
    add_input(session, monday, 25)
    (cs,) = add_card(session)
    # Reviews at local midnight Monday: always this week and never in the future.
    for rating in (3, 3, 3, 1):
        add_review(session, cs, at(monday, 0), rating=rating)
    add_review(session, cs, at(last_week, 12))
    text = _text(_panel(client.get("/dashboard").text))
    assert f"since Monday {monday.day} {monday.strftime('%B')}" in text
    assert "Practiced on 1 day" in text and "1 days" not in text
    assert "42.5 minutes of practice, 12 more than last week" in text
    assert "4 reviews, 3 more than last week" in text
    assert "Remembered 75% of reviews" in text
    assert "25 minutes of reading, listening and watching" in text


def test_dashboard_panel_singular_and_fewer(client, session):
    today = stats.local_date()
    monday = stats._week_start(today)
    add_session(session, monday, 1.0)
    add_session(session, monday - timedelta(days=1), 9.5)
    add_input(session, monday, 1)
    (cs,) = add_card(session)
    add_review(session, cs, at(monday, 0), state_before=0)
    text = _text(_panel(client.get("/dashboard").text))
    assert "1 minute of practice, 8.5 fewer than last week" in text
    assert "1 review, 1 more than last week" in text
    assert "1 new card" in text and "1 new cards" not in text
    assert "1 minute of reading, listening and watching" in text

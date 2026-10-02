from datetime import date, datetime, timedelta, timezone

from app.models import ApiUsage, Card, CardState, Category, Mistake, Module, ReviewLog, Session as StudySession, Setting
from app.services import stats

# Noon on a local calendar day, so results don't depend on the machine's timezone.
NOW = datetime(2026, 10, 2, 12, 0).astimezone()
TODAY = date(2026, 10, 2)


def day(offset: int) -> date:
    return TODAY + timedelta(days=offset)


def set_setting(session, key, value):
    session.merge(Setting(key=key, value=value))
    session.commit()


def add_sessions(session, offsets, completed=True):
    for offset in offsets:
        session.add(StudySession(date=day(offset), completed=completed))
    session.commit()


def add_state(session, state=2, due=NOW, suspended=False):
    card = Card(ru="а", en="a", suspended=suspended)
    session.add(card)
    session.commit()
    cs = CardState(card_id=card.id, state=state, due=due.astimezone(timezone.utc))
    session.add(cs)
    session.commit()
    return cs


def add_log(session, cs, rating, state_before=2, when=NOW):
    session.add(
        ReviewLog(
            card_state_id=cs.id, rating=rating, state_before=state_before,
            reviewed_at=when.astimezone(timezone.utc), due_before=when.astimezone(timezone.utc),
        )
    )
    session.commit()


def add_mistake(session, category, when=NOW):
    session.add(
        Mistake(module=Module.story, category=category, wrong="x", right="y", created_at=when.astimezone(timezone.utc))
    )
    session.commit()


def test_local_date_uses_local_clock():
    assert stats.local_date(NOW) == TODAY


# --- streaks -----------------------------------------------------------------


def test_streak_empty(session):
    assert stats.streaks(session, NOW) == stats.Streak(0, 0)


def test_streak_including_today(session):
    add_sessions(session, [0, -1, -2])
    assert stats.streaks(session, NOW) == stats.Streak(3, 3)


def test_streak_not_broken_until_day_ends(session):
    add_sessions(session, [-1, -2])
    assert stats.streaks(session, NOW) == stats.Streak(2, 2)


def test_streak_broken_after_missed_day(session):
    add_sessions(session, [-2, -3])
    assert stats.streaks(session, NOW) == stats.Streak(0, 2)


def test_streak_gap_and_longest(session):
    add_sessions(session, [0, -1, -3, -4, -5, -6])
    assert stats.streaks(session, NOW) == stats.Streak(2, 4)


def test_streak_ignores_incomplete_and_duplicates(session):
    add_sessions(session, [0, 0, -1])
    add_sessions(session, [-2], completed=False)
    assert stats.streaks(session, NOW) == stats.Streak(2, 2)


def test_streak_day_boundary(session):
    add_sessions(session, [0])
    just_after_midnight = datetime(2026, 10, 3, 0, 5).astimezone()
    assert stats.streaks(session, just_after_midnight) == stats.Streak(1, 1)
    two_days_later = datetime(2026, 10, 4, 0, 5).astimezone()
    assert stats.streaks(session, two_days_later).current == 0


def test_streak_ignores_future_sessions_for_current(session):
    add_sessions(session, [1, 2])
    assert stats.streaks(session, NOW) == stats.Streak(0, 2)


# --- forecast ----------------------------------------------------------------


def test_forecast_labels():
    labels = stats.forecast_labels(NOW)  # Fri 2 Oct 2026
    assert labels == ["Today", "Sat", "Sun", "Mon", "Tue", "Wed", "Thu"]


def test_review_forecast_counts_and_overdue(session):
    add_state(session, due=NOW - timedelta(days=3))
    add_state(session, due=NOW + timedelta(days=1))
    add_state(session, due=NOW + timedelta(days=1))
    add_state(session, due=NOW + timedelta(days=20))
    add_state(session, state=0, due=NOW)  # new cards aren't reviews
    add_state(session, due=NOW, suspended=True)
    result = stats.review_forecast(session, NOW)
    assert [n for _, n in result] == [1, 2, 0, 0, 0, 0, 0]
    assert result[0][0] == "Today"


def test_reviews_due_today(session):
    add_state(session, due=NOW - timedelta(hours=2))
    add_state(session, due=NOW + timedelta(hours=2))
    assert stats.reviews_due_today(session, NOW) == 1


# --- retention ---------------------------------------------------------------


def test_retention_no_data(session):
    assert stats.retention(session, NOW) is None


def test_retention_only_non_new_and_not_again(session):
    cs = add_state(session)
    add_log(session, cs, 3)
    add_log(session, cs, 2)
    add_log(session, cs, 4)
    add_log(session, cs, 1)
    add_log(session, cs, 1, state_before=0)  # first sight of a card doesn't count
    assert stats.retention(session, NOW) == 0.75


def test_retention_window(session):
    cs = add_state(session)
    add_log(session, cs, 1, when=NOW - timedelta(days=31))
    assert stats.retention(session, NOW) is None
    add_log(session, cs, 3, when=NOW - timedelta(days=29))
    assert stats.retention(session, NOW) == 1.0


# --- countdown ---------------------------------------------------------------


def test_days_until_trip(session):
    set_setting(session, "trip_date", "2027-09-30")
    session.commit()
    assert stats.days_until_trip(session, NOW) == (date(2027, 9, 30) - TODAY).days


def test_days_until_trip_uses_local_date(session):
    set_setting(session, "trip_date", "2026-10-03")
    session.commit()
    assert stats.days_until_trip(session, NOW) == 1
    assert stats.days_until_trip(session, datetime(2026, 10, 3, 0, 5).astimezone()) == 0
    assert stats.days_until_trip(session, datetime(2026, 10, 4, 9, 0).astimezone()) == -1


def test_days_until_trip_missing_or_bad(session):
    session.delete(session.get(Setting, "trip_date"))
    session.commit()
    assert stats.days_until_trip(session, NOW) is None
    set_setting(session, "trip_date", "soon")
    session.commit()
    assert stats.days_until_trip(session, NOW) is None


# --- mistakes ----------------------------------------------------------------


def test_top_mistakes_empty(session):
    assert stats.top_mistakes(session, NOW) == []


def test_top_mistakes_ranking_and_labels(session):
    old = NOW - timedelta(days=60)
    for _ in range(3):
        add_mistake(session, Category.case)
    add_mistake(session, Category.motion_verb)
    add_mistake(session, Category.motion_verb)
    for _ in range(10):
        add_mistake(session, Category.stress, when=old)
    rows = stats.top_mistakes(session, NOW)
    assert [(r.label, r.recent, r.total) for r in rows] == [
        ("Cases", 3, 3),
        ("Verbs of motion", 2, 2),
        ("Stress", 0, 10),
    ]


def test_top_mistakes_limit(session):
    for category in list(Category)[:7]:
        add_mistake(session, category)
    assert len(stats.top_mistakes(session, NOW)) == 5


def test_every_category_has_a_label():
    assert set(stats.CATEGORY_LABELS) == set(Category)


# --- deck --------------------------------------------------------------------


def test_deck_counts(session):
    add_state(session, state=0)
    add_state(session, state=2)
    add_state(session, state=0, suspended=True)
    assert stats.deck_counts(session) == stats.DeckCounts(cards=2, new_waiting=1)


# --- route -------------------------------------------------------------------


def test_dashboard_empty(client):
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "Streak" in response.text
    assert "No mistakes logged yet" in response.text


def test_dashboard_with_data(client, session):
    cs = add_state(session, due=datetime.now(timezone.utc) - timedelta(hours=1))
    add_log(session, cs, 3, when=datetime.now(timezone.utc))
    add_mistake(session, Category.motion_verb, when=datetime.now(timezone.utc))
    set_setting(session, "trip_date", "2027-09-30")
    set_setting(session, "api_budget_usd_month", 10)
    session.add(ApiUsage(task="t", model="m", input_tokens=1, output_tokens=1, cost_usd=9.0))
    session.commit()
    text = client.get("/dashboard").text
    assert "Verbs of motion" in text
    assert "approaching your limit" in text
    assert "100%" in text  # retention

"""Feature 5: "This week" panel on Today."""

import dataclasses
from datetime import timedelta

from tl_h import D, after, noon, real_today


def test_f5_this_week_without_lessons(session):
    from app.services import lessons

    w = lessons.this_week(session, noon(D))
    assert dataclasses.is_dataclass(w)
    assert w.topic is None and list(w.goals) == []
    assert w.next_lesson_date is None and w.days_until_next is None


def test_f5_this_week_current_and_next(session):
    from app.services import lessons

    lessons.create_lesson(session, D - timedelta(days=14), "older", goals=["old goal"])
    lessons.create_lesson(session, D - timedelta(days=4), "current", goals=["goal a", "goal b"])
    lessons.create_lesson(session, D + timedelta(days=3), "upcoming")
    lessons.create_lesson(session, D + timedelta(days=10), "far")
    w = lessons.this_week(session, noon(D))
    assert w.topic == "current" and list(w.goals) == ["goal a", "goal b"]
    assert w.next_lesson_date == D + timedelta(days=3) and w.days_until_next == 3


def test_f5_lesson_today_is_current_and_next(session):
    from app.services import lessons

    lessons.create_lesson(session, D - timedelta(days=7), "last week", goals=["x"])
    lessons.create_lesson(session, D, "today's lesson", goals=["today goal"])
    w = lessons.this_week(session, noon(D))
    assert w.topic == "today's lesson" and list(w.goals) == ["today goal"]
    assert w.next_lesson_date == D and w.days_until_next == 0


def test_f5_this_week_only_future(session):
    from app.services import lessons

    lessons.create_lesson(session, D + timedelta(days=1), "future")
    w = lessons.this_week(session, noon(D))
    assert w.topic is None and list(w.goals) == []
    assert w.next_lesson_date == D + timedelta(days=1) and w.days_until_next == 1


def test_f5_this_week_only_past(session):
    from app.services import lessons

    lessons.create_lesson(session, D - timedelta(days=2), "past", goals=["g"])
    w = lessons.this_week(session, noon(D))
    assert w.topic == "past" and list(w.goals) == ["g"]
    assert w.next_lesson_date is None and w.days_until_next is None


def test_f5_panel_invites_first_lesson(client):
    r = client.get("/")
    assert r.status_code == 200
    panel = after(r.text, "data-this-week")
    assert panel, "no data-this-week panel"
    assert 'href="/lessons"' in panel
    assert "lesson" in panel.lower()


def test_f5_panel_shows_topic_goals_and_next_today(client, session):
    from app.services import lessons

    today = real_today()
    lessons.create_lesson(session, today, "Instrumental case", goals=["Use with prepositions", "Ten new words"])
    panel = after(client.get("/").text, "data-this-week")
    assert "Instrumental case" in panel and "Use with prepositions" in panel and "Ten new words" in panel
    assert "today" in panel.lower()


def test_f5_panel_next_lesson_tomorrow(client, session):
    from app.services import lessons

    today = real_today()
    lessons.create_lesson(session, today - timedelta(days=3), "Accusative", goals=["g1"])
    lessons.create_lesson(session, today + timedelta(days=1), "Future talk")
    panel = after(client.get("/").text, "data-this-week")
    assert "Accusative" in panel and "g1" in panel
    assert "tomorrow" in panel.lower()


def test_f5_panel_next_lesson_in_n_days(client, session):
    from app.services import lessons

    today = real_today()
    lessons.create_lesson(session, today - timedelta(days=1), "Numbers")
    lessons.create_lesson(session, today + timedelta(days=5), "Later")
    panel = after(client.get("/").text, "data-this-week")
    assert "in 5 days" in panel.lower()

"""Feature 3: the timeline service and the /activity page."""

import dataclasses
import re
from datetime import datetime, timedelta, timezone

from tc_helpers import (NOON, TODAY, add_attempt, add_input, add_review, add_session, add_story, at_local,
                     new_card_state)

KINDS_ORDER = ["session", "review", "drill_answer", "story_attempt", "roleplay_turn", "input"]


def d(n):
    return TODAY - timedelta(days=n)


def rec(db, kind, ref, day, minutes=0.0, detail=None):
    from app.services import activity

    activity.record(db, kind, ref, at_local(day), day, minutes, detail)
    db.commit()


def done(minutes):
    return {"completed": True, "reviews": 0, "new_cards": 0}


def test_f3_timeline_grouping_and_order(session):
    from app.services import activity

    rec(session, "session", 1, d(0), 10.0, done(10))
    rec(session, "session", 2, d(0), 15.0, done(15))
    rec(session, "session", 3, d(0), 99.0, {"completed": False, "reviews": 0, "new_cards": 0})
    for i in range(3):
        rec(session, "review", 10 + i, d(0), 0, {"rating": 3, "state_before": 2})
    rec(session, "drill_answer", 20, d(0), 0, {"correct": True})
    rec(session, "story_attempt", 30, d(0), 0, {"story_id": 1})
    for i in range(2):
        rec(session, "roleplay_turn", 40 + i, d(0), 0, {"conversation_id": 1})
    rec(session, "input", 50, d(0), 20.0, {"kind": "reading"})
    rec(session, "input", 51, d(0), 10.0, {"kind": "watching"})
    for i in range(40):
        rec(session, "review", 100 + i, d(2), 0, {"rating": 3, "state_before": 2})
    rec(session, "drill_answer", 21, d(13), 0, {"correct": False})
    rec(session, "drill_answer", 22, d(14), 0, {"correct": False})  # outside the 14 days

    tl = activity.timeline(session, NOON)
    assert [t.day for t in tl] == [d(0), d(2), d(13)]
    top = tl[0]
    assert [line.kind for line in top.lines] == KINDS_ORDER
    assert [line.label for line in top.lines] == [
        "2 sessions, 25 min", "3 reviews", "1 drill answer", "1 translation", "2 role-play turns",
        "30 min of reading, listening or watching",
    ]
    by_kind = {line.kind: line for line in top.lines}
    assert [by_kind[k].count for k in KINDS_ORDER[:5]] == [2, 3, 1, 1, 2]
    assert by_kind["session"].minutes == 25.0 and by_kind["input"].minutes == 30.0
    assert [(line.kind, line.label) for line in tl[1].lines] == [("review", "40 reviews")]
    assert tl[1].lines[0].count == 40
    assert tl[2].lines[0].label == "1 drill answer"


def test_f3_timeline_labels(session):
    from app.services import activity

    rec(session, "session", 1, d(0), 25.0, done(25))
    rec(session, "session", 2, d(1), 12.5, done(12))
    rec(session, "session", 3, d(2), 7.5, done(7))
    rec(session, "session", 4, d(2), 10.0, done(10))
    rec(session, "review", 5, d(3))
    rec(session, "roleplay_turn", 6, d(4))
    for i in range(2):
        rec(session, "story_attempt", 7 + i, d(5))
    for i in range(2):
        rec(session, "drill_answer", 9 + i, d(6))
    rec(session, "input", 11, d(7), 1.0, {"kind": "reading"})
    rec(session, "input", 12, d(8), 90.0, {"kind": "reading"})
    labels = {t.day: [line.label for line in t.lines] for t in activity.timeline(session, NOON)}
    assert labels[d(0)] == ["1 session, 25 min"]
    assert labels[d(1)] == ["1 session, 12.5 min"]
    assert labels[d(2)] == ["2 sessions, 17.5 min"]
    assert labels[d(3)] == ["1 review"]
    assert labels[d(4)] == ["1 role-play turn"]
    assert labels[d(5)] == ["2 translations"]
    assert labels[d(6)] == ["2 drill answers"]
    assert labels[d(7)] == ["1 min of reading, listening or watching"]
    assert labels[d(8)] == ["90 min of reading, listening or watching"]


def test_f3_timeline_only_completed_sessions(session):
    from app.services import activity

    rec(session, "session", 1, d(1), 40.0, {"completed": False, "reviews": 0, "new_cards": 0})
    rec(session, "session", 2, d(2), 20.0, done(20))
    rec(session, "session", 3, d(2), 50.0, {"completed": False, "reviews": 0, "new_cards": 0})
    tl = activity.timeline(session, NOON)
    assert [t.day for t in tl] == [d(2)]
    assert [line.label for line in tl[0].lines] == ["1 session, 20 min"]


def test_f3_timeline_window_and_empty(session):
    from app.services import activity

    assert activity.timeline(session, NOON) == []
    for n in (0, 1, 2, 3, 13, 14):
        rec(session, "review", 200 + n, d(n), 0, {"rating": 3, "state_before": 2})
    assert [t.day for t in activity.timeline(session, NOON)] == [d(0), d(1), d(2), d(3), d(13)]
    assert [t.day for t in activity.timeline(session, NOON, days=3)] == [d(0), d(1), d(2)]
    assert [t.day for t in activity.timeline(session, NOON, days=1)] == [d(0)]
    assert [t.day for t in activity.timeline(session, NOON, days=15)][-1] == d(14)
    # relative to `now`: later days are not shown
    assert [t.day for t in activity.timeline(session, at_local(d(2)), days=3)] == [d(2), d(3)]


def test_f3_timeline_groups_by_day_field(session):
    from app.services import activity

    from_late_night = at_local(d(5), 23, 50)
    activity.record(session, "session", 1, from_late_night, d(5), 30.0, done(30))
    activity.record(session, "review", 2, at_local(d(3)), d(4), 0.0, {"rating": 3, "state_before": 2})
    session.commit()
    tl = activity.timeline(session, NOON)
    assert [t.day for t in tl] == [d(4), d(5)]
    assert tl[1].lines[0].label == "1 session, 30 min"


def test_f3_timeline_from_real_rows(session):
    """Timeline over rows written by the ORM, not by record()."""
    from app.services import activity

    cs = new_card_state(session)
    add_session(session, d(0), 25.0, True)
    add_session(session, d(0), 5.0, False)
    for i in range(3):
        add_review(session, cs, d(1), hour=9 + i)
    add_attempt(session, add_story(session), d(1))
    add_input(session, d(2), 45, "watching")
    tl = activity.timeline(session, NOON)
    assert [(t.day, [line.label for line in t.lines]) for t in tl] == [
        (d(0), ["1 session, 25 min"]),
        (d(1), ["3 reviews", "1 translation"]),
        (d(2), ["45 min of reading, listening or watching"]),
    ]


def test_f3_timeline_dataclasses():
    from app.services import activity

    line = activity.TimelineLine(kind="review", count=2, minutes=0.0, label="2 reviews")
    day = activity.TimelineDay(day=TODAY, lines=[line])
    assert dataclasses.is_dataclass(line) and dataclasses.is_dataclass(day)
    assert [f.name for f in dataclasses.fields(line)] == ["kind", "count", "minutes", "label"]
    assert [f.name for f in dataclasses.fields(day)] == ["day", "lines"]
    assert day.lines[0].label == "2 reviews"


def _real_today():
    from app.services import stats

    return stats.local_date(datetime.now(timezone.utc))


def test_f3_activity_page_blocks(client, session):
    today = _real_today()
    cs = new_card_state(session)
    add_session(session, today, 25.0, True)
    for i in range(3):
        add_review(session, cs, today - timedelta(days=1), hour=9 + i)
    add_input(session, today - timedelta(days=2), 30, "reading")
    response = client.get("/activity")
    assert response.status_code == 200
    html = response.text
    days = re.findall(r'data-activity-day="(\d{4}-\d{2}-\d{2})"', html)
    assert days == [(today - timedelta(days=n)).isoformat() for n in (0, 1, 2)]
    assert "1 session, 25 min" in html and "3 reviews" in html
    assert "30 min of reading, listening or watching" in html
    assert (today - timedelta(days=3)).isoformat() not in html


def test_f3_activity_page_empty_state(client):
    response = client.get("/activity")
    assert response.status_code == 200
    assert "data-activity-day" not in response.text
    assert len(response.text) > 500


def test_f3_navigation_links_to_activity(client):
    for path in ("/dashboard", "/"):
        response = client.get(path)
        assert response.status_code == 200
        assert 'href="/activity"' in response.text, path

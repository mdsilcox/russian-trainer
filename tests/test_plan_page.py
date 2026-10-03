from datetime import datetime, timezone

import pytest

from app.models import Card, Setting
from app.models import Session as StudySession
from app.services import plan

MID = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)  # early in month 1
LATE = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)  # last 3 days of month 1


def set_trip(db, trip="2027-09-30"):
    row = db.get(Setting, "trip_date") or Setting(key="trip_date", value=None)
    row.value = trip
    db.add(row)
    db.commit()


@pytest.fixture
def planned(session, client, monkeypatch):
    set_trip(session)
    plan.seed(session, MID)
    clock = {"now": MID}
    monkeypatch.setattr("app.routes.plan._now", lambda: clock["now"])
    client.clock = clock
    return client


def test_page_renders_timeline_current_month_goals_and_topics(planned):
    html = planned.get("/plan").text
    assert html.count('class="pl-station') == 12
    assert "Cases in everyday speech" in html and "this month" in html
    assert "pl-bar" not in html  # activity-goal bars are gone; units replace them
    assert 'href="/grammar/cases#prepositional"' in html
    assert "Drills favor these topics this month" in html
    assert "days to go" in html and "\u2014" not in html
    assert '<a href="/plan"' in planned.get("/").text


def test_months_list_their_units_and_pace(planned, session):
    from app.services import units

    units.seed_curriculum(session)
    html = planned.get("/plan").text
    assert 'href="/learn/u01-where-you-are"' in html and "Not started" in html
    assert "0 of 4 units passed" in html and "Units coming for this month" in html
    u = session.get(units.Unit, "u01-where-you-are")
    units.finish_step(session, u, "quiz", 0.9, now=MID)
    html = planned.get("/plan").text
    assert "1 of 4 units passed" in html and "Passed" in html


def test_empty_state_without_trip_date(client):
    html = client.get("/plan").text
    assert "No plan yet" in html and 'href="/settings"' in html
    assert "pl-station" not in html


def test_check_in_appears_only_when_due_and_saves(planned, session):
    assert "How did" not in planned.get("/plan").text
    planned.clock["now"] = LATE
    page = planned.get("/plan").text
    assert "How did Cases in everyday speech go?" in page
    assert page.count('type="radio"') == 5 and "<textarea" in page
    r = planned.post("/plan/checkin", data={"month_idx": 1, "rating": 4, "notes": "Solid"})
    assert "Check-in saved" in r.text and 'id="review-1"' in r.text
    session.expire_all()
    review = plan.months(session)[0].review_json
    assert review["rating"] == 4 and review["notes"] == "Solid"
    after = planned.get("/plan").text
    assert "How did" not in after and "Check-in 4/5" in after


@pytest.mark.parametrize("data", [
    {"month_idx": 1, "rating": 9, "notes": ""},
    {"month_idx": 1, "rating": "", "notes": "x"},
    {"month_idx": 1, "rating": "abc", "notes": ""},
    {"month_idx": 3, "rating": 3, "notes": ""},
    {"month_idx": 1, "rating": 3, "notes": "x" * 2001},
])
def test_check_in_rejects_invalid_input(planned, session, data):
    planned.clock["now"] = LATE
    r = planned.post("/plan/checkin", data=data)
    assert 'role="alert"' in r.text
    session.expire_all()
    assert plan.months(session)[0].review_json is None


def test_check_in_refused_when_not_due(planned):
    r = planned.post("/plan/checkin", data={"month_idx": 1, "rating": 4, "notes": ""})
    assert "no check-in open" in r.text


def test_rhythm_prefilled_save_and_reset(planned, session):
    page = planned.get("/plan").text
    assert "Today leads with" in page
    assert page.count("<select") == 7 and 'value="grammar" selected' in page
    kinds = ["light"] * 7
    r = planned.post("/plan/rhythm", data={"kind": kinds})
    assert "Saved." in r.text and plan.rhythm(session) == kinds
    r = planned.post("/plan/rhythm/reset")
    assert "Saved." in r.text and plan.rhythm(session) == plan.DEFAULT_RHYTHM


def test_rhythm_rejects_invalid_input(planned, session):
    r = planned.post("/plan/rhythm", data={"kind": ["grammar"] * 6 + ["nonsense"]})
    assert 'role="alert"' in r.text
    r = planned.post("/plan/rhythm", data={"kind": ["grammar"] * 3})
    assert 'role="alert"' in r.text
    assert plan.rhythm(session) == plan.DEFAULT_RHYTHM

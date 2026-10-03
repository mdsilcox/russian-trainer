from datetime import date, datetime, timedelta, timezone

import pytest

from app.models import Card, Category, Conversation, InputLog, Mistake, Module, Scenario, Setting
from app.models import Session as StudySession
from app.services import plan, weakness

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)  # a Wednesday in October 2026


def with_trip(db, trip="2027-09-30"):
    row = db.get(Setting, "trip_date") or Setting(key="trip_date", value=None)
    row.value = trip
    db.add(row)
    db.commit()


def test_seed_back_plans_twelve_months_ending_in_the_trip_month(session):
    with_trip(session)
    months = plan.seed(session, NOW)
    assert [m.start_date for m in (months[0], months[-1])] == [date(2026, 10, 1), date(2027, 9, 1)]
    assert len(months) == 12 and all(m.title and m.focus and m.goals_json for m in months)
    assert [m.status for m in months[:2]] == ["current", "planned"]
    assert plan.current_month(session, NOW).title == "Cases in everyday speech"
    assert all("—" not in m.focus and "—" not in m.title for m in months)


def test_seed_is_idempotent_keeps_check_ins_and_reanchors(session):
    with_trip(session)
    first = plan.seed(session, NOW)[0]
    plan.save_review(session, first, 4, "Good month", NOW)
    again = plan.seed(session, NOW)
    assert len(again) == 12 and again[0].review_json["rating"] == 4
    with_trip(session, "2027-12-15")  # moving the trip re-anchors every month
    moved = plan.seed(session, NOW)
    assert moved[0].start_date == date(2027, 1, 1) and moved[0].review_json is None
    assert plan.current_month(session, NOW) is None


def test_no_trip_date_means_no_plan(session):
    row = session.get(Setting, "trip_date")
    if row:
        session.delete(row)
        session.commit()
    assert plan.seed(session, NOW) == [] and plan.current_month(session, NOW) is None


def test_progress_counts_only_this_month(session):
    with_trip(session)
    october = plan.seed(session, NOW)[0]
    session.add(Card(ru="а", en="a", created_at=NOW))
    session.add(Card(ru="б", en="b", created_at=datetime(2026, 9, 20, tzinfo=timezone.utc)))
    session.add(InputLog(date=date(2026, 10, 3), minutes=30, kind="watching"))
    session.add(InputLog(date=date(2026, 11, 3), minutes=99, kind="watching"))
    for d in (date(2026, 10, 2), date(2026, 10, 2), date(2026, 10, 5)):
        session.add(StudySession(date=d, started_at=NOW, completed=True))
    s = Scenario(slug="t", title="T", setting="s", partner_role="r")
    session.add(s)
    session.flush()
    session.add(Conversation(scenario_id=s.id, ended_at=NOW))
    session.commit()
    start, end = plan.month_range(october)
    assert plan.metric_value(session, "cards_added", start, end) == 1
    assert plan.metric_value(session, "input_minutes", start, end) == 30
    assert plan.metric_value(session, "study_days", start, end) == 2
    assert plan.metric_value(session, "roleplays", start, end) == 1
    goals = {g.metric: g for g in plan.progress(session, october)}
    assert goals["cards_added"].value == 1 and goals["cards_added"].target == 120 and not goals["cards_added"].done
    assert 0.4 < plan.expected_ratio(october, NOW) < 0.5


def test_rhythm_defaults_setting_and_validation(session):
    assert plan.rhythm(session) == plan.DEFAULT_RHYTHM
    focus = plan.day_focus(session, NOW)
    assert (focus.weekday, focus.kind) == ("Wednesday", "interleaved")
    custom = ["roleplay"] * 7
    plan.set_rhythm(session, custom)
    assert plan.day_focus(session, NOW).kind == "roleplay"
    with pytest.raises(ValueError):
        plan.set_rhythm(session, ["nap"] * 7)
    session.get(Setting, "weekly_rhythm").value = ["grammar"]  # a broken setting falls back
    session.commit()
    assert plan.rhythm(session) == plan.DEFAULT_RHYTHM


def test_day_focus_mentions_the_month_on_drill_days(session):
    with_trip(session)
    plan.seed(session, NOW)
    monday = NOW - timedelta(days=2)
    focus = plan.day_focus(session, monday)
    assert focus.kind == "grammar" and "cases in everyday speech" in focus.why
    assert f"{plan.CASES}#prepositional" in focus.topics


def test_month_topics_boost_weakness_scores(session):
    with_trip(session)
    plan.seed(session, NOW)
    scores = {t.topic: t for t in weakness.topic_scores(session, NOW)}
    acc = scores[f"{plan.CASES}#accusative"]  # October topic, high-yield, no mistakes
    assert acc.month_focus and acc.score == pytest.approx(weakness.HIGH_YIELD_PRIOR * plan.MONTH_BOOST + plan.MONTH_PRIOR)
    session.add(Mistake(module=Module.story, category=Category.aspect, subcategory="perfective", wrong="x", right="y", created_at=NOW))
    session.commit()
    ranked = [t.topic for t in weakness.topic_scores(session, NOW)]
    assert ranked.index(f"{plan.CASES}#prepositional") < ranked.index(f"{plan.CASES}#genitive")  # month topics outrank other high-yield ones


def test_review_window_and_rating_validation(session):
    with_trip(session)
    october = plan.seed(session, NOW)[0]
    assert plan.review_due(session, NOW) is None
    assert plan.review_due(session, datetime(2026, 10, 30, 12, tzinfo=timezone.utc)).month_idx == 1
    assert plan.review_due(session, datetime(2026, 11, 5, 12, tzinfo=timezone.utc)).month_idx == 1
    with pytest.raises(ValueError):
        plan.save_review(session, october, 6, "")
    plan.save_review(session, october, 3, " ok ", NOW)
    assert october.review_json["notes"] == "ok"
    assert plan.review_due(session, datetime(2026, 11, 5, 12, tzinfo=timezone.utc)) is None

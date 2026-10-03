"""Feature 2: the four readers give exactly the legacy numbers, from the activity table."""

from datetime import timedelta

import pytest

from tc_compare import act, assert_equivalent, fresh_db, readers
from tc_helpers import (NOON, TODAY, add_attempt, add_input, add_review, add_session, add_story, all_kinds_world,
                     at_local, delete_sources, new_card_state, random_world)


def d(n):
    return TODAY - timedelta(days=n)


def test_f2_streaks_equivalence(tmp_path):
    scenarios = {
        "run_through_today": [(0, True), (1, True), (2, True), (4, True), (5, True)],
        "today_not_yet": [(1, True), (2, True), (3, True), (6, True)],
        "incomplete_breaks_run": [(0, True), (1, False), (2, True), (3, True)],
        "old_only": [(10, True), (11, True), (12, True)],
        "two_on_one_day": [(0, True), (0, True), (1, True), (3, True), (4, True), (5, True), (6, True)],
        "none": [],
        "only_incomplete": [(0, False), (1, False)],
    }
    for name, rows in scenarios.items():
        engine, db = fresh_db(tmp_path, name)
        for n, completed in rows:
            add_session(db, d(n), 10.0, completed)
        got = assert_equivalent(db, NOON)
        if name == "run_through_today":
            assert got["streaks"] == (3, 3)
        db.close()
        engine.dispose()


def test_f2_streaks_random(tmp_path):
    for seed in (1, 2, 3, 4, 5, 6):
        engine, db = fresh_db(tmp_path, f"s{seed}")
        random_world(db, seed)
        assert_equivalent(db, NOON)
        db.close()
        engine.dispose()


def test_f2_heatmap_equivalence(session):
    from app.services import stats

    first = stats._week_start(TODAY) - timedelta(weeks=25)
    add_session(session, d(0), 20.0, True)
    add_session(session, d(0), 10.0, False)  # incomplete: minutes still count
    add_input(session, d(0), 15)
    add_session(session, d(10), 30.0, False)
    add_session(session, d(11), 0.0, True)
    add_session(session, first, 12.5, True)  # first day of the window
    add_session(session, first - timedelta(days=1), 99.0, True)  # just outside
    add_input(session, first - timedelta(days=1), 99)
    add_session(session, TODAY + timedelta(days=2), 50.0, True)  # in the future
    add_input(session, d(40), 45, "watching")
    add_input(session, d(40), 5, "reading")
    got = assert_equivalent(session, NOON, weeks=(26, 4, 1))
    today_cell = next(c for c in got["heatmaps"][26]["cells"] if c and c[0] == TODAY)
    assert today_cell[1] == 30.0 and today_cell[2] == 15


def test_f2_heatmap_random(tmp_path):
    for seed in (11, 12, 13, 14):
        engine, db = fresh_db(tmp_path, f"h{seed}")
        random_world(db, seed, span=200)
        assert_equivalent(db, NOON, weeks=(26, 12, 3))
        db.close()
        engine.dispose()


def test_f2_day_summary_equivalence(tmp_path):
    from app.services import today

    engine, db = fresh_db(tmp_path, "empty")
    assert today.day_summary(db, NOON) is None
    add_session(db, d(0), 30.0, False)  # only an unfinished session today
    assert today.day_summary(db, NOON) is None
    assert_equivalent(db, NOON)
    db.close()
    engine.dispose()

    engine, db = fresh_db(tmp_path, "busy")
    add_session(db, d(0), 25.0, True, reviews=10, new_cards=3)
    add_session(db, d(0), 12.5, True, reviews=5, new_cards=1)
    add_session(db, d(0), 30.0, False, reviews=99, new_cards=99)
    add_session(db, d(1), 20.0, True, reviews=7, new_cards=7)
    add_session(db, d(3), 20.0, True)
    got = assert_equivalent(db, NOON)
    assert got["day_summary"] == (2, 37.5, 15, 4, 2)
    db.close()
    engine.dispose()


def test_f2_day_summary_random(tmp_path):
    for seed in (21, 22, 23, 24, 25):
        engine, db = fresh_db(tmp_path, f"d{seed}")
        random_world(db, seed, span=10)
        add_session(db, d(0), 17.25, True, reviews=3, new_cards=1)
        assert_equivalent(db, NOON)
        db.close()
        engine.dispose()


def test_f2_medals_equivalence(session):
    cs = new_card_state(session)
    story = add_story(session)
    add_attempt(session, story, d(3))
    add_attempt(session, story, d(2))
    for i in range(12):  # a clean day of 12
        add_review(session, cs, d(5), rating=3, hour=8 + i % 10)
    for i in range(15):  # 15 reviews with one Again: not clean
        add_review(session, cs, d(6), rating=1 if i == 3 else 3, hour=8 + i % 10)
    for n in range(8):  # eight days in a row
        add_session(session, d(n), 10.0, True)
    for n in range(20, 35):  # long total hours, partly incomplete
        add_session(session, d(n), 400.0, n % 2 == 0)
    got = assert_equivalent(session, NOON)
    assert got["medals"]["first_story"] == 2 and got["medals"]["flawless"] == 12
    assert got["medals"]["streak_7"] == 8 and got["earned"]["hours_100"] is True


def test_f2_medals_random(tmp_path):
    for seed in (31, 32, 33, 34, 35):
        engine, db = fresh_db(tmp_path, f"m{seed}")
        random_world(db, seed)
        add_attempt(db, add_story(db), d(1))
        assert_equivalent(db, NOON)
        db.close()
        engine.dispose()


def test_f2_incomplete_sessions_mixed(session):
    """Trap 2: an unfinished session carries minutes into the heatmap and hours, but not into streak or summary."""
    from app.services import medals, stats, today

    add_session(session, TODAY, 30.0, False)
    assert [r["minutes"] for r in act(session, "session")] == [30.0]
    assert today.day_summary(session, NOON) is None
    assert (stats.streaks(session, NOON).current, stats.streaks(session, NOON).longest) == (0, 0)
    hm = stats.practice_heatmap(session, NOON)
    assert hm.total_minutes == 30.0 and hm.active_days == 1
    hours = next(m for m in medals.evaluate(session, NOON) if m.defn.key == "hours_100")
    assert hours.current == pytest.approx(0.5)
    add_session(session, TODAY, 15.0, True)
    assert today.day_summary(session, NOON).minutes == 15.0
    assert stats.streaks(session, NOON).current == 1
    assert stats.practice_heatmap(session, NOON).total_minutes == 45.0
    hours = next(m for m in medals.evaluate(session, NOON) if m.defn.key == "hours_100")
    assert hours.current == pytest.approx(0.75)


def test_f2_readers_use_activity(session):
    """Trap 6: after the source rows are deleted with raw SQL, the readers still report the same numbers."""
    random_world(session, 7)
    all_kinds_world(session, TODAY)
    add_session(session, TODAY, 22.5, True, reviews=4, new_cards=2)
    add_session(session, d(1), 14.0, False)
    before = assert_equivalent(session, NOON)
    assert before["streaks"][0] >= 1 and before["day_summary"] is not None
    assert before["heatmaps"][26]["total"] > 0 and before["medals"]["first_story"] >= 1
    delete_sources(session)
    session.expire_all()
    after = readers(session, NOON)
    assert after == before


def test_f2_service_flow_equivalence(session):
    """Sessions run through the services, with reviews inside them and one session left unfinished."""
    from fsrs import Rating

    from app.services import srs, today

    cs = new_card_state(session)
    plan = [(d(2), 9, 20, 2), (d(1), 9, 45, 0), (TODAY, 10, 30, 3)]
    for day, hour, length, n_reviews in plan:
        start = at_local(day, hour)
        today.start_session(session, now=start)
        for i in range(n_reviews):
            srs.review(session, cs, Rating.Good, now=start + timedelta(minutes=2 + i))
        assert today.finish_session(session, now=start + timedelta(minutes=length)) is not None
    today.start_session(session, now=at_local(TODAY, 18))  # abandoned: never finished
    got = assert_equivalent(session, at_local(TODAY, 19))
    assert got["day_summary"][0] == 1 and got["day_summary"][2] == 3 and got["streaks"] == (3, 3)

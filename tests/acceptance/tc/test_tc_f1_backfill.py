"""Feature 1: backfill and upgrading an existing database (trap 5)."""

import os
import shutil
from datetime import timedelta

import pytest

from sqlalchemy import text
from sqlmodel import Session

from tc_compare import act, assert_equivalent, snapshot_rows
from tc_helpers import (NOON, TODAY, all_kinds_world, at_local, random_world, raw_attempt, raw_input, raw_review,
                     raw_session, raw_story)


def _raw_world(db):
    """Source rows inserted with raw SQL, bypassing the ORM. Returns the expected number of rows per kind."""
    cs = new_card_state_for(db)
    d = lambda n: TODAY - timedelta(days=n)  # noqa: E731
    with db.get_bind().begin() as conn:
        raw_session(conn, d(0), 30.0, True, reviews=5, new_cards=2)
        raw_session(conn, d(1), 20.5, True, reviews=3)
        raw_session(conn, d(2), 45.0, False)  # incomplete, but its minutes count
        raw_session(conn, d(2), 10.0, True)
        for i in range(12):
            raw_review(conn, cs, d(1), rating=3, hour=8 + i % 10)
        raw_review(conn, cs, d(3), rating=1)
        raw_input(conn, d(0), 25, "watching")
        raw_input(conn, d(4), 40, "reading")
        story = raw_story(conn)
        raw_attempt(conn, story, d(1))
        raw_attempt(conn, story, d(5))
    return {"session": 4, "review": 13, "input": 2, "story_attempt": 2}


def new_card_state_for(db):
    from tc_helpers import new_card_state

    return new_card_state(db).id


def test_f1_backfill_restores_deleted_rows(session):
    from app.services import activity

    all_kinds_world(session)
    random_world(session, 3, span=20)
    full = snapshot_rows(session)
    assert len(full) > 20
    session.exec(text("DELETE FROM activity WHERE kind IN ('session', 'review')"))
    session.commit()
    missing = len(full) - len(snapshot_rows(session))
    assert missing > 0
    assert activity.backfill(session) == missing
    assert snapshot_rows(session) == full
    session.exec(text("DELETE FROM activity"))
    session.commit()
    assert activity.backfill(session) == len(full)
    assert snapshot_rows(session) == full
    assert activity.backfill(session) == 0
    assert len([r for r in full if r[0] == "roleplay_turn"]) == 1


def test_f1_backfill_raw_rows_match_legacy(session):
    from app.services import activity

    counts = _raw_world(session)
    activity.backfill(session)
    session.expire_all()
    for kind, n in counts.items():
        assert len(act(session, kind)) == n, kind
    assert_equivalent(session, NOON)


def test_f1_backfill_idempotent(session):
    """Trap 5: running backfill again creates nothing and changes no number."""
    from app.services import activity, stats

    assert activity.backfill(session) == 0  # empty database
    _raw_world(session)
    activity.backfill(session)
    first_rows = snapshot_rows(session)
    first = assert_equivalent(session, NOON)
    assert activity.backfill(session) == 0
    assert activity.backfill(session) == 0
    assert snapshot_rows(session) == first_rows
    assert assert_equivalent(session, NOON) == first
    assert stats.practice_heatmap(session, NOON).total_minutes == 30 + 20.5 + 45 + 10 + 25 + 40


def test_f1_fixture_upgrade_equivalence(tmp_path):
    """Trap 5: the seed database (it has reviews), plus rows of every practice kind, reports the same numbers
    after migrating as the legacy readers computed before."""
    import tc_legacy as legacy
    from app.db import make_engine, migrate
    from app.services import activity

    # Adapted for main: the Lab's fixture (a snapshot of the real database) stays in the Lab, never in this repo.
    src = os.environ.get("LAB_FIXTURE_DB") or "E:/Backup Desktop/Claude Code Projects/Orchestration Lab/fixtures/data/russian.db"
    if not os.path.exists(src):
        pytest.skip("the Orchestration Lab's fixture database is not on this machine")
    dest = tmp_path / "upgrade.db"
    shutil.copy2(src, dest)
    engine = make_engine(f"sqlite:///{dest}")
    d = lambda n: TODAY - timedelta(days=n)  # noqa: E731
    with engine.begin() as conn:
        cs_id = conn.execute(text("SELECT id FROM card_state ORDER BY id LIMIT 1")).scalar()
        assert cs_id is not None
        for n in range(0, 9):  # a run of completed days ending today
            raw_session(conn, d(n), 15.0 + n, n != 4, reviews=n, new_cards=n % 3)
        raw_session(conn, d(0), 33.5, False)
        raw_input(conn, d(0), 20, "reading")
        raw_input(conn, d(6), 50, "listening")
        for i in range(11):
            raw_review(conn, cs_id, d(2), rating=3, hour=8 + i)
        raw_review(conn, cs_id, d(7), rating=1)
        story = raw_story(conn)
        raw_attempt(conn, story, d(3))
    with Session(engine) as db:
        want_streaks = legacy.streaks(db, NOON)
        want_summary = legacy.day_summary(db, NOON)
        want_heat = legacy.heatmap(db, NOON)
        want_medals = legacy.medal_measures(db, NOON)
        n_reviews = db.exec(text("SELECT COUNT(*) FROM review_log")).scalar()
        n_sessions = db.exec(text("SELECT COUNT(*) FROM sessions")).scalar()
    assert n_reviews == 6 + 12 and want_streaks[1] >= 4 and want_summary is not None

    version = migrate(engine)
    assert version >= 13
    with Session(engine) as db:
        got = assert_equivalent(db, NOON)
        assert got["streaks"] == want_streaks
        assert got["day_summary"] == want_summary
        assert got["heatmaps"][26] == want_heat
        for k, v in want_medals.items():
            assert got["medals"][k] == v
        assert len(act(db, "review")) == n_reviews
        assert len(act(db, "session")) == n_sessions
        assert len(act(db, "input")) == 2 and len(act(db, "story_attempt")) == 1
        before = snapshot_rows(db)
        assert activity.backfill(db) == 0
    migrate(engine)  # running the migrations again changes nothing
    with Session(engine) as db:
        assert snapshot_rows(db) == before
    engine.dispose()

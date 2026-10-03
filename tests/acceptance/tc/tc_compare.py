"""Reading the activity table without assuming where the model lives, and comparing readers with the legacy oracle."""

import json
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from tc_helpers import naive_utc

PRACTICE_MEDALS = ("streak_7", "streak_30", "first_story", "flawless", "hours_100")


def act(db, kind=None):
    """Activity rows as dicts (raw SQL): kind, ref_id, day (date), minutes, detail (dict or None), at (naive UTC)."""
    out = []
    for r in db.exec(text("SELECT kind, ref_id, day, minutes, detail, at FROM activity ORDER BY id")).all():
        detail = r[4]
        if isinstance(detail, str):
            detail = json.loads(detail)
        day = r[2] if isinstance(r[2], date) else date.fromisoformat(str(r[2])[:10])
        at = r[5] if isinstance(r[5], datetime) else datetime.fromisoformat(str(r[5]))
        out.append(dict(kind=r[0], ref_id=r[1], day=day, minutes=r[3], detail=detail, at=naive_utc(at)))
    return [a for a in out if kind is None or a["kind"] == kind]


def snapshot_rows(db):
    return sorted(
        (a["kind"], a["ref_id"], a["day"], float(a["minutes"]), repr(sorted((a["detail"] or {}).items())))
        for a in act(db)
    )


def local_day_of(dt):
    return dt.replace(tzinfo=timezone.utc).astimezone().date() if dt.tzinfo is None else dt.astimezone().date()


def readers(db, now, weeks=(26, 4)):
    """The run's four readers, reduced to comparable plain values."""
    import legacy
    from app.services import medals, stats, today

    s = stats.streaks(db, now)
    ds = today.day_summary(db, now)
    states = {st.defn.key: st for st in medals.evaluate(db, now)}
    return dict(
        streaks=(s.current, s.longest),
        day_summary=None if ds is None else (ds.sessions, ds.minutes, ds.reviews, ds.new_cards, ds.streak),
        heatmaps={w: legacy.flatten_heatmap(stats.practice_heatmap(db, now, w)) for w in weeks},
        medals={k: float(states[k].current) for k in PRACTICE_MEDALS},
        earned={k: states[k].earned for k in PRACTICE_MEDALS},
    )


def expected(db, now, weeks=(26, 4)):
    """The same values computed by the legacy oracle from the source tables."""
    import legacy
    from app.services import medals

    measures = legacy.medal_measures(db, now)
    targets = {m.key: m.target for m in medals.MEDALS}
    return dict(
        streaks=legacy.streaks(db, now),
        day_summary=legacy.day_summary(db, now),
        heatmaps={w: legacy.heatmap(db, now, w) for w in weeks},
        medals=measures,
        earned={k: measures[k] >= targets[k] for k in PRACTICE_MEDALS},
    )


def assert_equivalent(db, now, weeks=(26, 4)):
    n_source = sum(db.exec(text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in ("sessions", "review_log", "input_log"))
    assert (len(act(db)) > 0) == (n_source > 0), "the activity table must mirror the source rows"
    got, want = readers(db, now, weeks), expected(db, now, weeks)
    assert got["streaks"] == want["streaks"], "streaks differ"
    assert got["day_summary"] == want["day_summary"], "day_summary differs"
    for w in weeks:
        assert got["heatmaps"][w] == want["heatmaps"][w], f"heatmap ({w} weeks) differs"
    for k in PRACTICE_MEDALS:
        assert got["medals"][k] == pytest.approx(want["medals"][k]), f"medal measure {k} differs"
    assert got["earned"] == want["earned"], "earned medals differ"
    return got


def fresh_db(tmp_path, name):
    """A new migrated database and an open session on it."""
    from sqlmodel import Session

    from app.db import make_engine, migrate

    engine = make_engine(f"sqlite:///{tmp_path / (name + '.db')}")
    migrate(engine)
    return engine, Session(engine)

"""The unified activity log (Phase 6).

One `activity` row per piece of practice, kept in step with its source row (a study session, review,
drill answer, translation attempt, learner role-play turn or input log). Summaries read this table instead
of the six source tables. Activity is history: deleting a source row never deletes its activity.

Sync mechanism: a SQLAlchemy `after_flush` hook on every ORM session upserts the activity row for each
source row that was added or changed in the flush (INSERT ... ON CONFLICT DO UPDATE, in the same
transaction and so the same commit). It catches code that writes source rows directly through the ORM as
well as the services. `backfill` covers rows written by other means (raw SQL, upgrades).

This module must not import `stats` (stats reads it).
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import event, inspect
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import Session as DbSession, col, select

from app import models
from app.models import Activity

KINDS = ("session", "review", "drill_answer", "story_attempt", "roleplay_turn", "input")

_ACTIVITY = Activity.__table__


def _utc(dt: datetime) -> datetime:
    """SQLite hands datetimes back naive; they are always UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def local_date(dt: datetime) -> date:
    """The learner's calendar date (system local time) for a stored timestamp."""
    return _utc(dt).astimezone().date()


# --- source row -> activity values -----------------------------------------------------------


def _values(obj) -> dict | None:
    """The activity values for a source row, or None if the object is not practice."""
    if isinstance(obj, models.Session):
        return dict(kind="session", ref_id=obj.id, at=obj.started_at, day=obj.date, minutes=float(obj.minutes or 0),
                    detail={"completed": bool(obj.completed), "reviews": int(obj.reviews or 0),
                            "new_cards": int(obj.new_cards or 0)})
    if isinstance(obj, models.ReviewLog):
        return dict(kind="review", ref_id=obj.id, at=obj.reviewed_at, day=local_date(obj.reviewed_at), minutes=0.0,
                    detail={"rating": int(obj.rating), "state_before": int(obj.state_before)})
    if isinstance(obj, models.DrillAnswer):
        return dict(kind="drill_answer", ref_id=obj.id, at=obj.created_at, day=local_date(obj.created_at),
                    minutes=0.0, detail={"correct": bool(obj.correct)})
    if isinstance(obj, models.TranslationAttempt):
        return dict(kind="story_attempt", ref_id=obj.id, at=obj.created_at, day=local_date(obj.created_at),
                    minutes=0.0, detail={"story_id": obj.story_id})
    if isinstance(obj, models.Message) and obj.role == "user":
        return dict(kind="roleplay_turn", ref_id=obj.id, at=obj.created_at, day=local_date(obj.created_at),
                    minutes=0.0, detail={"conversation_id": obj.conversation_id})
    if isinstance(obj, models.InputLog):
        return dict(kind="input", ref_id=obj.id, at=obj.created_at, day=obj.date, minutes=float(obj.minutes or 0),
                    detail={"kind": obj.kind})
    return None


_SOURCES = {
    "session": models.Session,
    "review": models.ReviewLog,
    "drill_answer": models.DrillAnswer,
    "story_attempt": models.TranslationAttempt,
    "roleplay_turn": models.Message,
    "input": models.InputLog,
}

_SOURCE_TYPES = tuple(_SOURCES.values())


def _upsert(connection, rows: list[dict]) -> None:
    stmt = sqlite_insert(_ACTIVITY)
    stmt = stmt.on_conflict_do_update(
        index_elements=["kind", "ref_id"],
        set_={c: stmt.excluded[c] for c in ("at", "day", "minutes", "detail")},
    )
    connection.execute(stmt, [{**r, "at": _utc(r["at"])} for r in rows])


def _after_flush(session: OrmSession, _context) -> None:
    rows = []
    for obj in list(session.new) + [o for o in session.dirty if session.is_modified(o)]:
        if isinstance(obj, _SOURCE_TYPES) and obj.id is not None:
            values = _values(obj)
            if values is not None:
                rows.append(values)
    if not rows:
        return
    try:
        _upsert(session.connection(), rows)
    except OperationalError as error:  # the table does not exist yet (a database mid-upgrade)
        if "no such table" not in str(error):
            raise


event.listen(OrmSession, "after_flush", _after_flush)


# --- the service ---------------------------------------------------------------------------------


def record(session: DbSession, kind: str, ref_id: int, at: datetime, day: date, minutes: float = 0.0,
           detail: dict | None = None) -> Activity:
    """Insert the activity row for (kind, ref_id), or update it if it exists."""
    row = session.exec(select(Activity).where(Activity.kind == kind, Activity.ref_id == ref_id)).first()
    if row is None:
        row = Activity(kind=kind, ref_id=ref_id, at=_utc(at), day=day, minutes=minutes, detail=detail)
    else:
        row.at, row.day, row.minutes, row.detail = _utc(at), day, minutes, detail
    session.add(row)
    session.flush()
    return row


def between(session: DbSession, first: date, last: date, kinds: Iterable[str] | None = None) -> list[Activity]:
    """Rows with first <= day <= last, oldest first."""
    query = select(Activity).where(Activity.day >= first, Activity.day <= last)
    if kinds is not None:
        query = query.where(col(Activity.kind).in_(list(kinds)))
    query = query.order_by(col(Activity.day), col(Activity.at), col(Activity.id))
    return list(session.exec(query.execution_options(populate_existing=True)).all())


def backfill(session: DbSession) -> int:
    """Create the missing activity rows for existing source rows; returns how many. Idempotent.

    Tolerates databases that predate some source tables (or this one).
    """
    session.flush()
    connection = session.connection()
    tables = set(inspect(connection).get_table_names())
    if _ACTIVITY.name not in tables:
        return 0
    created = 0
    for kind, model in _SOURCES.items():
        if model.__tablename__ not in tables:
            continue
        have = select(Activity.ref_id).where(Activity.kind == kind)
        query = select(model).where(col(model.id).not_in(have))
        rows = [v for obj in session.exec(query).all() if (v := _values(obj)) is not None]
        if rows:
            _upsert(connection, rows)
            created += len(rows)
    return created


# --- timeline -------------------------------------------------------------------------------------


@dataclass
class TimelineLine:
    kind: str
    count: int
    minutes: float
    label: str


@dataclass
class TimelineDay:
    day: date
    lines: list[TimelineLine] = field(default_factory=list)


def _num(value: float) -> str:
    value = round(value, 1)
    return str(int(value)) if value == int(value) else str(value)


def _label(kind: str, count: int, minutes: float) -> str:
    one = count == 1
    if kind == "session":
        return f"{count} {'session' if one else 'sessions'}, {_num(minutes)} min"
    if kind == "review":
        return f"{count} {'review' if one else 'reviews'}"
    if kind == "drill_answer":
        return f"{count} {'drill answer' if one else 'drill answers'}"
    if kind == "story_attempt":
        return f"{count} {'translation' if one else 'translations'}"
    if kind == "roleplay_turn":
        return f"{count} {'role-play turn' if one else 'role-play turns'}"
    return f"{_num(minutes)} min of reading, listening or watching"


def timeline(session: DbSession, now: datetime, days: int = 14) -> list[TimelineDay]:
    """The last `days` local days including today, newest first; days without activity are left out."""
    today = local_date(now)
    rows = between(session, today - timedelta(days=days - 1), today)
    grouped: dict[date, dict[str, list[float]]] = {}
    for row in rows:
        if row.kind == "session" and not (row.detail or {}).get("completed"):
            continue
        grouped.setdefault(row.day, {}).setdefault(row.kind, []).append(row.minutes or 0.0)
    result = []
    for day in sorted(grouped, reverse=True):
        lines = []
        for kind in KINDS:
            if kind in grouped[day]:
                minutes = grouped[day][kind]
                total = round(sum(minutes), 1) if kind in ("session", "input") else 0.0
                lines.append(TimelineLine(kind, len(minutes), total, _label(kind, len(minutes), total)))
        result.append(TimelineDay(day, lines))
    return result

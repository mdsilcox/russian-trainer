"""The Today page: build the daily plan and track study sessions.

Pure reads/writes over the database; `now` is injectable for tests. Reviews
made in /review are attributed to a session by time window, not by hooks.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlmodel import Session as DbSession, col, select

from app.models import ReviewLog, Session, Setting, Story, TranslationAttempt
from app.services import srs, stats

HISTORY_DAYS = 14
OUTLIER_SECONDS = 120.0
OVERHEAD_SECONDS = 3.0
DEFAULT_SECONDS_PER_CARD = 12.0
MAX_SESSION_MINUTES = 90.0
MIN_SESSION_MINUTES = 1.0
DEFAULT_SPLIT = {"srs": 10, "drill_or_story": 8, "scenario": 7}


def _now(now: datetime | None) -> datetime:
    return srs._utc(now or datetime.now(timezone.utc))


def session_split(db: DbSession) -> dict[str, int]:
    """Minutes per block from the `session_split` setting, falling back to the defaults."""
    row = db.get(Setting, "session_split")
    split = dict(DEFAULT_SPLIT)
    if row is not None and isinstance(row.value, dict):
        for key in split:
            try:
                split[key] = max(0, int(row.value.get(key, split[key])))
            except (TypeError, ValueError):
                pass
    return split


def seconds_per_card(db: DbSession, now: datetime | None = None) -> float:
    """Average seconds per card over the last 14 days, plus a few seconds of overhead.

    Rows without a duration and outliers (walked away mid-card) are ignored.
    """
    since = _now(now) - timedelta(days=HISTORY_DAYS)
    durations = db.exec(
        select(ReviewLog.duration_ms).where(ReviewLog.reviewed_at >= since, col(ReviewLog.duration_ms).is_not(None))
    ).all()
    seconds = [d / 1000 for d in durations if 0 < d / 1000 <= OUTLIER_SECONDS]
    if not seconds:
        return DEFAULT_SECONDS_PER_CARD
    return sum(seconds) / len(seconds) + OVERHEAD_SECONDS


@dataclass(frozen=True)
class ReviewBlock:
    queued: int  # cards waiting today (due reviews + remaining new cards)
    new: int  # of which new
    budget_minutes: int
    seconds_per_card: float
    max_cards: int  # how many fit in the budget
    planned: int  # min(queued, max_cards)
    minutes: float  # estimate for the planned cards
    rollover: int  # queued cards that won't fit and stay due


def plan_reviews(db: DbSession, now: datetime | None = None) -> ReviewBlock:
    now = _now(now)
    queue = srs.build_queue(db, now)
    budget = session_split(db)["srs"]
    spc = seconds_per_card(db, now)
    max_cards = int(budget * 60 // spc)
    planned = min(len(queue), max_cards)
    return ReviewBlock(
        queued=len(queue),
        new=sum(1 for cs in queue if cs.state == srs.NEW),
        budget_minutes=budget,
        seconds_per_card=spc,
        max_cards=max_cards,
        planned=planned,
        minutes=round(planned * spc / 60, 1),
        rollover=len(queue) - planned,
    )


@dataclass(frozen=True)
class WritingBlock:
    minutes: int
    story: Story | None  # a story to revise, else None -> write a new one
    href: str


def suggest_story(db: DbSession) -> Story | None:
    """The most recently worked-on story whose latest attempt has feedback but no revision after it."""
    rows = db.exec(
        select(TranslationAttempt).order_by(col(TranslationAttempt.created_at).desc(), col(TranslationAttempt.id).desc())
    ).all()
    seen: set[int] = set()
    for attempt in rows:
        if attempt.story_id in seen:
            continue
        seen.add(attempt.story_id)  # first row seen per story is its latest attempt
        if attempt.feedback_json or attempt.corrected_text:
            story = db.get(Story, attempt.story_id)
            if story is not None:
                return story
    return None


def plan_writing(db: DbSession) -> WritingBlock:
    story = suggest_story(db)
    return WritingBlock(
        minutes=session_split(db)["drill_or_story"],
        story=story,
        href=f"/workshop/{story.id}" if story else "/workshop/new",
    )


@dataclass(frozen=True)
class Plan:
    reviews: ReviewBlock
    writing: WritingBlock
    speaking_minutes: int


def build_plan(db: DbSession, now: datetime | None = None) -> Plan:
    return Plan(plan_reviews(db, now), plan_writing(db), session_split(db)["scenario"])


# --- Session tracking ----------------------------------------------------------


def active_session(db: DbSession, now: datetime | None = None) -> Session | None:
    """The unfinished session in progress; one abandoned over 90 minutes ago is ignored."""
    now = _now(now)
    cutoff = now - timedelta(minutes=MAX_SESSION_MINUTES)
    rows = db.exec(select(Session).where(Session.completed == False).order_by(col(Session.started_at).desc())).all()  # noqa: E712
    for row in rows:
        if cutoff <= srs._utc(row.started_at) <= now:
            return row
    return None


def start_session(db: DbSession, now: datetime | None = None) -> Session:
    """Begin a session, or return the one already running."""
    now = _now(now)
    current = active_session(db, now)
    if current is not None:
        return current
    row = Session(date=stats.local_date(now), started_at=now)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def count_reviews(db: DbSession, since: datetime, until: datetime) -> tuple[int, int]:
    """(reviews, distinct new cards) logged in [since, until]."""
    since, until = srs._utc(since), srs._utc(until)
    window = (ReviewLog.reviewed_at >= since, ReviewLog.reviewed_at <= until)
    reviews = db.exec(select(func.count()).select_from(ReviewLog).where(*window)).one()
    new = db.exec(
        select(func.count(func.distinct(ReviewLog.card_state_id))).where(ReviewLog.state_before == srs.NEW, *window)
    ).one()
    return reviews, new


def finish_session(db: DbSession, now: datetime | None = None) -> Session | None:
    """Close the running session. Returns None if there is none or less than a minute has passed."""
    now = _now(now)
    row = active_session(db, now)
    if row is None:
        return None
    started = srs._utc(row.started_at)
    elapsed = (now - started).total_seconds() / 60
    if elapsed < MIN_SESSION_MINUTES:
        return None
    row.minutes = round(min(elapsed, MAX_SESSION_MINUTES), 1)
    row.reviews, row.new_cards = count_reviews(db, started, now)
    row.completed = True
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@dataclass(frozen=True)
class DaySummary:
    sessions: int
    minutes: float
    reviews: int
    new_cards: int
    streak: int


def day_summary(db: DbSession, now: datetime | None = None) -> DaySummary | None:
    """Totals across today's completed sessions, or None if there are none."""
    now = _now(now)
    rows = db.exec(select(Session).where(Session.date == stats.local_date(now), Session.completed == True)).all()  # noqa: E712
    if not rows:
        return None
    return DaySummary(
        sessions=len(rows),
        minutes=round(sum(r.minutes for r in rows), 1),
        reviews=sum(r.reviews for r in rows),
        new_cards=sum(r.new_cards for r in rows),
        streak=stats.streaks(db, now).current,
    )

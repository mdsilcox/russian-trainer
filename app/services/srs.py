"""Spaced repetition on top of the `fsrs` package.

card_state.state is 0 for a card never reviewed ("new"); otherwise it holds
the fsrs.State value (1 learning, 2 review, 3 relearning).
"""

from datetime import datetime, time, timedelta, timezone

import fsrs
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.models import Card, CardState, Direction, ReviewLog, Setting

NEW = 0
DEFAULT_RETENTION = 0.9
DEFAULT_NEW_PER_DAY = 15


def _utc(dt: datetime) -> datetime:
    """SQLite hands datetimes back naive; they're always stored as UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _setting(session: Session, key: str, default):
    row = session.get(Setting, key)
    return row.value if row is not None else default


def make_scheduler(session: Session) -> fsrs.Scheduler:
    return fsrs.Scheduler(desired_retention=float(_setting(session, "desired_retention", DEFAULT_RETENTION)))


def to_fsrs(cs: CardState) -> fsrs.Card:
    if cs.state == NEW:
        return fsrs.Card(card_id=cs.id, state=fsrs.State.Learning, step=0, due=_utc(cs.due))
    return fsrs.Card(
        card_id=cs.id,
        state=fsrs.State(cs.state),
        step=cs.step,
        stability=cs.stability,
        difficulty=cs.difficulty,
        due=_utc(cs.due),
        last_review=_utc(cs.last_review) if cs.last_review else None,
    )


def review(
    session: Session,
    cs: CardState,
    rating: fsrs.Rating,
    now: datetime | None = None,
    duration_ms: int | None = None,
    scheduler: fsrs.Scheduler | None = None,
) -> ReviewLog:
    """Apply one rating: update the card's memory state and write a log row."""
    now = now or datetime.now(timezone.utc)
    scheduler = scheduler or make_scheduler(session)
    log = ReviewLog(
        card_state_id=cs.id,
        rating=int(rating),
        reviewed_at=now,
        duration_ms=duration_ms,
        state_before=cs.state,
        due_before=_utc(cs.due),
    )
    updated, _ = scheduler.review_card(to_fsrs(cs), rating, now)

    if rating == fsrs.Rating.Again and cs.state == fsrs.State.Review:
        cs.lapses += 1
    cs.reps += 1
    cs.state = int(updated.state)
    cs.step = updated.step
    cs.stability = updated.stability
    cs.difficulty = updated.difficulty
    cs.due = updated.due
    cs.last_review = updated.last_review

    session.add(cs)
    session.add(log)
    session.commit()
    return log


def day_start(now: datetime) -> datetime:
    """Local midnight for `now`, in UTC. A study day follows your clock, not UTC."""
    local = _utc(now).astimezone()
    return datetime.combine(local.date(), time.min, tzinfo=local.tzinfo).astimezone(timezone.utc)


def new_introduced_today(session: Session, now: datetime) -> int:
    return session.exec(
        select(func.count(func.distinct(ReviewLog.card_state_id))).where(
            ReviewLog.state_before == NEW, ReviewLog.reviewed_at >= day_start(now)
        )
    ).one()


def _active(query):
    return query.join(Card, Card.id == CardState.card_id).where(Card.suspended == False)  # noqa: E712


def due_reviews(session: Session, now: datetime) -> list[CardState]:
    query = select(CardState).where(CardState.state != NEW, CardState.due <= now).order_by(col(CardState.due))
    return list(session.exec(_active(query)).all())


def new_cards(session: Session, limit: int) -> list[CardState]:
    if limit <= 0:
        return []
    query = select(CardState).where(CardState.state == NEW).order_by(col(Card.created_at), col(CardState.id))
    return list(session.exec(_active(query).limit(limit)).all())


def interleave(reviews: list, new: list) -> list:
    """Spread new cards evenly through the reviews instead of leaving them all for the end."""
    if not new:
        return list(reviews)
    gap = max(1, len(reviews) // len(new))
    out, reviews_iter = [], iter(reviews)
    for card in new:
        out.extend(next(reviews_iter, None) for _ in range(gap))
        out.append(card)
    out.extend(reviews_iter)
    return [c for c in out if c is not None]


def build_queue(session: Session, now: datetime | None = None, max_cards: int | None = None) -> list[CardState]:
    """Today's queue: due reviews (oldest first) with today's remaining new cards mixed in.

    `max_cards` caps a session to its time budget; anything left over stays
    due and rolls into the next session.
    """
    now = now or datetime.now(timezone.utc)
    reviews = due_reviews(session, now)
    per_day = int(_setting(session, "daily_new_cards", DEFAULT_NEW_PER_DAY))
    new = new_cards(session, per_day - new_introduced_today(session, now))
    if max_cards is not None:
        reviews = reviews[:max_cards]
        new = new[: max(0, max_cards - len(reviews))]
    return interleave(reviews, new)


def forecast(session: Session, days: int, now: datetime | None = None) -> list[int]:
    """Reviews falling due on each of the next `days` days (index 0 = today, incl. overdue)."""
    now = now or datetime.now(timezone.utc)
    start = day_start(now)
    counts = [0] * days
    query = select(CardState.due).where(CardState.state != NEW, CardState.due < start + timedelta(days=days))
    for due in session.exec(_active(query)).all():
        counts[max(0, (_utc(due) - start).days)] += 1
    return counts


# --- Review screen helpers -----------------------------------------------------

# A recognition card unlocks its EN→RU production card once FSRS expects you to
# remember it for at least this many days.
PRODUCTION_UNLOCK_STABILITY = 5.0


def maybe_unlock_production(session: Session, cs: CardState) -> CardState | None:
    if cs.direction != Direction.recognition or cs.state != fsrs.State.Review:
        return None
    if (cs.stability or 0) < PRODUCTION_UNLOCK_STABILITY:
        return None
    exists = session.exec(
        select(CardState).where(CardState.card_id == cs.card_id, CardState.direction == Direction.production)
    ).first()
    if exists:
        return None
    production = CardState(card_id=cs.card_id, direction=Direction.production)
    session.add(production)
    session.commit()
    return production


def preview_intervals(scheduler: fsrs.Scheduler, cs: CardState, now: datetime) -> dict[int, timedelta]:
    """What each rating would schedule, for the labels on the rating buttons."""
    card = to_fsrs(cs)
    return {int(r): scheduler.review_card(card, r, now)[0].due - now for r in fsrs.Rating}


def format_interval(delta: timedelta) -> str:
    minutes = delta.total_seconds() / 60
    if minutes < 60:
        return f"{max(1, round(minutes))}m"
    if minutes < 60 * 24:
        return f"{round(minutes / 60)}h"
    days = minutes / (60 * 24)
    if days < 30:
        return f"{round(days)}d"
    if days < 365:
        return f"{round(days / 30)}mo"
    return f"{days / 365:.1f}y"


def next_learning_due(session: Session, now: datetime, within: timedelta = timedelta(hours=1)) -> datetime | None:
    """When the next card in a short learning step comes back, if that's soon."""
    query = select(func.min(CardState.due)).where(
        col(CardState.state).in_([int(fsrs.State.Learning), int(fsrs.State.Relearning)]),
        CardState.due > now,
        CardState.due <= now + within,
    )
    due = session.exec(_active(query)).one()
    return _utc(due) if due else None

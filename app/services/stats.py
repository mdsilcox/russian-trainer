"""Dashboard numbers. Pure reads over the database; `now` is injectable for tests."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlmodel import Session as DbSession, col, select

from app.models import Card, CardState, Category, Mistake, ReviewLog, Session, Setting
from app.services import srs

WINDOW_DAYS = 30
FORECAST_DAYS = 7

CATEGORY_LABELS = {
    Category.case: "Cases",
    Category.aspect: "Verb aspect",
    Category.motion_verb: "Verbs of motion",
    Category.participle: "Participles",
    Category.agreement: "Agreement",
    Category.word_choice: "Word choice",
    Category.word_order: "Word order",
    Category.preposition: "Prepositions",
    Category.stress: "Stress",
    Category.spelling: "Spelling",
    Category.idiom: "Idioms",
}


def category_label(category: Category) -> str:
    return CATEGORY_LABELS.get(category, str(category.value).replace("_", " ").capitalize())


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def local_date(now: datetime | None = None) -> date:
    """The learner's calendar date (system local time) for `now`."""
    return srs._utc(_now(now)).astimezone().date()


@dataclass(frozen=True)
class Streak:
    current: int
    longest: int


def streaks(session: DbSession, now: datetime | None = None) -> Streak:
    """Consecutive days with a completed session. A day without one yet doesn't break the streak until it ends."""
    today = local_date(now)
    days = set(session.exec(select(Session.date).where(Session.completed == True)).all())  # noqa: E712
    if not days:
        return Streak(0, 0)

    longest = run = 0
    previous: date | None = None
    for day in sorted(days):
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day

    day = today if today in days else today - timedelta(days=1)
    current = 0
    while day in days:
        current += 1
        day -= timedelta(days=1)
    return Streak(current, longest)


def forecast_labels(now: datetime | None = None, days: int = FORECAST_DAYS) -> list[str]:
    """Bar labels for the forecast: "Today", then weekday abbreviations."""
    today = local_date(now)
    return ["Today"] + [(today + timedelta(days=i)).strftime("%a") for i in range(1, days)]


def review_forecast(session: DbSession, now: datetime | None = None, days: int = FORECAST_DAYS) -> list[tuple[str, int]]:
    counts = srs.forecast(session, days, _now(now))
    return list(zip(forecast_labels(now, days), counts))


def reviews_due_today(session: DbSession, now: datetime | None = None) -> int:
    return len(srs.due_reviews(session, _now(now)))


def retention(session: DbSession, now: datetime | None = None, days: int = WINDOW_DAYS) -> float | None:
    """Share of non-new card reviews in the last `days` days not rated Again; None with no data."""
    since = srs._utc(_now(now)) - timedelta(days=days)
    rows = session.exec(
        select(ReviewLog.rating).where(ReviewLog.state_before != srs.NEW, ReviewLog.reviewed_at >= since)
    ).all()
    return sum(1 for rating in rows if rating > 1) / len(rows) if rows else None


def days_until_trip(session: DbSession, now: datetime | None = None) -> int | None:
    """Whole days from today (local) to the `trip_date` setting; negative once it has passed."""
    row = session.get(Setting, "trip_date")
    if row is None or not row.value:
        return None
    try:
        trip = date.fromisoformat(str(row.value))
    except ValueError:
        return None
    return (trip - local_date(now)).days


@dataclass(frozen=True)
class MistakeRow:
    category: Category
    label: str
    recent: int
    total: int


def top_mistakes(session: DbSession, now: datetime | None = None, limit: int = 5) -> list[MistakeRow]:
    """Categories ranked by mistakes in the last 30 days, then all-time."""
    since = srs._utc(_now(now)) - timedelta(days=WINDOW_DAYS)
    counts: dict[Category, list[int]] = {}
    for category, created_at in session.exec(select(Mistake.category, Mistake.created_at)).all():
        row = counts.setdefault(category, [0, 0])
        row[1] += 1
        row[0] += srs._utc(created_at) >= since
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0].value))
    return [MistakeRow(cat, category_label(cat), recent, total) for cat, (recent, total) in ranked[:limit]]


@dataclass(frozen=True)
class DeckCounts:
    cards: int
    new_waiting: int


def deck_counts(session: DbSession) -> DeckCounts:
    cards = session.exec(select(func.count()).select_from(Card).where(Card.suspended == False)).one()  # noqa: E712
    new = session.exec(
        srs._active(select(func.count()).select_from(CardState).where(CardState.state == srs.NEW))
    ).one()
    return DeckCounts(cards, new)

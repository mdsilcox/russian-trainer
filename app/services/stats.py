"""Dashboard numbers. Pure reads over the database; `now` is injectable for tests."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from math import ceil

from sqlalchemy import func
from sqlmodel import Session as DbSession, col, select

from app.models import Card, CardState, Category, InputLog, Mistake, Module, ReviewLog, Session, Setting
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

# --- Dashboard v2: trends and forecast ------------------------------------------------

MISTAKE_WEEKS = 12
MISTAKE_SERIES = 7  # categories drawn on their own; the rest are grouped as "Other"
RETENTION_MIN_REVIEWS = 5
FORECAST_CHART_DAYS = 30
HEATMAP_WEEKS = 26

# (solid, lighter tint for drills). Hues chosen to read on the black lacquer; cinnabar is left for fills.
SERIES_PALETTE = [
    ("#E8A94A", "#F6D9A8"),  # amber
    ("#4FB3A9", "#A9DDD7"),  # teal
    ("#6FA8DC", "#BCD6EE"),  # sky
    ("#B38BDB", "#DCCAEE"),  # violet
    ("#E58AA6", "#F4C4D2"),  # rose
    ("#8FBF6A", "#C9E2B4"),  # green
    ("#D9C7A0", "#EFE6D2"),  # sand
]
OTHER_COLORS = ("#8C8577", "#C4BEB1")

SOURCE_LABELS = {
    Module.manual: "Added by hand",
    Module.starter: "Starter deck",
    Module.story: "Stories",
    Module.drill: "Drills",
    Module.scenario: "Scenarios",
    Module.media: "Media",
    Module.tutor: "Tutor lessons",
}


def _local_day(moment: datetime) -> date:
    return srs._utc(moment).astimezone().date()


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _local_midnight_utc(day: date) -> datetime:
    return datetime.combine(day, time.min).astimezone().astimezone(timezone.utc)


def nice_axis(max_value: float, max_ticks: int = 4) -> tuple[int, list[int]]:
    """A round axis top (never below `max_value`) and its tick values from 0."""
    step = 1
    magnitude = 1
    while ceil(max_value / step) > max_ticks:
        step = {1: 2, 2: 5, 5: 10}[step // magnitude] * magnitude
        if step == 10 * magnitude:
            magnitude *= 10
            step = magnitude
    top = max(step, step * ceil(max_value / step))
    return top, list(range(0, top + 1, step))


@dataclass(frozen=True)
class MistakeSeries:
    label: str
    color: str
    tint: str
    total: int


@dataclass(frozen=True)
class MistakeSegment:
    series: MistakeSeries
    real: int  # outside drills: stories, scenarios, ...
    drill: int


@dataclass(frozen=True)
class MistakeWeek:
    start: date  # Monday
    segments: list[MistakeSegment]

    @property
    def total(self) -> int:
        return sum(s.real + s.drill for s in self.segments)


@dataclass(frozen=True)
class MistakeTrend:
    weeks: list[MistakeWeek]
    series: list[MistakeSeries]
    axis_max: int
    ticks: list[int]
    total: int


def mistake_trend(session: DbSession, now: datetime | None = None, weeks: int = MISTAKE_WEEKS) -> MistakeTrend:
    """Mistakes per category for each of the last `weeks` Monday-to-Sunday weeks (the last one holds today)."""
    today = local_date(now)
    first = _week_start(today) - timedelta(weeks=weeks - 1)
    rows = session.exec(
        select(Mistake.category, Mistake.module, Mistake.created_at).where(
            Mistake.created_at >= _local_midnight_utc(first) - timedelta(days=1)
        )
    ).all()

    # counts[week index][category] = [real, drill]
    counts: list[dict[Category, list[int]]] = [{} for _ in range(weeks)]
    totals: dict[Category, int] = {}
    for category, module, created_at in rows:
        day = _local_day(created_at)
        index = (day - first).days // 7
        if day < first or day > today:
            continue
        counts[index].setdefault(category, [0, 0])[module == Module.drill] += 1
        totals[category] = totals.get(category, 0) + 1

    order = list(Category)
    ranked = sorted(totals, key=lambda c: (-totals[c], order.index(c)))
    shown = ranked[:MISTAKE_SERIES]
    rest = ranked[MISTAKE_SERIES:]
    series = [MistakeSeries(category_label(c), *SERIES_PALETTE[i], totals[c]) for i, c in enumerate(shown)]
    if rest:
        series.append(MistakeSeries("Other", *OTHER_COLORS, sum(totals[c] for c in rest)))

    result = []
    for i in range(weeks):
        segments = [
            MistakeSegment(entry, *counts[i].get(category, [0, 0])) for category, entry in zip(shown, series)
        ]
        if rest:
            pairs = [counts[i].get(c, [0, 0]) for c in rest]
            segments.append(MistakeSegment(series[-1], sum(p[0] for p in pairs), sum(p[1] for p in pairs)))
        result.append(MistakeWeek(first + timedelta(weeks=i), segments))

    axis_max, ticks = nice_axis(max([w.total for w in result] + [1]))
    return MistakeTrend(result, series, axis_max, ticks, sum(totals.values()))


@dataclass(frozen=True)
class SourceRetention:
    source: Module
    label: str
    reviews: int
    kept: int  # reviews rated Hard or better

    @property
    def rate(self) -> float:
        return self.kept / self.reviews if self.reviews else 0.0


@dataclass(frozen=True)
class RetentionBySource:
    rows: list[SourceRetention]  # enough reviews to be meaningful
    hidden: list[SourceRetention]  # fewer than the minimum
    min_reviews: int


def retention_by_source(
    session: DbSession,
    now: datetime | None = None,
    days: int = WINDOW_DAYS,
    min_reviews: int = RETENTION_MIN_REVIEWS,
) -> RetentionBySource:
    """Share of non-new reviews rated 2 or above, per `Card.source_module`, over the last `days` days."""
    since = srs._utc(_now(now)) - timedelta(days=days)
    rows = session.exec(
        select(Card.source_module, ReviewLog.rating)
        .select_from(ReviewLog)
        .join(CardState, CardState.id == ReviewLog.card_state_id)
        .join(Card, Card.id == CardState.card_id)
        .where(ReviewLog.state_before != srs.NEW, ReviewLog.reviewed_at >= since)
    ).all()
    tally: dict[Module, list[int]] = {}
    for source, rating in rows:
        entry = tally.setdefault(source, [0, 0])
        entry[0] += 1
        entry[1] += rating >= 2
    found = [SourceRetention(m, SOURCE_LABELS[m], *tally[m]) for m in Module if m in tally]
    return RetentionBySource(
        [r for r in found if r.reviews >= min_reviews],
        [r for r in found if r.reviews < min_reviews],
        min_reviews,
    )


@dataclass(frozen=True)
class ForecastDay:
    day: date
    count: int


@dataclass(frozen=True)
class ReviewForecast:
    days: list[ForecastDay]  # days[0] is today and includes overdue reviews
    total: int
    axis_max: int
    ticks: list[int]


def forecast_days(session: DbSession, now: datetime | None = None, days: int = FORECAST_CHART_DAYS) -> ReviewForecast:
    today = local_date(now)
    counts = srs.forecast(session, days, _now(now))
    result = [ForecastDay(today + timedelta(days=i), n) for i, n in enumerate(counts)]
    axis_max, ticks = nice_axis(max(counts + [1]))
    return ReviewForecast(result, sum(counts), axis_max, ticks)


@dataclass(frozen=True)
class HeatCell:
    day: date
    study: float  # minutes in app sessions
    input: float  # minutes of reading, listening, watching
    level: int  # 0 (nothing) to 4

    @property
    def total(self) -> float:
        return self.study + self.input


@dataclass(frozen=True)
class Heatmap:
    weeks: list[list[HeatCell | None]]  # columns of 7 (Monday first); None for days not yet come
    month_labels: list[tuple[int, str]]  # (column, abbreviated month)
    busiest: float  # minutes on the busiest day: the top of the scale
    total_minutes: float
    active_days: int


def practice_heatmap(session: DbSession, now: datetime | None = None, weeks: int = HEATMAP_WEEKS) -> Heatmap:
    """Minutes practiced per day (app sessions plus logged input) for the last `weeks` weeks."""
    today = local_date(now)
    first = _week_start(today) - timedelta(weeks=weeks - 1)
    study: dict[date, float] = {}
    for day, minutes in session.exec(select(Session.date, Session.minutes).where(Session.date >= first)).all():
        study[day] = study.get(day, 0) + (minutes or 0)
    logged: dict[date, float] = {}
    for day, minutes in session.exec(select(InputLog.date, InputLog.minutes).where(InputLog.date >= first)).all():
        logged[day] = logged.get(day, 0) + (minutes or 0)

    days = [first + timedelta(days=i) for i in range(weeks * 7)]
    totals = [study.get(d, 0) + logged.get(d, 0) for d in days if d <= today]
    busiest = max(totals + [0])

    def level(total: float) -> int:
        return 0 if total <= 0 else min(4, ceil(4 * total / busiest))

    columns: list[list[HeatCell | None]] = []
    for w in range(weeks):
        column: list[HeatCell | None] = []
        for day in days[w * 7 : w * 7 + 7]:
            if day > today:
                column.append(None)
                continue
            s, i = study.get(day, 0), logged.get(day, 0)
            column.append(HeatCell(day, s, i, level(s + i)))
        columns.append(column)

    labels: list[tuple[int, str]] = []
    for w in range(weeks):
        monday = first + timedelta(weeks=w)
        if w == 0 or monday.month != (monday - timedelta(weeks=1)).month:
            labels.append((w, monday.strftime("%b")))
    if len(labels) > 1 and labels[1][0] - labels[0][0] < 3:
        labels.pop(0)

    return Heatmap(columns, labels, busiest, sum(totals), sum(1 for t in totals if t > 0))


# --- Weekly summary ---------------------------------------------------------------------


@dataclass(frozen=True)
class WeeklySummary:
    week_start: date  # Monday of the current local week
    days_practiced: int  # local days this week with a completed session or logged input
    minutes: float  # minutes in completed sessions this week, rounded to 0.1
    reviews: int  # reviews this week, including first reviews of new cards
    new_cards: int  # distinct cards (not card directions) reviewed for the first time this week
    retention: float | None  # this week's reviews, same definition as `retention`; None without data
    input_minutes: int  # logged input minutes this week
    prev_minutes: float  # minutes in completed sessions in the previous Monday-Sunday week
    prev_reviews: int  # reviews in the previous week


def weekly_summary(session: DbSession, now: datetime | None = None) -> WeeklySummary:
    """This local Monday-to-Sunday week so far, with the previous week for comparison."""
    week_start = _week_start(local_date(now))
    week_end = week_start + timedelta(days=7)
    prev_start = week_start - timedelta(days=7)
    start_utc, end_utc = _local_midnight_utc(week_start), _local_midnight_utc(week_end)
    prev_start_utc = _local_midnight_utc(prev_start)

    def session_minutes(first: date, last: date) -> float:
        total = session.exec(
            select(func.coalesce(func.sum(Session.minutes), 0)).where(
                Session.completed == True, Session.date >= first, Session.date < last  # noqa: E712
            )
        ).one()
        return round(float(total or 0), 1)

    def review_count(first: datetime, last: datetime) -> int:
        return session.exec(
            select(func.count()).select_from(ReviewLog).where(ReviewLog.reviewed_at >= first, ReviewLog.reviewed_at < last)
        ).one()

    session_days = set(
        session.exec(
            select(Session.date).where(Session.completed == True, Session.date >= week_start, Session.date < week_end)  # noqa: E712
        ).all()
    )
    input_days = set(
        session.exec(select(InputLog.date).where(InputLog.date >= week_start, InputLog.date < week_end)).all()
    )
    input_minutes = session.exec(
        select(func.coalesce(func.sum(InputLog.minutes), 0)).where(InputLog.date >= week_start, InputLog.date < week_end)
    ).one()

    first_review = func.min(ReviewLog.reviewed_at)
    new_cards = len(
        session.exec(
            select(CardState.card_id)
            .select_from(ReviewLog)
            .join(CardState, CardState.id == ReviewLog.card_state_id)
            .group_by(CardState.card_id)
            .having(first_review >= start_utc, first_review < end_utc)
        ).all()
    )

    ratings = session.exec(
        select(ReviewLog.rating).where(
            ReviewLog.state_before != srs.NEW, ReviewLog.reviewed_at >= start_utc, ReviewLog.reviewed_at < end_utc
        )
    ).all()

    return WeeklySummary(
        week_start=week_start,
        days_practiced=len(session_days | input_days),
        minutes=session_minutes(week_start, week_end),
        reviews=review_count(start_utc, end_utc),
        new_cards=new_cards,
        retention=sum(1 for r in ratings if r > 1) / len(ratings) if ratings else None,
        input_minutes=int(input_minutes or 0),
        prev_minutes=session_minutes(prev_start, week_start),
        prev_reviews=review_count(prev_start_utc, start_utc),
    )

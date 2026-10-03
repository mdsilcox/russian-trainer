"""The Today page: build the daily plan and track study sessions.

Pure reads/writes over the database; `now` is injectable for tests. Reviews
made in /review are attributed to a session by time window, not by hooks.
"""

import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo

from sqlalchemy import func
from sqlmodel import Session as DbSession, col, select

from app.models import Card, CardState, Conversation, DrillSet, ReviewLog, Scenario, Session, Setting, Story, TranslationAttempt
from app.services import drills, plan, shelf, srs, stats

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
class DrillBlock:
    minutes: int
    kind: str  # "focused" | "mixed" (of the open set if there is one, else of the planned one)
    labels: list[str]  # topic names
    open: DrillSet | None  # an unfinished set to carry on with
    href: str


def plan_drills(db: DbSession, now: datetime | None = None) -> DrillBlock | None:
    """The drill option for block II, or None when there is nothing to drill and no set is open."""
    current = drills.open_set(db)
    if current is not None:
        labels = list(dict.fromkeys(i.get("topic_label", "") for i in current.items_json if i.get("topic_label")))
        kind = current.kind
    else:
        kind, topics = drills.plan_next(db, now)
        if kind == "none":
            return None
        labels = [t.label for t in topics]
    return DrillBlock(session_split(db)["drill_or_story"], kind, labels, current, "/drills")


@dataclass(frozen=True)
class SpeakingBlock:
    minutes: int
    scenario: Scenario | None  # the scenario least recently practised, None when none are seeded
    href: str  # the suggested scenario, else the scenario list


def suggest_scenario(db: DbSession) -> Scenario | None:
    """Never-practised scenarios first, then the one practised longest ago; ties go by `Scenario.sort`."""
    scenarios = db.exec(select(Scenario).order_by(col(Scenario.sort), col(Scenario.id))).all()
    if not scenarios:
        return None
    last = dict(db.exec(select(Conversation.scenario_id, func.max(Conversation.started_at)).group_by(Conversation.scenario_id)).all())
    never = datetime.min.replace(tzinfo=timezone.utc)

    def key(sc: Scenario):
        when = last.get(sc.id)
        return (srs._utc(when) if when is not None else never, sc.sort, sc.id or 0)

    return min(scenarios, key=key)


def plan_speaking(db: DbSession) -> SpeakingBlock:
    scenario = suggest_scenario(db)
    return SpeakingBlock(session_split(db)["scenario"], scenario, f"/scenarios/{scenario.slug}" if scenario else "/scenarios")


@dataclass(frozen=True)
class Plan:
    reviews: ReviewBlock
    writing: WritingBlock
    speaking_minutes: int
    drills: DrillBlock | None = None
    drills_first: bool = False  # block II shows drills as its lead
    mode: str = "writing"  # what block II shows: drills | writing | input | light
    lead: bool = True  # block II is the day's lead (False on role-play days)
    speaking: SpeakingBlock | None = None
    speaking_lead: bool = False  # role-play day: block III leads
    day_kind: str = ""  # the weekly rhythm's kind for today
    day_weekday: str = ""
    day_title: str = ""
    month_title: str = ""
    review_title: str = ""  # a month waiting for its check-in
    input_minutes: int = 0  # reading and listening logged this week


def build_plan(db: DbSession, now: datetime | None = None) -> Plan:
    now = _now(now)
    focus = plan.day_focus(db, now)
    block = plan_drills(db, now)
    kind = focus.kind
    if kind in ("grammar", "interleaved") and block is not None:
        mode = "drills"
    elif kind == "input":
        mode = "input"
    elif kind == "light":
        mode = "light"
    else:
        mode = "writing"  # writing, translation, role-play days (and drill days with nothing to drill)
    due = plan.review_due(db, now)
    split = session_split(db)
    return Plan(
        plan_reviews(db, now), plan_writing(db), split["scenario"], block,
        drills_first=mode == "drills", mode=mode, lead=kind != "roleplay",
        speaking=plan_speaking(db), speaking_lead=kind == "roleplay",
        day_kind=kind, day_weekday=focus.weekday, day_title=focus.title,
        month_title=focus.month_title, review_title=due.title if due else "",
        input_minutes=shelf.this_week(db, now),
    )


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


# --- Header extras -------------------------------------------------------------

TRIP_MONTHS = 12


def date_label(now: datetime | None = None) -> str:
    """e.g. "Friday, 2 October" for the learner's local date."""
    d = stats.local_date(_now(now))
    return f"{d.strftime('%A')}, {d.day} {d.strftime('%B')}"


@dataclass(frozen=True)
class TripProgress:
    month: int  # 1..total, the month of the run-up to the trip we are in
    total: int
    trip_date: date


def trip_progress(db: DbSession, now: datetime | None = None) -> TripProgress | None:
    """Which of the 12 months before `trip_date` we are in; None with no trip date or once it has passed."""
    days_left = stats.days_until_trip(db, now)
    if days_left is None or days_left < 0:
        return None
    row = db.get(Setting, "trip_date")
    trip = date.fromisoformat(str(row.value))
    span = 365
    elapsed = min(max(span - days_left, 0), span - 1)
    return TripProgress(elapsed * TRIP_MONTHS // span + 1, TRIP_MONTHS, trip)


@dataclass(frozen=True)
class WeakSpot:
    label: str
    count: int


def weak_spots(db: DbSession, now: datetime | None = None, limit: int = 3) -> list[WeakSpot]:
    """Top mistake categories with at least one mistake in the last 30 days."""
    return [WeakSpot(m.label, m.recent) for m in stats.top_mistakes(db, now, limit) if m.recent > 0]


WORD_POOL_MIN = 7  # below this many still-learning cards, rotate through the whole deck
WORD_SETTLED_DAYS = 21  # stability past which a card counts as known


def _word_pool(db: DbSession) -> list[int]:
    """Card ids to rotate through: ones still being learned (reviewed, but shaky or lapsed),
    or every active card when too few qualify."""
    rows = db.exec(
        select(Card.id, CardState.state, CardState.stability, CardState.lapses)
        .join(CardState, CardState.card_id == Card.id, isouter=True)
        .where(Card.suspended == False)  # noqa: E712
    ).all()
    everything = sorted({r[0] for r in rows})
    learning = sorted({
        card_id for card_id, state, stability, lapses in rows
        if state and ((stability or 0) < WORD_SETTLED_DAYS or (lapses or 0) > 0)
    })
    return learning if len(learning) >= WORD_POOL_MIN else everything


def _shuffled(pool: list[int], cycle: int) -> list[int]:
    order = pool[:]
    random.Random(cycle * 7919 + len(pool)).shuffle(order)
    return order


def _pick(pool: list[int], day: date) -> int:
    """A fresh shuffle of the pool per cycle, walked one card per day, so every card comes up
    before any repeats, and a new cycle never opens with the card the last one ended on."""
    n = len(pool)
    if n <= 2:
        return pool[day.toordinal() % n]
    cycle, idx = divmod(day.toordinal(), n)
    order = _shuffled(pool, cycle)
    if order[0] == _shuffled(pool, cycle - 1)[-1]:  # the swap only touches the first two, so [-1] is final
        order[0], order[1] = order[1], order[0]
    return order[idx]


def word_of_the_day(db: DbSession, day: date) -> Card | None:
    """One card per calendar day, steady all day; None with an empty deck."""
    pool = _word_pool(db)
    return db.get(Card, _pick(pool, day)) if pool else None


# --- Flair: Moscow clock and the year's growth -----------------------------------

GROWTH_SPAN_DAYS = 365
GROWTH_STAGES = 5  # 0 bare stem, 1 leaves, 2 flowers, 3 berries forming, 4 full bloom


def _moscow_tz() -> tzinfo:
    """Europe/Moscow, or a fixed UTC+3 (Moscow has no DST) when tzdata is missing."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo("Europe/Moscow")
    except Exception:
        return timezone(timedelta(hours=3), "MSK")


def sky_phase(hour: int) -> str:
    """dawn 5-7, day 8-17, dusk 18-20, night otherwise (mirrors static/today.js)."""
    if 5 <= hour < 8:
        return "dawn"
    if 8 <= hour < 18:
        return "day"
    if 18 <= hour < 21:
        return "dusk"
    return "night"


@dataclass(frozen=True)
class MoscowClock:
    time: str  # "HH:MM"
    phase: str  # dawn | day | dusk | night


def moscow_clock(now: datetime | None = None) -> MoscowClock:
    local = _now(now).astimezone(_moscow_tz())
    return MoscowClock(local.strftime("%H:%M"), sky_phase(local.hour))


def growth_stage(days_left: int | None, span: int = GROWTH_SPAN_DAYS) -> int:
    """Stage 0..4 from the share of the final `span` days already elapsed.

    No trip date -> 0 (bare stem); trip reached or passed -> 4 (full bloom).
    """
    if days_left is None:
        return 0
    if days_left <= 0:
        return GROWTH_STAGES - 1
    elapsed = min(max(span - days_left, 0), span)
    return min(elapsed * GROWTH_STAGES // span, GROWTH_STAGES - 1)

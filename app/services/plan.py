"""The 12-month plan and the weekly rhythm (P4.2a).

The plan back-plans from the trip date (setting `trip_date`): twelve monthly blocks ending in the
trip month, following the research arc (docs/research.md): cases in speech first, then verbs of
motion and aspect, then fluency, stress and listening, then trip rehearsal with maintenance-only
SRS in the last weeks. Each month has a focus, measurable goals computed from data the app
already records, and the grammar topics whose drills it boosts.

The weekly rhythm maps each weekday to the kind of session that leads Today. It is a setting
(`weekly_rhythm`), defaulting to the research's week, so it can be changed without code.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.models import Card, Conversation, DrillSet, InputLog, PlanMonth, ReviewLog, Setting, TranslationAttempt
from app.models import Session as StudySession
from app.services import stats
from app.services.grammar import ASPECT, CASES, MOTION, NUMBERS

PLAN_MONTHS = 12
MONTH_BOOST = 1.5  # multiplier on this month's topics in weakness scoring
MONTH_PRIOR = 0.3  # and a small prior so they surface even without mistakes

# --- The arc ------------------------------------------------------------------------------------

# Goals are (metric, target, text). Metrics are counted over the calendar month:
METRICS = {
    "cards_added": "cards added",
    "reviews": "reviews",
    "drill_sets": "drill sets finished",
    "stories": "story drafts with feedback",
    "roleplays": "role-plays finished",
    "input_minutes": "minutes of reading and listening",
    "study_days": "days with a finished session",
}

ARC = [
    {"title": "Cases in everyday speech",
     "focus": "Where you are and where you are going: prepositional after в and на, accusative for direction, and the accusative of things you buy and see. These cover most travel sentences.",
     "topics": [f"{CASES}#prepositional", f"{CASES}#location-direction", f"{CASES}#accusative"],
     "goals": [("study_days", 20), ("cards_added", 120), ("drill_sets", 8), ("stories", 4)]},
    {"title": "The genitive everywhere",
     "focus": "Нет, мно́го, из, до, у, без and every price: the genitive and its plural, and numbers with nouns (1, 2-4, 5+).",
     "topics": [f"{CASES}#genitive", f"{CASES}#genitive-plural", f"{NUMBERS}#numbers-rule"],
     "goals": [("study_days", 20), ("cards_added", 120), ("drill_sets", 8), ("input_minutes", 300)]},
    {"title": "People: dative, instrumental, animate accusative",
     "focus": "Talking to and about people: мне ну́жно, мне нра́вится, к врачу́, с дру́гом, and seeing someone (ви́жу бра́та). Start role-play at level 1.",
     "topics": [f"{CASES}#dative", f"{CASES}#instrumental", f"{CASES}#animate-accusative"],
     "goals": [("study_days", 20), ("cards_added", 100), ("drill_sets", 8), ("roleplays", 4)]},
    {"title": "Going places: verbs of motion",
     "focus": "идти́ or ходи́ть, е́хать or е́здить: one way or round trip, on foot or by transport. The core of getting around Moscow.",
     "topics": [f"{MOTION}#motion-use", f"{MOTION}#motion-conjugation"],
     "goals": [("study_days", 20), ("cards_added", 100), ("drill_sets", 8), ("roleplays", 4)]},
    {"title": "Motion prefixes in the city",
     "focus": "Arriving, leaving, crossing and stopping by: при-, у-, вы́-, пере-, за-, до-, про-, and how prefixed verbs pair for aspect.",
     "topics": [f"{MOTION}#motion-prefixes", f"{MOTION}#motion-aspect"],
     "goals": [("study_days", 20), ("cards_added", 100), ("drill_sets", 8), ("stories", 4)]},
    {"title": "Aspect: finished or in progress",
     "focus": "Choosing perfective or imperfective in context, with negation (не на́до) and in requests. Mixed drills now interleave cases, motion and aspect.",
     "topics": [f"{ASPECT}#aspect-choose", f"{ASPECT}#aspect-pairs", f"{ASPECT}#aspect-negation", f"{ASPECT}#aspect-commands"],
     "goals": [("study_days", 20), ("cards_added", 100), ("drill_sets", 8), ("roleplays", 4)]},
    {"title": "Fluency: speaking without translating",
     "focus": "More role-play at level 2 and shorter stories written straight in Russian. Drills stay interleaved across everything so far.",
     "topics": [f"{CASES}#location-direction", f"{MOTION}#motion-use", f"{ASPECT}#aspect-choose"],
     "goals": [("study_days", 22), ("roleplays", 8), ("stories", 4), ("input_minutes", 450)]},
    {"title": "Stress and sound",
     "focus": "Mobile stress in nouns and the past tense, stress pairs, and shadowing short clips. Fridays go to translation and stress cards.",
     "topics": [f"{CASES}#genitive-plural", f"{NUMBERS}#numbers-rule"],
     "goals": [("study_days", 22), ("cards_added", 100), ("input_minutes", 600), ("roleplays", 6)]},
    {"title": "Natural-speed listening",
     "focus": "Native-pace input every week: series, YouTube and podcasts from the shelf, plus role-play at level 3.",
     "topics": [f"{ASPECT}#aspect-choose", f"{MOTION}#motion-prefixes"],
     "goals": [("study_days", 22), ("input_minutes", 900), ("roleplays", 8), ("reviews", 600)]},
    {"title": "Rehearsal: getting around and staying",
     "focus": "Every transport and hotel scenario at levels 2 and 3, including the problem scenarios. Fix whatever the debriefs keep flagging.",
     "topics": [f"{CASES}#location-direction", f"{MOTION}#motion-use", f"{MOTION}#motion-prefixes"],
     "goals": [("study_days", 22), ("roleplays", 12), ("input_minutes", 600), ("drill_sets", 6)]},
    {"title": "Rehearsal: food, shopping and family",
     "focus": "Restaurants, markets, the pharmacy and dinner with relatives at natural speed. Numbers and prices until they are automatic.",
     "topics": [f"{NUMBERS}#numbers-rule", f"{CASES}#genitive-plural", f"{CASES}#dative"],
     "goals": [("study_days", 22), ("roleplays", 12), ("input_minutes", 600), ("drill_sets", 6)]},
    {"title": "Final polish and maintenance",
     "focus": "Keep reviews going but add few new cards, and stop new cards entirely in the last two weeks. Short daily role-plays at level 3 to arrive warmed up.",
     "topics": [],
     "goals": [("study_days", 24), ("roleplays", 10), ("reviews", 400)]},
]

# --- The weekly rhythm --------------------------------------------------------------------------

@dataclass(frozen=True)
class DayKind:
    title: str
    why: str
    href: str


DAY_KINDS: dict[str, DayKind] = {
    "grammar": DayKind("Grammar drills", "A focused drill set on this month's weakest topic.", "/drills"),
    "writing": DayKind("Writing", "Write or revise a short story and fix it yourself first.", "/workshop"),
    "interleaved": DayKind("Mixed drills and shadowing", "Interleaved drills across topics, then shadow a short clip.", "/drills"),
    "roleplay": DayKind("Role-play", "A conversation from the scenario library at your level.", "/scenarios"),
    "translation": DayKind("Translation and stress", "Translate a short story and work on stress cards.", "/workshop"),
    "input": DayKind("Reading and listening", "Something from the shelf at the right level; log the minutes.", "/shelf"),
    "light": DayKind("Light review", "Just your reviews and something easy to watch.", "/review"),
}
DEFAULT_RHYTHM = ["grammar", "writing", "interleaved", "roleplay", "translation", "input", "light"]  # Monday first
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def rhythm(session: Session) -> list[str]:
    """Seven day kinds, Monday first, from the `weekly_rhythm` setting (defaults where missing or invalid)."""
    row = session.get(Setting, "weekly_rhythm")
    value = row.value if row is not None else None
    if isinstance(value, list) and len(value) == 7 and all(v in DAY_KINDS for v in value):
        return list(value)
    return list(DEFAULT_RHYTHM)


def set_rhythm(session: Session, kinds: list[str]) -> list[str]:
    if len(kinds) != 7 or any(k not in DAY_KINDS for k in kinds):
        raise ValueError("The rhythm needs one valid session kind for each of the seven days")
    row = session.get(Setting, "weekly_rhythm") or Setting(key="weekly_rhythm", value=None)
    row.value = list(kinds)
    session.add(row)
    session.commit()
    return list(kinds)


@dataclass(frozen=True)
class DayFocus:
    weekday: str  # "Monday"
    kind: str  # key of DAY_KINDS
    title: str
    why: str
    href: str
    month_title: str  # "" when no plan month covers today
    topics: list[str]  # this month's boosted topics


def day_focus(session: Session, now: datetime | None = None) -> DayFocus:
    """What leads Today: the weekday's kind from the rhythm, in the light of this month's block."""
    today = stats.local_date(now)
    kind = rhythm(session)[today.weekday()]
    k = DAY_KINDS[kind]
    month = current_month(session, now)
    why = k.why
    if month is not None and month.title and kind in ("grammar", "interleaved"):
        why = f"{k.why} This month: {month.title.lower()}."
    return DayFocus(WEEKDAYS[today.weekday()], kind, k.title, why, k.href,
                    month.title if month else "", list(month.topics_json or []) if month else [])


# --- Months ------------------------------------------------------------------------------------

def _trip_date(session: Session) -> date | None:
    row = session.get(Setting, "trip_date")
    try:
        return date.fromisoformat(str(row.value)) if row is not None and row.value else None
    except ValueError:
        return None


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def month_starts(trip: date) -> list[date]:
    """First days of the twelve months ending in the trip month."""
    last = date(trip.year, trip.month, 1)
    return [_add_months(last, i - (PLAN_MONTHS - 1)) for i in range(PLAN_MONTHS)]


def seed(session: Session, now: datetime | None = None) -> list[PlanMonth]:
    """Create or refresh the twelve months from the trip date and the arc. Keeps check-ins.
    Re-anchors when the trip date changes. Returns the months in order (empty without a trip date)."""
    trip = _trip_date(session)
    if trip is None:
        return []
    starts = month_starts(trip)
    existing = {m.month_idx: m for m in session.exec(select(PlanMonth)).all()}
    for idx, (start, block) in enumerate(zip(starts, ARC), start=1):
        m = existing.get(idx) or PlanMonth(month_idx=idx, start_date=start, focus="")
        if m.start_date != start:
            m.review_json = None  # a re-anchored month is a different month
        m.start_date = start
        m.title = block["title"]
        m.focus = block["focus"]
        m.topics_json = list(block["topics"])
        m.goals_json = [{"metric": metric, "target": target, "text": f"{target} {METRICS[metric]}"} for metric, target in block["goals"]]
        session.add(m)
    session.commit()
    _refresh_status(session, now)
    return months(session)


def months(session: Session) -> list[PlanMonth]:
    return list(session.exec(select(PlanMonth).order_by(col(PlanMonth.month_idx))).all())


def month_range(m: PlanMonth) -> tuple[date, date]:
    """[start, end) of a plan month."""
    return m.start_date, _add_months(m.start_date, 1)


def current_month(session: Session, now: datetime | None = None) -> PlanMonth | None:
    today = stats.local_date(now)
    for m in months(session):
        start, end = month_range(m)
        if start <= today < end:
            return m
    return None


def _refresh_status(session: Session, now: datetime | None) -> None:
    today = stats.local_date(now)
    for m in months(session):
        start, end = month_range(m)
        status = "done" if end <= today else "current" if start <= today else "planned"
        if m.status != status:
            m.status = status
            session.add(m)
    session.commit()


# --- Progress -------------------------------------------------------------------------------------

def _utc_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """Local-date range to UTC datetimes (the app stores UTC)."""
    tz = datetime.now().astimezone().tzinfo
    return (datetime.combine(start, time.min, tz).astimezone(timezone.utc),
            datetime.combine(end, time.min, tz).astimezone(timezone.utc))


def metric_value(session: Session, metric: str, start: date, end: date) -> int:
    """A goal metric counted over local dates [start, end)."""
    lo, hi = _utc_bounds(start, end)
    count = lambda q: int(session.exec(q).one() or 0)  # noqa: E731
    if metric == "cards_added":
        return count(select(func.count()).select_from(Card).where(Card.created_at >= lo, Card.created_at < hi))
    if metric == "reviews":
        return count(select(func.count()).select_from(ReviewLog).where(ReviewLog.reviewed_at >= lo, ReviewLog.reviewed_at < hi))
    if metric == "drill_sets":
        return count(select(func.count()).select_from(DrillSet).where(DrillSet.completed_at >= lo, DrillSet.completed_at < hi))
    if metric == "stories":
        return count(select(func.count()).select_from(TranslationAttempt).where(
            TranslationAttempt.created_at >= lo, TranslationAttempt.created_at < hi, col(TranslationAttempt.feedback_json).is_not(None)))
    if metric == "roleplays":
        return count(select(func.count()).select_from(Conversation).where(Conversation.ended_at >= lo, Conversation.ended_at < hi))
    if metric == "input_minutes":
        return count(select(func.coalesce(func.sum(InputLog.minutes), 0)).where(InputLog.date >= start, InputLog.date < end))
    if metric == "study_days":
        return count(select(func.count(func.distinct(StudySession.date))).where(
            StudySession.completed == True, StudySession.date >= start, StudySession.date < end))  # noqa: E712
    raise ValueError(f"Unknown metric {metric!r}")


@dataclass(frozen=True)
class GoalProgress:
    text: str
    metric: str
    target: int
    value: int

    @property
    def done(self) -> bool:
        return self.value >= self.target

    @property
    def ratio(self) -> float:
        return min(1.0, self.value / self.target) if self.target else 1.0


def progress(session: Session, month: PlanMonth) -> list[GoalProgress]:
    start, end = month_range(month)
    return [GoalProgress(g["text"], g["metric"], int(g["target"]), metric_value(session, g["metric"], start, end))
            for g in month.goals_json or []]


def expected_ratio(month: PlanMonth, now: datetime | None = None) -> float:
    """How far through the month today is (0-1), for "on track" comparisons."""
    start, end = month_range(month)
    today = stats.local_date(now)
    total = (end - start).days
    return max(0.0, min(1.0, ((today - start).days + 1) / total)) if total else 1.0


def save_review(session: Session, month: PlanMonth, rating: int, notes: str, now: datetime | None = None) -> PlanMonth:
    """The end-of-month check-in: a 1-5 rating of how it went, free notes, and which goals were met."""
    if not 1 <= rating <= 5:
        raise ValueError("Rating must be 1 to 5")
    met = [i for i, g in enumerate(progress(session, month)) if g.done]
    month.review_json = {"rating": rating, "notes": notes.strip(), "goals_met": met,
                         "at": (now or datetime.now(timezone.utc)).isoformat()}
    session.add(month)
    session.commit()
    return month


def review_due(session: Session, now: datetime | None = None) -> PlanMonth | None:
    """The month to check in on: the current month in its last 3 days, or the previous month if it
    ended without a check-in (within the first 10 days of the next)."""
    today = stats.local_date(now)
    for m in months(session):
        start, end = month_range(m)
        if m.review_json:
            continue
        if start <= today < end and (end - today).days <= 3:
            return m
        if end <= today < end + timedelta(days=10):
            return m
    return None


def month_topic_boosts(session: Session, now: datetime | None = None) -> set[str]:
    """Weakness topics this month's block boosts in drill selection."""
    month = current_month(session, now)
    return set(month.topics_json or []) if month else set()

"""Guided-learning units (P5): curriculum, progress, mastery, revisits and adaptation.

The API the pages, the exercise player and Today build on. Design: docs/guided-learning.md.

Routes (owned by the lanes, listed here so links agree):
  /learn                                  unit map by month + the current unit       (Lane B)
  /learn/{unit_id}                        unit page: steps checklist, story prompt   (Lane B)
  /learn/{unit_id}/lesson                 the lesson                                  (Lane B)
  /learn/{unit_id}/play/{kind}?variant=N  exercise player for an item set             (Lane A)
Story and role-play steps link out to /workshop/new and the unit's scenario.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel
from sqlmodel import Session, col, select

from app.models import Conversation, ExerciseAttempt, Scenario, TopicReview, TranslationAttempt, Unit, UnitContent, UnitProgress
from app.services import plan as plan_service
from app.services import srs, stats
from app.services.exercises import parse_items
from app.services.grammar import CASES, NUMBERS

PASS = 0.80  # quiz pass mark
REMEDIATE_BELOW = 0.60  # under this, a remediation round before retesting
FAST_TRACK = 0.85  # pre-test score that offers skipping to the quiz
REVISIT_PASS = 0.70
REVISIT_LADDER = [3, 7, 21, 60]  # days after passing, then after each passed revisit
SECURE_AFTER = 2  # passed revisits before a topic counts as secure
PRACTICE_SETS = 2  # controlled-practice sets before the quiz unlocks

# Step keys in unit order. "kind" is the content kind an item-set step plays.
STEPS = [
    ("pretest", "Pre-test", "Six quick items: ace them and you can skip ahead"),
    ("learn", "Learn", "The rule, examples with audio, and the unit's words"),
    ("practice", "Practice", "Multiple choice, fill-ins, matching, transformations"),
    ("listening", "Listen", "Hear it and choose the meaning, then dictation"),
    ("story", "Write", "A short story using the unit's words and pattern"),
    ("roleplay", "Speak", "A role-play where the goals need this topic"),
    ("quiz", "Quiz", "Ten to twelve mixed items; pass at 80%"),
]
ITEM_KINDS = {"pretest", "practice", "listening", "quiz", "remediation", "revisit"}

# --- Curriculum ---------------------------------------------------------------------------------

CURRICULUM = [
    # Month 1: Cases in everyday speech
    dict(id="u01-where-you-are", month_idx=1, order=1, level="A2", title="Where you are: в and на + prepositional",
         topics=[f"{CASES}#prepositional", f"{CASES}#prepositional-locative"], vocab_theme="places in the city",
         can_do="Say where you are and where things are: at the station, in the hotel, on the square.",
         scenario_slug="directions", roleplay_goal="Say where you are right now and where the hotel is"),
    dict(id="u02-where-to", month_idx=1, order=2, level="A2", title="Where you're going: в and на + accusative",
         topics=[f"{CASES}#location-direction", f"{CASES}#accusative"], vocab_theme="destinations and getting there",
         can_do="Tell a driver or a friend where you're going, and tell where from where to apart.",
         scenario_slug="taxi", roleplay_goal="Give the destination with в or на", prereqs=["u01-where-you-are"]),
    dict(id="u03-buy-and-see", month_idx=1, order=3, level="A2", title="Things you buy and see: the accusative",
         topics=[f"{CASES}#accusative", f"{CASES}#animate-accusative"], vocab_theme="shopping, food and people you see",
         can_do="Order, buy and ask for things; say who you see or meet.",
         scenario_slug="market", roleplay_goal="Ask for two things by name"),
    dict(id="u04-around-town", month_idx=1, order=4, level="B1", title="Consolidation: a day around town",
         topics=[f"{CASES}#prepositional", f"{CASES}#location-direction", f"{CASES}#accusative"], vocab_theme="a day out in Moscow",
         can_do="Plan and talk through a day around town without mixing up where and where to.",
         scenario_slug="metro", roleplay_goal="Say where you're going and where you'll change lines",
         prereqs=["u01-where-you-are", "u02-where-to", "u03-buy-and-see"]),
    # Month 2: The genitive everywhere
    dict(id="u05-there-is-no", month_idx=2, order=1, level="A2", title="Nothing and no one: нет + genitive",
         topics=[f"{CASES}#genitive"], vocab_theme="things that run out or go missing",
         can_do="Say what there isn't or what you don't have: no tickets, no change, no time.",
         scenario_slug="train", roleplay_goal="Cope when there are no tickets for your train"),
    dict(id="u06-from-until-without", month_idx=2, order=2, level="B1", title="From, until, without: из, до, у, без",
         topics=[f"{CASES}#genitive", f"{CASES}#prepositions"], vocab_theme="origins, distances and conditions",
         can_do="Say where you're from, how far it is, and what you want without.",
         scenario_slug="pharmacy", roleplay_goal="Ask for something without a prescription", prereqs=["u05-there-is-no"]),
    dict(id="u07-prices", month_idx=2, order=3, level="A2", title="Prices and numbers: 1, 2-4, 5+",
         topics=[f"{NUMBERS}#numbers-rule"], vocab_theme="money, prices and quantities",
         can_do="Understand and say prices, counts and times with the right noun form.",
         scenario_slug="souvenirs", roleplay_goal="Ask the price and say how many you want"),
    dict(id="u08-many-and-few", month_idx=2, order=4, level="B1", title="Many and few: the genitive plural",
         topics=[f"{CASES}#genitive-plural"], vocab_theme="quantities at the market and the café",
         can_do="Say how much or how many with много, ма́ло, ско́лько and numbers 5 and up.",
         scenario_slug="cafe", roleplay_goal="Order for several people", prereqs=["u07-prices"]),
]


def seed_curriculum(session: Session) -> None:
    """Insert or refresh the curriculum (idempotent; progress is kept)."""
    existing = {u.id: u for u in session.exec(select(Unit)).all()}
    for d in CURRICULUM:
        u = existing.get(d["id"]) or Unit(id=d["id"], month_idx=d["month_idx"], title=d["title"])
        u.month_idx, u.order, u.level, u.title = d["month_idx"], d["order"], d["level"], d["title"]
        u.topics_json, u.vocab_theme, u.can_do = list(d["topics"]), d["vocab_theme"], d["can_do"]
        u.prereqs_json = list(d.get("prereqs", []))
        u.scenario_slug, u.roleplay_goal = d.get("scenario_slug", ""), d.get("roleplay_goal", "")
        session.add(u)
    session.commit()


def units(session: Session) -> list[Unit]:
    return list(session.exec(select(Unit).order_by(col(Unit.month_idx), col(Unit.order))).all())


def units_for_month(session: Session, month_idx: int) -> list[Unit]:
    return [u for u in units(session) if u.month_idx == month_idx]


def progress(session: Session, unit: Unit) -> UnitProgress:
    """The unit's progress row (an unsaved fresh one when not started)."""
    return session.get(UnitProgress, unit.id) or UnitProgress(unit_id=unit.id)


def current_unit(session: Session, now: datetime | None = None) -> Unit | None:
    """The unit to work on: the first unfinished unit in plan order up to and including this month,
    or the next month's first unit when everything due is done (working ahead)."""
    month = plan_service.current_month(session, now)
    limit = month.month_idx if month else 1
    unfinished = [u for u in units(session) if progress(session, u).status in ("not_started", "active", "remediation")]
    due = [u for u in unfinished if u.month_idx <= limit]
    return (due or unfinished or [None])[0]


# --- Content ------------------------------------------------------------------------------------

class Example(BaseModel):
    ru: str
    en: str


class Lesson(BaseModel):
    title: str
    intro: str  # two or three sentences: why this matters on the trip
    rule_points: list[str]  # short English points, may contain «Russian» in guillemets
    examples: list[Example]  # 4-6, stress-marked
    notice_ru: str  # a short text containing the pattern several times
    notice_task: str  # what to look for in it
    words: list[Example]  # the unit's 10-15 words or phrases, stress-marked


def cached(session: Session, unit_id: str, kind: str, variant: int = 0) -> dict | None:
    row = session.exec(select(UnitContent).where(
        UnitContent.unit_id == unit_id, UnitContent.kind == kind, UnitContent.variant == variant)).first()
    return row.body_json if row else None


def store(session: Session, unit_id: str, kind: str, variant: int, body: dict) -> None:
    row = session.exec(select(UnitContent).where(
        UnitContent.unit_id == unit_id, UnitContent.kind == kind, UnitContent.variant == variant)).first()
    row = row or UnitContent(unit_id=unit_id, kind=kind, variant=variant, body_json={})
    row.body_json = body
    session.add(row)
    session.commit()


def get_lesson(session: Session, unit: Unit, client=None) -> Lesson:
    """The unit's lesson, generated once and cached. `client`: a ClaudeClient (or fake)."""
    body = cached(session, unit.id, "lesson")
    if body is None:
        from app.services import unit_content
        body = unit_content.generate_lesson(session, unit, client).model_dump()
        store(session, unit.id, "lesson", 0, body)
    return Lesson(**body)


def get_items(session: Session, unit: Unit, kind: str, variant: int = 0, client=None) -> tuple[str, list]:
    """(title, items) for an item-set step, generated once and cached per (kind, variant)."""
    if kind not in ITEM_KINDS:
        raise ValueError(f"Unknown item set kind {kind!r}")
    body = cached(session, unit.id, kind, variant)
    if body is None:
        from app.services import unit_content
        try:
            item_set = unit_content.generate_items(session, unit, kind, variant, client)
        except NotImplementedError:  # before generation exists: reuse a cached set (demo content)
            body = cached(session, unit.id, kind, 0) or cached(session, unit.id, "practice", 0)
            if body is None:
                raise
        else:
            body = item_set.model_dump()
            store(session, unit.id, kind, variant, body)
    return body.get("title", ""), parse_items(body["items"])


def story_prompt(unit: Unit) -> str:
    return (f"Write 5 to 8 sentences in Russian about {unit.vocab_theme}, using the pattern from this unit "
            f"({unit.title.lower()}). Fix what you can yourself before you look at the corrections.")


# --- Progress -----------------------------------------------------------------------------------

def _now(now: datetime | None) -> datetime:
    return srs._utc(now or datetime.now(timezone.utc))


def start(session: Session, unit: Unit, now: datetime | None = None) -> UnitProgress:
    p = progress(session, unit)
    if p.status == "not_started":
        p.status, p.started_at = "active", _now(now)
        session.add(p)
        session.commit()
    return p


def record_attempt(session: Session, unit: Unit, kind: str, variant: int, item, answer: str, correct: bool,
                   attempt: int = 1, now: datetime | None = None) -> None:
    session.add(ExerciseAttempt(unit_id=unit.id, kind=kind, variant=variant, item_id=item.id, item_type=item.type,
                                topic=item.topic, skill=item.skill, answer=answer, correct=correct, attempt=attempt,
                                created_at=_now(now)))
    session.commit()


def _step_key(kind: str, variant: int) -> str:
    return f"{kind}:{variant}" if kind in ("practice", "remediation") else kind


@dataclass
class FinishResult:
    kind: str
    score: float
    outcome: str  # done, fast_track_offered, passed, retry_practice, remediation, revisit_passed, revisit_failed
    message: str


def finish_step(session: Session, unit: Unit, kind: str, score: float, variant: int = 0,
                now: datetime | None = None) -> FinishResult:
    """Record a finished step (score 0-1 for item sets; 1.0 for self-reported steps) and apply the
    adaptation rules. Returns what happens next."""
    now = _now(now)
    p = start(session, unit, now)
    steps = dict(p.steps_json or {})
    steps[_step_key(kind, variant)] = {"done_at": now.isoformat(), "score": round(score, 3)}
    p.steps_json = steps
    result = FinishResult(kind, score, "done", "Step done.")
    if kind == "pretest":
        p.pretest_score = score
        if score >= FAST_TRACK:
            result = FinishResult(kind, score, "fast_track_offered",
                                  f"{round(score * 100)}%: you know this already. Skip to the quiz, or work through the unit anyway.")
    elif kind == "quiz":
        p.quiz_attempts += 1
        p.quiz_score = max(p.quiz_score or 0.0, score)
        if score >= PASS:
            p.status, p.passed_at = "passed", now
            _schedule_revisit(session, unit, 0, now)
            result = FinishResult(kind, score, "passed", f"Passed with {round(score * 100)}%. This topic comes back for review in {REVISIT_LADDER[0]} days.")
        elif score < REMEDIATE_BELOW:
            p.status = "remediation"
            result = FinishResult(kind, score, "remediation",
                                  f"{round(score * 100)}%. A remediation round comes next: a different explanation and practice on what you missed, then the quiz again.")
        else:
            p.status = "active"
            result = FinishResult(kind, score, "retry_practice",
                                  f"{round(score * 100)}%, close. One more practice set, then try the quiz again.")
    elif kind == "remediation":
        p.status = "active"
        result = FinishResult(kind, score, "done", "Remediation done. The quiz is open again: take it when you're ready.")
    elif kind == "revisit":
        result = _finish_revisit(session, unit, p, score, now)
    p.mastery = mastery(session, unit, p)
    session.add(p)
    session.commit()
    return result


def fast_track(session: Session, unit: Unit, now: datetime | None = None) -> UnitProgress:
    """Accept the pre-test's offer: skip straight to the quiz."""
    p = start(session, unit, now)
    if (p.pretest_score or 0) < FAST_TRACK:
        raise ValueError("Fast-track needs a pre-test score of 85% or more")
    steps = dict(p.steps_json or {})
    steps["fast_track"] = {"done_at": _now(now).isoformat(), "score": p.pretest_score}
    p.steps_json = steps
    session.add(p)
    session.commit()
    return p


def _schedule_revisit(session: Session, unit: Unit, step: int, now: datetime) -> None:
    r = session.get(TopicReview, unit.id) or TopicReview(unit_id=unit.id, due=stats.local_date(now))
    r.step = step
    r.due = stats.local_date(now) + timedelta(days=REVISIT_LADDER[min(step, len(REVISIT_LADDER) - 1)])
    session.add(r)


def _finish_revisit(session: Session, unit: Unit, p: UnitProgress, score: float, now: datetime) -> FinishResult:
    r = session.get(TopicReview, unit.id)
    if r is None:
        return FinishResult("revisit", score, "done", "Revisit done.")
    r.last_result = score
    if score >= REVISIT_PASS:
        passed = sum(1 for k in (p.steps_json or {}) if k.startswith("revisit_ok"))
        p.steps_json = {**(p.steps_json or {}), f"revisit_ok:{passed + 1}": {"done_at": now.isoformat(), "score": score}}
        if passed + 1 >= SECURE_AFTER:
            p.status = "secure"
        r.flagged = False
        _schedule_revisit(session, unit, r.step + 1, now)
        session.add(r)
        return FinishResult("revisit", score, "revisit_passed", f"{round(score * 100)}%. Next review in {(r.due - stats.local_date(now)).days} days.")
    r.flagged = True
    if p.status == "secure":
        p.status = "passed"
    _schedule_revisit(session, unit, 0, now)
    session.add(r)
    return FinishResult("revisit", score, "revisit_failed", f"{round(score * 100)}%. This topic comes back sooner, in {REVISIT_LADDER[0]} days.")


def revisits_due(session: Session, now: datetime | None = None) -> list[Unit]:
    today = stats.local_date(now)
    due_ids = [r.unit_id for r in session.exec(select(TopicReview).where(TopicReview.due <= today).order_by(col(TopicReview.due))).all()]
    by_id = {u.id: u for u in units(session)}
    return [by_id[i] for i in due_ids if i in by_id]


def _first_try_accuracy(session: Session, unit: Unit) -> float | None:
    rows = session.exec(select(ExerciseAttempt.correct).where(
        ExerciseAttempt.unit_id == unit.id, ExerciseAttempt.attempt == 1,
        col(ExerciseAttempt.kind).in_(["practice", "listening", "remediation"]))).all()
    return sum(rows) / len(rows) if rows else None


def mastery(session: Session, unit: Unit, p: UnitProgress | None = None) -> float:
    """0-1: half the best quiz, three tenths first-try practice accuracy, a fifth the latest revisit
    (missing parts fall back to what exists)."""
    p = p or progress(session, unit)
    parts: list[tuple[float, float]] = []
    if p.quiz_score is not None:
        parts.append((0.5, p.quiz_score))
    acc = _first_try_accuracy(session, unit)
    if acc is not None:
        parts.append((0.3, acc))
    r = session.get(TopicReview, unit.id)
    if r is not None and r.last_result is not None:
        parts.append((0.2, r.last_result))
    if not parts:
        return 0.0
    return round(sum(w * v for w, v in parts) / sum(w for w, _ in parts), 3)


# --- What the learner sees ----------------------------------------------------------------------

@dataclass
class StepState:
    key: str  # pretest, learn, practice, listening, story, roleplay, quiz, remediation
    title: str
    why: str
    status: str  # locked, available, done, skipped
    href: str
    kind: str = ""  # item-set kind to play, if any
    variant: int = 0
    score: float | None = None


@dataclass
class UnitState:
    unit: Unit
    status: str
    mastery: float
    steps: list[StepState] = field(default_factory=list)
    fast_track_offer: bool = False
    message: str = ""


def _done(p: UnitProgress, key: str) -> dict | None:
    return (p.steps_json or {}).get(key)


def _auto_done(session: Session, unit: Unit, p: UnitProgress, key: str) -> bool:
    """Story and role-play count as done when the learner did them after starting the unit."""
    if p.started_at is None:
        return False
    since = srs._utc(p.started_at)
    if key == "story":
        rows = session.exec(select(TranslationAttempt.created_at).where(col(TranslationAttempt.feedback_json).is_not(None))).all()
        return any(srs._utc(t) >= since for t in rows)
    if key == "roleplay" and unit.scenario_slug:
        sc = session.exec(select(Scenario).where(Scenario.slug == unit.scenario_slug)).first()
        if sc is None:
            return False
        ended = session.exec(select(Conversation.ended_at).where(Conversation.scenario_id == sc.id, col(Conversation.ended_at).is_not(None))).all()
        return any(srs._utc(t) >= since for t in ended)
    return False


def state(session: Session, unit: Unit, now: datetime | None = None) -> UnitState:
    p = progress(session, unit)
    fast = bool(_done(p, "fast_track"))
    learned = bool(_done(p, "learn")) or fast
    practice_done = [bool(_done(p, f"practice:{v}")) for v in range(PRACTICE_SETS + 1)]
    out: list[StepState] = []
    for key, title, why in STEPS:
        base = f"/learn/{unit.id}"
        if key == "pretest":
            d = _done(p, "pretest")
            out.append(StepState(key, title, why, "done" if d else "available", f"{base}/play/pretest", "pretest", 0, d and d["score"]))
        elif key == "learn":
            out.append(StepState(key, title, why, "skipped" if fast and not _done(p, "learn") else "done" if learned else "available", f"{base}/lesson"))
        elif key == "practice":
            for v in range(PRACTICE_SETS):
                d = _done(p, f"practice:{v}")
                status = "skipped" if fast and not d else "done" if d else "available" if learned and (v == 0 or practice_done[v - 1]) else "locked"
                out.append(StepState(key, f"{title} {v + 1}", why, status, f"{base}/play/practice?variant={v}", "practice", v, d and d["score"]))
            if p.status == "active" and (p.quiz_score or 0) >= REMEDIATE_BELOW and (p.quiz_score or 0) < PASS:
                d = _done(p, f"practice:{PRACTICE_SETS}")
                out.append(StepState(key, f"{title}: one more set", "A further practice set before retrying the quiz",
                                     "done" if d else "available", f"{base}/play/practice?variant={PRACTICE_SETS}", "practice", PRACTICE_SETS, d and d["score"]))
        elif key == "listening":
            d = _done(p, "listening")
            out.append(StepState(key, title, why, "skipped" if fast and not d else "done" if d else "available" if learned else "locked",
                                 f"{base}/play/listening", "listening", 0, d and d["score"]))
        elif key in ("story", "roleplay"):
            d = _done(p, key) or (_auto_done(session, unit, p, key) and {"score": 1.0})
            href = "/workshop/new" if key == "story" else (f"/scenarios/{unit.scenario_slug}" if unit.scenario_slug else "/scenarios")
            out.append(StepState(key, title, why, "skipped" if fast and not d else "done" if d else "available" if practice_done[0] else "locked", href))
        elif key == "quiz":
            if p.status == "remediation":
                v = p.quiz_attempts
                out.append(StepState("remediation", "Remediation", "A different explanation and practice on what you missed",
                                     "available", f"{base}/play/remediation?variant={v}", "remediation", v))
            extra_needed = any(s.key == "practice" and s.variant == PRACTICE_SETS and s.status != "done" for s in out)
            unlocked = (fast or all(practice_done[:PRACTICE_SETS])) and p.status != "remediation" and not extra_needed
            d = _done(p, "quiz")
            status = "done" if p.status in ("passed", "secure") else "available" if unlocked else "locked"
            out.append(StepState(key, title, why, status, f"{base}/play/quiz?variant={p.quiz_attempts}", "quiz", p.quiz_attempts, p.quiz_score))
    offer = (p.pretest_score or 0) >= FAST_TRACK and not fast and p.status not in ("passed", "secure")
    return UnitState(unit, p.status, p.mastery, out, offer)


# --- Today ----------------------------------------------------------------------------------------

DAY_STEP = {  # weekly-rhythm day kind -> preferred step keys, in order
    "grammar": ["learn", "practice"],
    "interleaved": ["practice", "listening"],
    "writing": ["story"],
    "translation": ["story", "practice"],
    "roleplay": ["roleplay"],
    "input": ["listening"],
    "light": [],
}


@dataclass
class TodayStep:
    unit: Unit | None
    step: StepState | None
    revisits: list[Unit]
    why: str


def today_step(session: Session, now: datetime | None = None) -> TodayStep:
    """The unit step that leads Today: the rhythm's preferred step if available, otherwise the next
    available step in unit order. Light days lead with revisits."""
    revisits = revisits_due(session, now)
    unit = current_unit(session, now)
    if unit is None:
        return TodayStep(None, None, revisits, "")
    st = state(session, unit, now)
    kind = plan_service.day_focus(session, now).kind
    available = [s for s in st.steps if s.status == "available"]
    for key in DAY_STEP.get(kind, []):
        match = next((s for s in available if s.key == key), None)
        if match:
            return TodayStep(unit, match, revisits, f"{plan_service.DAY_KINDS[kind].title} day")
    if kind == "light":
        return TodayStep(unit, None, revisits, "Light day: revisits and reviews only")
    first = next((s for s in available if s.key != "pretest" or not _done(progress(session, unit), "pretest")), None)
    return TodayStep(unit, first, revisits, "Next step in your unit")


# --- Preparing content ahead ----------------------------------------------------------------------

PREFETCH_KINDS = [("lesson", 0), ("pretest", 0), ("practice", 0), ("practice", 1), ("listening", 0), ("quiz", 0)]


def prefetch(session: Session, unit: Unit, client=None) -> int:
    """Generate any of the unit's standard content that isn't cached yet. Returns how many sets were made."""
    made = 0
    for kind, variant in PREFETCH_KINDS:
        if cached(session, unit.id, kind, variant) is not None:
            continue
        if kind == "lesson":
            get_lesson(session, unit, client)
        else:
            get_items(session, unit, kind, variant, client)
        made += 1
    return made


def prefetch_upcoming(session: Session, now: datetime | None = None, client=None) -> int:
    """Prepare the current unit and the one after it, so opening them never waits on Claude."""
    current = current_unit(session, now)
    if current is None:
        return 0
    ordered = units(session)
    i = next(k for k, u in enumerate(ordered) if u.id == current.id)
    made = 0
    for unit in ordered[i:i + 2]:
        made += prefetch(session, unit, client)
    return made


def start_prefetch_loop(interval_seconds: int = 600) -> None:
    """Background thread for the running app (not tests): every few minutes, prepare upcoming units."""
    import logging
    import threading
    import time

    from app.db import get_engine

    log = logging.getLogger("units.prefetch")

    def loop():
        while True:
            try:
                with Session(get_engine()) as session:
                    made = prefetch_upcoming(session)
                    if made:
                        log.info("prepared %d content sets for upcoming units", made)
            except Exception as e:  # Claude busy or offline: try again next round
                log.warning("unit prefetch skipped: %s", e)
            time.sleep(interval_seconds)

    threading.Thread(target=loop, name="unit-prefetch", daemon=True).start()

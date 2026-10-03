"""Tutor lessons: lessons, word lists, tasks, questions and the pre-lesson summary (Phase 6).

All dates are local calendar dates (`stats.local_date`); services take `now` where time matters.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from app.models import Card, Lesson, Mistake, Module, ReviewLog, TutorQuestion, TutorTask
from app.models import Session as StudySession
from app.services import cards as cards_svc
from app.services import srs, stats
from app.services.claude import Task

TUTOR_TAG = "tutor"
LESSON_FIELDS = ("topic", "date", "goals", "materials", "notes")


# ---------------------------------------------------------------- lessons (feature 1)

def _clean_goals(goals) -> list[str]:
    return [g.strip() for g in (goals or []) if g and g.strip()]


def _clean_materials(materials) -> list[dict]:
    cleaned = []
    for m in materials or []:
        url = (m.get("url") or "").strip()
        if not re.match(r"https?://\S", url, re.I):
            raise ValueError(f"Material links must start with http:// or https:// ({url or 'empty link'})")
        cleaned.append({"title": (m.get("title") or "").strip() or url, "url": url})
    return cleaned


def _clean_topic(topic: str) -> str:
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("A lesson needs a topic")
    return topic


def create_lesson(session: Session, date: date, topic: str, goals: list[str] = (), materials: list[dict] = (),
                  notes: str = "") -> Lesson:
    lesson = Lesson(date=date, topic=_clean_topic(topic), goals_json=_clean_goals(goals),
                    materials_json=_clean_materials(materials), notes=(notes or "").strip())
    session.add(lesson)
    session.commit()
    session.refresh(lesson)
    return lesson


def get_lesson(session: Session, lesson_id: int) -> Lesson | None:
    return session.get(Lesson, lesson_id)


def list_lessons(session: Session) -> list[Lesson]:
    """Newest date first, then newest id first."""
    return list(session.exec(select(Lesson).order_by(col(Lesson.date).desc(), col(Lesson.id).desc())).all())


def update_lesson(session: Session, lesson_id: int, **fields) -> Lesson:
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise ValueError("No such lesson")
    unknown = set(fields) - set(LESSON_FIELDS)
    if unknown:
        raise ValueError(f"Unknown lesson fields: {', '.join(sorted(unknown))}")
    # Validate everything before changing anything.
    new = {}
    if "topic" in fields:
        new["topic"] = _clean_topic(fields["topic"])
    if "date" in fields:
        new["date"] = fields["date"]
    if "goals" in fields:
        new["goals_json"] = _clean_goals(fields["goals"])
    if "materials" in fields:
        new["materials_json"] = _clean_materials(fields["materials"])
    if "notes" in fields:
        new["notes"] = (fields["notes"] or "").strip()
    for name, value in new.items():
        setattr(lesson, name, value)
    session.add(lesson)
    session.commit()
    session.refresh(lesson)
    return lesson


def current_lesson(session: Session, now: datetime) -> Lesson | None:
    """The latest lesson dated on or before today."""
    today = stats.local_date(now)
    return session.exec(select(Lesson).where(Lesson.date <= today)
                        .order_by(col(Lesson.date).desc(), col(Lesson.id).desc())).first()


def next_lesson(session: Session, now: datetime) -> Lesson | None:
    """The earliest lesson dated today or later."""
    today = stats.local_date(now)
    return session.exec(select(Lesson).where(Lesson.date >= today)
                        .order_by(col(Lesson.date), col(Lesson.id))).first()


def parse_materials(text: str) -> list[dict]:
    """One per line: `title | url` or just `url`."""
    items = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if re.match(r"https?://", line, re.I) or "|" not in line:
            items.append({"title": "", "url": line})
        else:
            title, _, url = line.partition("|")
            items.append({"title": title.strip(), "url": url.strip()})
    return items


def parse_goals(text: str) -> list[str]:
    return _clean_goals((text or "").splitlines())


def lesson_counts(session: Session, lessons: list[Lesson]) -> dict[int, tuple[int, int]]:
    """lesson id -> (words added, open tasks)."""
    ids = [lesson.id for lesson in lessons]
    if not ids:
        return {}
    words = Counter(session.exec(select(Card.source_ref_id).where(
        Card.source_module == Module.tutor, col(Card.source_ref_id).in_(ids))).all())
    tasks = Counter(session.exec(select(TutorTask.lesson_id).where(
        col(TutorTask.lesson_id).in_(ids), col(TutorTask.done_at).is_(None))).all())
    return {i: (words[i], tasks[i]) for i in ids}


def lesson_words(session: Session, lesson_id: int) -> list[Card]:
    return list(session.exec(select(Card).where(Card.source_module == Module.tutor, Card.source_ref_id == lesson_id)
                             .order_by(col(Card.id))).all())


def lesson_tasks(session: Session, lesson_id: int) -> list[TutorTask]:
    """Open tasks first (by due date), then done ones."""
    rows = session.exec(select(TutorTask).where(TutorTask.lesson_id == lesson_id)
                        .order_by(col(TutorTask.due), col(TutorTask.id))).all()
    return sorted(rows, key=lambda t: t.done_at is not None)


# ---------------------------------------------------------------- word lists (feature 3)

@dataclass
class WordItem:
    ru: str
    en: str


_SEPARATORS = ("—", "–", " - ", ":", "\t")


def parse_word_list(text: str) -> tuple[list[WordItem], list[str]]:
    """One word per line: `russian <sep> english`. The leftmost separator wins; a bare hyphen is not one."""
    items: list[WordItem] = []
    errors: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        hits = [(line.find(sep), sep) for sep in _SEPARATORS if sep in line]
        if not hits:
            errors.append(f"No separator in “{line}” (use a dash, a colon or a tab between the Russian and the English)")
            continue
        pos, sep = min(hits)
        ru, en = line[:pos].strip(), line[pos + len(sep):].strip()
        if not ru or not en:
            errors.append(f"Both a Russian word and its English meaning are needed in “{line}”")
            continue
        items.append(WordItem(ru=ru, en=en))
    return items, errors


def add_words(session: Session, lesson_id: int, items: list[dict]) -> list[Card]:
    """Create a card per item (already filtered to the ticked ones). Existing words are skipped."""
    made: list[Card] = []
    for item in items:
        ru = (item.get("ru") or "").strip()
        en = (item.get("en") or "").strip()
        if not ru or not en or cards_svc.find_duplicate(session, ru):
            continue
        fields = {name: item.get(name) or "" for name in (
            "ru_stressed", "example_ru", "example_en", "notes", "pos", "gender", "aspect", "aspect_partner")}
        made.append(cards_svc.create_card(
            session, ru=ru, en=en, tags=TUTOR_TAG, source_module=Module.tutor, source_ref_id=lesson_id, **fields))
    return made


# ---------------------------------------------------------------- tasks (feature 4)

def add_task(session: Session, title: str, due: date, lesson_id: int | None = None) -> TutorTask:
    title = (title or "").strip()
    if not title:
        raise ValueError("A task needs a title")
    task = TutorTask(title=title, due=due, lesson_id=lesson_id)
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def complete_task(session: Session, task_id: int, now: datetime) -> TutorTask:
    task = session.get(TutorTask, task_id)
    if task is None:
        raise ValueError("No such task")
    if task.done_at is None:
        task.done_at = srs._utc(now)
        session.add(task)
        session.commit()
        session.refresh(task)
    return task


def open_tasks(session: Session) -> list[TutorTask]:
    return list(session.exec(select(TutorTask).where(col(TutorTask.done_at).is_(None))
                             .order_by(col(TutorTask.due), col(TutorTask.id))).all())


def tasks_for_today(session: Session, now: datetime) -> list[TutorTask]:
    """Open tasks that are overdue, due today, or due within the next 2 days."""
    last = stats.local_date(now) + timedelta(days=2)
    return [t for t in open_tasks(session) if t.due <= last]


def due_label(due: date, today: date) -> str:
    """'overdue', 'today', 'tomorrow' or the full weekday name."""
    days = (due - today).days
    if days < 0:
        return "overdue"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return due.strftime("%A")


# ---------------------------------------------------------------- this week (feature 5)

@dataclass
class ThisWeek:
    topic: str | None
    goals: list[str] = field(default_factory=list)
    next_lesson_date: date | None = None
    days_until_next: int | None = None


def this_week(session: Session, now: datetime) -> ThisWeek:
    current = current_lesson(session, now)
    upcoming = next_lesson(session, now)
    return ThisWeek(
        topic=current.topic if current else None,
        goals=current.goals if current else [],
        next_lesson_date=upcoming.date if upcoming else None,
        days_until_next=(upcoming.date - stats.local_date(now)).days if upcoming else None,
    )


def pretty_date(day: date, today: date | None = None) -> str:
    """'Thursday, October 8'; the year is added only when it is not this year."""
    today = today or date.today()
    text = f"{day.strftime('%A, %B')} {day.day}"
    return text if day.year == today.year else f"{text}, {day.year}"


def next_label(days: int) -> str:
    return "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"


# ---------------------------------------------------------------- questions (feature 6)

def add_question(session: Session, text: str, page: str, now: datetime) -> TutorQuestion:
    text = (text or "").strip()
    if not text:
        raise ValueError("Write your question first")
    question = TutorQuestion(text=text, page=(page or "").strip(), created_at=srs._utc(now))
    session.add(question)
    session.commit()
    session.refresh(question)
    return question


def open_questions(session: Session) -> list[TutorQuestion]:
    return list(session.exec(select(TutorQuestion).where(TutorQuestion.asked == False)  # noqa: E712
                             .order_by(col(TutorQuestion.created_at), col(TutorQuestion.id))).all())


def mark_asked(session: Session, question_id: int) -> TutorQuestion:
    question = session.get(TutorQuestion, question_id)
    if question is None:
        raise ValueError("No such question")
    question.asked = True
    session.add(question)
    session.commit()
    session.refresh(question)
    return question


# ---------------------------------------------------------------- pre-lesson summary (feature 7)

@dataclass
class SummaryFacts:
    since: date
    minutes: float
    reviews: int
    new_cards: int
    tutor_cards: int
    top_mistakes: list[str]
    tasks_done: int
    tasks_open: int
    questions: list[str]


class LessonSummaryText(BaseModel):
    summary_ru: str = Field(description="A short summary for the tutor, in Russian, with stress marks (U+0301) on every word of 2+ syllables")
    focus_points: list[str] = Field(description="What to work on next lesson, in English")


@dataclass
class LessonSummary:
    facts: SummaryFacts
    summary_ru: str
    focus_points: list[str]


def summary_facts(session: Session, lesson_id: int, now: datetime) -> SummaryFacts:
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise ValueError("No such lesson")
    previous = session.exec(select(Lesson).where(Lesson.date < lesson.date)
                            .order_by(col(Lesson.date).desc(), col(Lesson.id).desc())).first()
    since = previous.date if previous else stats.local_date(now) - timedelta(days=7)

    def since_ok(moment: datetime | None) -> bool:
        return moment is not None and stats.local_date(moment) >= since

    # Candidate rows come from a loose UTC bound; the local calendar date decides.
    loose = datetime.combine(since - timedelta(days=2), datetime.min.time(), tzinfo=timezone.utc)
    minutes = sum(s.minutes for s in session.exec(
        select(StudySession).where(StudySession.date >= since, StudySession.completed == True)).all())  # noqa: E712
    reviews = sum(1 for r in session.exec(select(ReviewLog.reviewed_at).where(ReviewLog.reviewed_at >= loose)).all()
                  if since_ok(r))
    new = [c for c in session.exec(select(Card).where(Card.created_at >= loose)).all() if since_ok(c.created_at)]
    counts = Counter(m.category for m in session.exec(select(Mistake).where(Mistake.created_at >= loose)).all()
                     if since_ok(m.created_at))
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], getattr(kv[0], "value", kv[0])))[:3]
    tasks = session.exec(select(TutorTask)).all()
    return SummaryFacts(
        since=since,
        minutes=float(minutes),
        reviews=reviews,
        new_cards=len(new),
        tutor_cards=sum(1 for c in new if c.source_module == Module.tutor),
        top_mistakes=[getattr(cat, "value", cat) for cat, _ in ranked],
        tasks_done=sum(1 for t in tasks if since_ok(t.done_at)),
        tasks_open=sum(1 for t in tasks if t.done_at is None),
        questions=[q.text for q in open_questions(session)],
    )


SUMMARY_SYSTEM = """You help an English-speaking intermediate learner of Russian (B1) prepare for a lesson with a tutor.
Write a short summary the learner can read out or send to the tutor: what they did since the last lesson, what is going well,
what is hard, and the questions they want to ask. Write summary_ru in simple, natural Russian (4 to 6 short sentences, first person),
with a stress mark (U+0301) after the stressed vowel of every word of 2+ syllables, never on ё. Use only the facts given;
do not invent numbers. Then give 2 to 4 focus_points in English: what to work on in the next lesson."""


def _summary_prompt(lesson: Lesson, facts: SummaryFacts) -> str:
    lines = [
        f"Lesson topic: {lesson.topic}",
        f"Lesson date: {lesson.date.isoformat()}",
        f"Since: {facts.since.isoformat()} (the previous lesson, or a week ago)",
        f"Study time: {facts.minutes:g} minutes",
        f"Card reviews: {facts.reviews}",
        f"New cards: {facts.new_cards} ({facts.tutor_cards} from tutor lessons)",
        f"Most frequent mistake types: {', '.join(facts.top_mistakes) or 'none logged'}",
        f"Tasks done: {facts.tasks_done}; tasks still open: {facts.tasks_open}",
    ]
    if facts.questions:
        lines.append("Questions for the tutor:")
        lines += [f"- {q}" for q in facts.questions]
    else:
        lines.append("Questions for the tutor: none")
    return "\n".join(lines)


def pre_lesson_summary(session: Session, lesson_id: int, client, now: datetime) -> LessonSummary:
    lesson = session.get(Lesson, lesson_id)
    if lesson is None:
        raise ValueError("No such lesson")
    facts = summary_facts(session, lesson_id, now)
    result = client.ask_structured(Task.lesson_summary, SUMMARY_SYSTEM, _summary_prompt(lesson, facts),
                                   LessonSummaryText, max_tokens=2000)
    return LessonSummary(
        facts=facts,
        summary_ru=cards_svc.fix_latin_accents(result.summary_ru),
        focus_points=list(result.focus_points),
    )


# ---------------------------------------------------------------- redirects

def safe_path(path: str | None, default: str) -> str:
    """A single-slash local path, else `default` (rejects //host, backslashes and control characters)."""
    path = (path or "").strip()
    if (path.startswith("/") and not path.startswith("//") and "\\" not in path
            and not any(ord(c) < 32 for c in path)):
        return path
    return default

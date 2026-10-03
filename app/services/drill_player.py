"""Drill player: answer checking, the two-attempt rule and progress through a set.

Attempt 1 right: counts, and moves the seed mistakes of that topic toward mastery.
Attempt 1 wrong: a hint (topic name and reference link) and one more try, nothing stored.
Attempt 2 right: stored as correct, but self-corrected, so no mastery credit.
Attempt 2 wrong: stored as wrong, logged as a mistake, the answer and rule are revealed.
"""

import re
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, col, select

from app.models import Category, DrillAnswer, DrillSet, Mistake, Module
from app.services import cards, drills, weakness
from app.services.mistakes import RouteResult, log_mistake

BLANK = drills.BLANK
_EDGE = re.compile(r"^[\W_]+|[\W_]+$")  # punctuation, quotes and spaces around the answer


def norm(text: str) -> str:
    """Comparison key: no stress marks (also a stray Latin acute), ё = е, lowercase,
    single spaces, no surrounding punctuation or quotes."""
    text = cards.normalize(cards.fix_latin_accents(text or ""))
    return _EDGE.sub("", text)


def check(item: dict, answer: str) -> bool:
    given = norm(answer)
    if not given:
        return False
    return given in {norm(a) for a in [item.get("answer", ""), *item.get("accepted", [])] if norm(a)}


def fill(item: dict, answer: str | None = None) -> str:
    """The prompt sentence with the blank filled in."""
    return item["prompt_ru"].replace(BLANK, answer if answer is not None else item["answer"])


@dataclass(frozen=True)
class Result:
    idx: int
    attempt: int
    correct: bool
    final: bool  # False: wrong first try, ask again
    empty: bool = False
    credited: bool = False  # first-try correct (counts toward mastery)
    answer: str = ""  # revealed on a final answer
    rule: str = ""
    topic: str = ""
    topic_label: str = ""
    sentence: str = ""


@dataclass(frozen=True)
class Progress:
    total: int
    answered: int
    correct: int
    next_idx: int | None  # None when every item is answered

    @property
    def done(self) -> bool:
        return self.next_idx is None


def _stored(session: Session, drill_set: DrillSet) -> dict[int, DrillAnswer]:
    rows = session.exec(select(DrillAnswer).where(DrillAnswer.drill_set_id == drill_set.id).order_by(col(DrillAnswer.id))).all()
    return {r.item_idx: r for r in rows}


def progress(session: Session, drill_set: DrillSet, now: datetime | None = None) -> Progress:
    stored = _stored(session, drill_set)
    total = len(drill_set.items_json)
    next_idx = next((i for i in range(total) if i not in stored), None)
    result = Progress(total, len(stored), sum(1 for a in stored.values() if a.correct), next_idx)
    if result.done and total and drill_set.completed_at is None:
        drills.complete_set(session, drill_set, now)
    return result


def _item_topic(item: dict) -> str:
    return item.get("topic") or ""


def _seed_mistakes(session: Session, drill_set: DrillSet, topic: str) -> list[Mistake]:
    found = []
    for mid in drill_set.from_mistake_ids or []:
        m = session.get(Mistake, mid)
        if m is None:
            continue
        if (m.topic or weakness.topic_for(m.category, m.subcategory)) == topic:
            found.append(m)
    return found


def _reveal(item: dict, idx: int, attempt: int, correct: bool, **extra) -> Result:
    return Result(
        idx=idx, attempt=attempt, correct=correct, final=True, answer=item["answer"], rule=item.get("rule", ""),
        topic=_item_topic(item), topic_label=item.get("topic_label", ""), sentence=fill(item), **extra,
    )


def submit(session: Session, drill_set: DrillSet, idx: int, answer: str, attempt: int, now: datetime | None = None) -> Result:
    items = drill_set.items_json
    if not 0 <= idx < len(items):
        raise IndexError(f"No item {idx} in drill set {drill_set.id}")
    item = items[idx]
    answer = (answer or "").strip()
    attempt = 2 if attempt >= 2 else 1

    prior = _stored(session, drill_set).get(idx)
    if prior is not None:  # already final (double submit): show it again, change nothing
        return _reveal(item, idx, attempt, prior.correct)
    if not answer:
        return Result(idx, attempt, correct=False, final=False, empty=True)

    topic = _item_topic(item)
    if check(item, answer):
        session.add(DrillAnswer(drill_set_id=drill_set.id, item_idx=idx, answer=answer, correct=True))
        session.commit()
        if attempt == 1:
            for m in _seed_mistakes(session, drill_set, topic):
                weakness.record_drill_answer(session, m, True, now)
        progress(session, drill_set, now)
        return _reveal(item, idx, attempt, True, credited=attempt == 1)

    if attempt == 1:
        return Result(idx, 1, correct=False, final=False, topic=topic, topic_label=item.get("topic_label", ""))

    # Log the mistake before storing the final answer, so a failure can't leave the item
    # answered with its mistake unrecorded.
    log_mistake(
        session, RouteResult(), module=Module.drill, ref_id=drill_set.id, category=Category(item.get("category") or drill_set.category),
        subcategory=item.get("topic_label"), wrong=answer, right=item["answer"], explanation=item.get("rule"),
        make_card=False, topic=topic or None,
    )
    session.add(DrillAnswer(drill_set_id=drill_set.id, item_idx=idx, answer=answer, correct=False))
    session.commit()
    for m in _seed_mistakes(session, drill_set, topic):
        weakness.record_drill_answer(session, m, False, now)
    progress(session, drill_set, now)
    return _reveal(item, idx, attempt, False)

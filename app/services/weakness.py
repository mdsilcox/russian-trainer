"""Weakness scoring: which grammar topics to drill next, and when a mistake counts as mastered.

A topic is the grammar-reference section a mistake links to (grammar.link_for), so free-text
subcategories like "genitive plural after numerals" and "gen. pl" land in the same bucket.

score = recency-weighted open mistakes - recency-weighted correct drill answers (never below 0),
then the travel high-yield topics get a boost and a small prior, so a learner with no history
starts on them.
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import Session, col, select

from app.models import Category, DrillAnswer, DrillSet, Mistake
from app.services import srs
from app.services.grammar import _PREP_IDS, ASPECT, CASES, MOTION, NUMBERS, PITFALLS, STRESS, link_for
from app.services.mistakes import DRILL_CATEGORIES
from app.services.stats import category_label, local_date

HALF_LIFE_DAYS = 14  # a mistake two weeks old weighs half as much as today's
SUCCESS_WEIGHT = 0.5  # one correct drill answer offsets half a fresh mistake
SUCCESS_WINDOW_DAYS = 60
SELF_CORRECTED_WEIGHT = 0.5  # fixed it yourself before seeing the answer: less urgent
HIGH_YIELD_BOOST = 1.5
HIGH_YIELD_PRIOR = 0.25
MASTERY_DAYS = 3  # correct answers, each on a different day

# The research's high-yield list for a trip (docs/research.md), as reference sections.
HIGH_YIELD = {
    f"{CASES}#prepositional",  # в метро́, на вокза́ле
    f"{CASES}#prepositional-locative",  # в аэропорту́
    f"{CASES}#location-direction",  # в Москву́ vs в Москве́
    f"{CASES}#accusative",
    f"{CASES}#animate-accusative",
    f"{CASES}#genitive",  # нет, мно́го, из, до, у, без
    f"{CASES}#genitive-plural",
    f"{NUMBERS}#numbers-rule",  # 1 / 2-4 / 5+
    f"{CASES}#dative",  # мне ну́жно, мне нра́вится
    f"{MOTION}#motion-use",  # идти́/ходи́ть, е́хать/е́здить
}

TOPIC_LABELS = {
    CASES: "Cases",
    f"{CASES}#nominative": "Nominative",
    f"{CASES}#genitive": "Genitive",
    f"{CASES}#genitive-plural": "Genitive plural",
    f"{CASES}#dative": "Dative",
    f"{CASES}#accusative": "Accusative",
    f"{CASES}#animate-accusative": "Animate accusative",
    f"{CASES}#instrumental": "Instrumental",
    f"{CASES}#prepositional": "Prepositional",
    f"{CASES}#prepositional-locative": "Locative -у́ forms",
    f"{CASES}#location-direction": "Location vs direction (в/на)",
    f"{CASES}#adjectives": "Adjective endings",
    f"{CASES}#possessives": "Possessives and pronouns",
    f"{CASES}#prepositions": "Prepositions",
    f"{CASES}#spelling-rules": "Spelling rules",
    f"{NUMBERS}#numbers-rule": "Numerals with nouns",
    NUMBERS: "Numbers",
    MOTION: "Verbs of motion",
    f"{MOTION}#motion-use": "Motion: which verb",
    f"{MOTION}#motion-prefixes": "Motion prefixes",
    f"{MOTION}#motion-conjugation": "Motion verb forms",
    f"{MOTION}#motion-aspect": "Motion verbs and aspect",
    ASPECT: "Verb aspect",
    f"{ASPECT}#aspect-choose": "Aspect: which one",
    f"{ASPECT}#aspect-pairs": "Aspect pairs",
    f"{ASPECT}#aspect-negation": "Aspect with negation",
    f"{ASPECT}#aspect-commands": "Aspect in commands",
    STRESS: "Stress",
    PITFALLS: "Common pitfalls",
    "/grammar": "Grammar",
}
_PREP_LABELS = {f"{CASES}#{anchor}": f"Preposition {word}" for word, anchor in _PREP_IDS.items()}
_PREP_LABELS[f"{CASES}#prep-s-gen"] = "Preposition с (from)"
_PREP_LABELS[f"{CASES}#prep-s-instr"] = "Preposition с (with)"


def topic_for(category: Category | str, subcategory: str | None) -> str:
    value = category.value if isinstance(category, Category) else category
    return link_for(value, subcategory)


def topic_label(topic: str, category: Category | None = None) -> str:
    if topic in TOPIC_LABELS:
        return TOPIC_LABELS[topic]
    if topic in _PREP_LABELS:
        return _PREP_LABELS[topic]
    return category_label(category) if category else "Grammar"


@dataclass
class TopicScore:
    topic: str  # reference URL, e.g. /grammar/cases#genitive-plural
    label: str
    category: Category | None
    score: float
    high_yield: bool
    mistake_weight: float = 0.0
    success_weight: float = 0.0
    mistake_ids: list[int] = field(default_factory=list)  # open mistakes, newest first
    subcategories: list[str] = field(default_factory=list)  # free-text labels seen, for the drill generator


def _decay(when: datetime, now: datetime) -> float:
    age_days = max(0.0, (now - srs._utc(when)).total_seconds() / 86400)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def topic_scores(session: Session, now: datetime | None = None) -> list[TopicScore]:
    """Every drillable topic with history, plus the high-yield ones, highest score first."""
    now = srs._utc(now or datetime.now().astimezone())
    topics: dict[str, TopicScore] = {}

    def get(topic: str, category: Category | None) -> TopicScore:
        if topic not in topics:
            topics[topic] = TopicScore(topic, topic_label(topic, category), category, 0.0, topic in HIGH_YIELD)
        elif topics[topic].category is None:
            topics[topic].category = category
        return topics[topic]

    open_mistakes = session.exec(
        select(Mistake)
        .where(Mistake.mastered == False, col(Mistake.category).in_(DRILL_CATEGORIES))  # noqa: E712
        .order_by(col(Mistake.created_at).desc(), col(Mistake.id).desc())
    ).all()
    for m in open_mistakes:
        t = get(m.topic or topic_for(m.category, m.subcategory), m.category)
        weight = _decay(m.created_at, now) * (SELF_CORRECTED_WEIGHT if m.self_corrected else 1.0)
        t.mistake_weight += weight
        t.mistake_ids.append(m.id)
        if m.subcategory and m.subcategory not in t.subcategories:
            t.subcategories.append(m.subcategory)

    since = now.timestamp() - SUCCESS_WINDOW_DAYS * 86400
    rows = session.exec(
        select(DrillAnswer.created_at, DrillAnswer.item_idx, DrillSet)
        .join(DrillSet, DrillSet.id == DrillAnswer.drill_set_id)
        .where(DrillAnswer.correct == True)  # noqa: E712
    ).all()
    for created_at, item_idx, drill_set in rows:
        if srs._utc(created_at).timestamp() < since:
            continue
        items = drill_set.items_json or []
        item = items[item_idx] if 0 <= item_idx < len(items) and isinstance(items[item_idx], dict) else {}
        category = drill_set.category
        topic = item.get("topic") or drill_set.topic or topic_for(category, drill_set.subcategory)
        t = get(topic, category)
        t.success_weight += _decay(created_at, now) * SUCCESS_WEIGHT

    for topic in HIGH_YIELD:
        get(topic, Category.motion_verb if topic.startswith(MOTION) else Category.case)

    for t in topics.values():
        base = max(0.0, t.mistake_weight - t.success_weight)
        t.score = base * HIGH_YIELD_BOOST + HIGH_YIELD_PRIOR if t.high_yield else base
    return sorted(topics.values(), key=lambda t: (-t.score, -len(t.mistake_ids), t.label))


def pick_topics(session: Session, now: datetime | None = None, n: int = 2) -> list[TopicScore]:
    """The n topics to drill today."""
    return [t for t in topic_scores(session, now) if t.score > 0][:n]


def record_drill_answer(session: Session, mistake: Mistake, correct: bool, now: datetime | None = None) -> Mistake:
    """Move a mistake toward mastery. Only one correct answer per local day counts, so mastery
    means MASTERY_DAYS separate days; a wrong answer starts the count again."""
    today = local_date(now)
    if correct:
        if mistake.last_drilled_on is None or today > mistake.last_drilled_on:
            mistake.drilled_count += 1
            mistake.last_drilled_on = today
            if mistake.drilled_count >= MASTERY_DAYS:
                mistake.mastered = True
    else:
        mistake.drilled_count = 0
        mistake.mastered = False
    session.add(mistake)
    session.commit()
    return mistake

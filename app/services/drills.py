"""Drill generator (P2.2).

Explicit instruction then practice (Norris & Ortega; Spada & Tomita), then interleaving
(Nakata & Suzuki): a topic the learner hasn't drilled yet opens with a short rule card and a
focused block; once a focused set for it is finished, the topic joins MIXED sets that
interleave several weak topics.

Every set is generated from the learner's own mistakes on the topic, then a second, independent
review pass re-solves each item: wrong keys are fixed, ambiguous or unnatural items are dropped.
Unfinished sets are reused rather than regenerated.
"""

import random
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from app.models import Category, DrillSet, Mistake
from app.services import srs
from app.services.claude import ClaudeClient, Task
from app.services.grammar import ASPECT, CASES, MOTION, NUMBERS
from app.services.weakness import TopicScore, topic_scores

FOCUSED_ITEMS = 8
MIXED_TOPICS = 3
MIXED_PER_TOPIC = 3
MIN_ITEMS = 4  # after review; below this the set is not worth showing
MAX_SEEDS = 6
BLANK = "___"

Format = Literal["case_ending", "preposition_case", "numeral", "aspect_choice", "motion_choice", "other"]


class Example(BaseModel):
    ru: str = Field(description="A short Russian sentence with stress marks (U+0301) on words of 2+ syllables")
    en: str


class RuleCard(BaseModel):
    title: str = Field(description="The pattern in a few words, e.g. 'Genitive plural after numbers and много'")
    rule: str = Field(description="2-3 plain English sentences: when it applies and how to form it")
    examples: list[Example] = Field(description="2-3 travel-flavoured examples")


class DrillItem(BaseModel):
    format: Format
    prompt_ru: str = Field(description=f"One natural Russian sentence containing exactly one {BLANK} where the answer goes; stress marks on other words")
    cue: str = Field(description="What the learner works from, shown in brackets: the dictionary form to inflect (Москва́), a choice (идти́ / ходи́ть, покупа́ть / купи́ть, в / на), or the number and noun (5, рубль)")
    translation_en: str = Field(description="English translation of the whole sentence, so the meaning is unambiguous")
    answer: str = Field(description=f"Exactly the word(s) that fill {BLANK}, with stress marks")
    accepted: list[str] = Field(description="Other fully correct fillers (true alternatives only; spelling without stress marks or with е for ё is accepted automatically, so don't list those)")
    rule: str = Field(description="One short English line naming the rule, e.g. 'в + accusative for where you are going'")
    topic_index: int = Field(default=0, description="For mixed sets: which topic (0-based, in the order given) this item practises")


class GeneratedSet(BaseModel):
    rule_card: RuleCard | None = Field(description="Required for a focused set; null for a mixed set")
    items: list[DrillItem]


class ReviewedItem(BaseModel):
    index: int
    solved: str = Field(description="Your own answer for the blank, worked out before looking at the key")
    verdict: Literal["ok", "fix", "drop"] = Field(description="ok: key correct and the blank has one clear answer. fix: the sentence is fine but the key is wrong or misses a correct alternative. drop: ambiguous, unnatural, off-topic, or the cue gives the answer away")
    answer: str = Field(description="The correct answer (the key if ok, your corrected one if fix)")
    accepted: list[str] = Field(description="Every other fully correct filler")
    note: str = Field(description="A few words on why, for fix or drop")


class Review(BaseModel):
    items: list[ReviewedItem]


# What to ask for, by reference section prefix (most specific first).
FORMAT_GUIDE = [
    (f"{NUMBERS}", "numeral agreement with prices, times, ages and quantities: give the number and the dictionary-form noun in the cue (5, рубль) and blank the noun form, or blank the number word when gender matters (оди́н/одна́, два/две)."),
    (f"{CASES}#location-direction", "where (в/на + prepositional) against where to (в/на + accusative): blank the noun phrase, cue gives its dictionary form; mix both directions."),
    (f"{CASES}#prep", "the preposition and its case together: blank the preposition plus noun, cue gives the meaning-free dictionary form; or blank only the noun after a given preposition."),
    (f"{CASES}#prepositions", "the preposition and its case together: blank the preposition plus noun, cue gives the noun's dictionary form."),
    (f"{CASES}", "case-ending fill-ins in everyday travel sentences (station, hotel, café, metro, family visits): blank one noun or adjective+noun phrase, cue gives its dictionary form."),
    (f"{ASPECT}", "aspect choice in context: cue gives the pair (покупа́ть / купи́ть), blank needs the right form in the right tense; the sentence must contain the clue (вчера весь день, уже, каждый день, не надо, etc.)."),
    (f"{MOTION}", "verb-of-motion choice: cue gives the options (идти́ / ходи́ть / е́хать / е́здить, or prefixed forms like прие́хать / уе́хать), blank needs the right form; the sentence must make one-way vs round-trip, on foot vs by transport, and arrival vs departure unambiguous."),
]


def format_guide(topic: str) -> str:
    for prefix, guide in FORMAT_GUIDE:
        if topic.startswith(prefix):
            return guide
    return "fill-in-the-blank sentences that test exactly this pattern."


SYSTEM = f"""You write grammar drills in Russian for an English-speaking adult at intermediate (B1) level who is preparing for a family trip to Moscow. Explanations are in English.

Every item is one natural sentence a person might really say or hear in Moscow (transport, hotels, cafés, shops, sightseeing, family, small talk), containing exactly one {BLANK}.

Hard requirements:
- Exactly one correct answer for the blank given the cue and the English translation. If two forms could fit, change the sentence until only one does, or list the other in `accepted`.
- The answer must be standard modern Russian. Put stress marks (U+0301) on the answer and on every word of 2+ syllables in prompt_ru and the examples; never on ё, never on one-syllable words.
- The cue must not give the answer away (give the dictionary form, the aspect pair, or the options, never the inflected form). The cue is only those words: no notes, labels or grammar hints in it.
- Every item must actually change form or require a real choice: no indeclinable words (такси́, кафе́, метро́) and no items where the answer equals the cue unless the point is that it doesn't change.
- Vary the words and situations; don't repeat a noun or a sentence frame.
- Base several items on the learner's own mistakes when they're given: test the same pattern in a new sentence; never copy their sentence.

Punctuation: never use em dashes (—) in English text; use a comma, colon, full stop or parentheses instead. Inside Russian sentences, keep the dash only where Russian grammar requires it."""

REVIEW_SYSTEM = f"""You are a meticulous Russian grammar checker reviewing fill-in-the-blank drills before a learner sees them.

For each item, first solve the blank yourself from prompt_ru, the cue and translation_en, writing your answer in `solved`, and only then compare with the given key.
- verdict "ok": the key is correct and the blank has one clear answer (or the alternatives are all listed).
- verdict "fix": the sentence is good but the key is wrong, or a correct alternative is missing from accepted. Give the corrected answer and full accepted list.
- verdict "drop": the item is ambiguous, unnatural, ungrammatical apart from the blank, tests a different pattern than its rule, or its cue gives the answer away.
Keep stress marks (U+0301) on answers. Judge spelling with е/ё and missing stress marks as equivalent. Be strict: dropping a doubtful item is better than teaching a wrong form."""


def _seed_lines(session: Session, mistake_ids: list[int]) -> str:
    if not mistake_ids:
        return "No logged mistakes on this yet; use the most common travel situations."
    mistakes = session.exec(select(Mistake).where(col(Mistake.id).in_(mistake_ids[:MAX_SEEDS]))).all()
    lines = []
    for m in mistakes:
        why = f" ({m.explanation})" if m.explanation else ""
        lines.append(f"- wrote «{m.wrong}», should be «{m.right}»; {m.subcategory or m.category.value}{why}")
    return "\n".join(lines)


def build_focused_prompt(session: Session, topic: TopicScore) -> str:
    return (
        f"Make a FOCUSED set on one pattern: {topic.label} (reference: {topic.topic}).\n"
        f"Labels this learner's mistakes were filed under: {', '.join(topic.subcategories) or 'none yet'}.\n\n"
        f"Their mistakes on it:\n{_seed_lines(session, topic.mistake_ids)}\n\n"
        f"Write a rule_card (this is the first time they drill it), then {FOCUSED_ITEMS} items, easiest first. "
        f"Formats to use: {format_guide(topic.topic)}"
    )


def build_mixed_prompt(session: Session, topics: list[TopicScore]) -> str:
    blocks = []
    for i, t in enumerate(topics):
        blocks.append(
            f"Topic {i}: {t.label} (reference: {t.topic})\n"
            f"Formats: {format_guide(t.topic)}\n"
            f"Their mistakes:\n{_seed_lines(session, t.mistake_ids)}"
        )
    return (
        f"Make a MIXED review set (rule_card: null) with {MIXED_PER_TOPIC} items for each topic below; "
        f"set topic_index on each item. The learner has already met each rule, so items can be a little harder.\n\n"
        + "\n\n".join(blocks)
    )


def _review(client: ClaudeClient, items: list[DrillItem]) -> list[DrillItem]:
    """Independent second pass: keep ok, apply fix, remove drop."""
    listing = "\n".join(
        f"{i}. prompt_ru: {it.prompt_ru}\n   cue: {it.cue}\n   translation_en: {it.translation_en}\n"
        f"   key: {it.answer}; accepted: {', '.join(it.accepted) or 'none'}\n   rule: {it.rule}"
        for i, it in enumerate(items)
    )
    review = client.ask_structured(Task.drill_review, REVIEW_SYSTEM, f"Review these {len(items)} items:\n\n{listing}", Review)
    verdicts = {r.index: r for r in review.items}
    kept = []
    for i, item in enumerate(items):
        r = verdicts.get(i)
        if r is None or r.verdict == "drop":
            continue
        if r.verdict == "fix":
            item = item.model_copy(update={"answer": r.answer, "accepted": r.accepted})
        kept.append(item)
    return kept


def _valid(item: DrillItem) -> bool:
    return item.prompt_ru.count(BLANK) == 1 and bool(item.answer.strip())


def _item_dict(item: DrillItem, topic: TopicScore) -> dict:
    category = (topic.category or Category.case).value
    return {**item.model_dump(exclude={"topic_index"}), "topic": topic.topic, "topic_label": topic.label, "category": category}


class NotEnoughItems(RuntimeError):
    pass


def generate_focused(session: Session, client: ClaudeClient, topic: TopicScore) -> DrillSet:
    generated = client.ask_structured(Task.drill_generation, SYSTEM, build_focused_prompt(session, topic), GeneratedSet)
    items = _review(client, [it for it in generated.items if _valid(it)])
    if len(items) < MIN_ITEMS:
        raise NotEnoughItems(f"Only {len(items)} drills passed the answer-key check; try again.")
    drill_set = DrillSet(
        category=topic.category or Category.case,
        subcategory=topic.label,
        topic=topic.topic,
        kind="focused",
        intro_json=generated.rule_card.model_dump() | {"reference": topic.topic} if generated.rule_card else {"reference": topic.topic},
        items_json=[_item_dict(it, topic) for it in items],
        from_mistake_ids=topic.mistake_ids[:MAX_SEEDS],
    )
    session.add(drill_set)
    session.commit()
    session.refresh(drill_set)
    return drill_set


def generate_mixed(session: Session, client: ClaudeClient, topics: list[TopicScore], seed: int | None = None) -> DrillSet:
    generated = client.ask_structured(Task.drill_generation, SYSTEM, build_mixed_prompt(session, topics), GeneratedSet)
    raw = [it for it in generated.items if _valid(it) and 0 <= it.topic_index < len(topics)]
    items = _review(client, raw)
    if len(items) < MIN_ITEMS:
        raise NotEnoughItems(f"Only {len(items)} drills passed the answer-key check; try again.")
    tagged = [_item_dict(it, topics[it.topic_index]) for it in items]
    random.Random(seed).shuffle(tagged)
    tagged = _interleave(tagged)
    drill_set = DrillSet(
        category=topics[0].category or Category.case,
        subcategory=" + ".join(t.label for t in topics),
        topic=None,
        kind="mixed",
        intro_json=None,
        items_json=tagged,
        from_mistake_ids=[i for t in topics for i in t.mistake_ids[:2]],
    )
    session.add(drill_set)
    session.commit()
    session.refresh(drill_set)
    return drill_set


def _interleave(items: list[dict]) -> list[dict]:
    """Reorder so no two neighbours share a topic where that's possible."""
    out: list[dict] = []
    pool = items[:]
    while pool:
        pick = next((i for i, it in enumerate(pool) if not out or it["topic"] != out[-1]["topic"]), 0)
        out.append(pool.pop(pick))
    return out


def introduced_topics(session: Session) -> set[str]:
    """Topics with a finished focused set: their rule has been taught."""
    rows = session.exec(
        select(DrillSet.topic).where(DrillSet.kind == "focused", DrillSet.completed_at != None)  # noqa: E711
    ).all()
    return {t for t in rows if t}


def open_set(session: Session) -> DrillSet | None:
    """The newest unfinished set, reused instead of generating a new one."""
    return session.exec(
        select(DrillSet).where(DrillSet.completed_at == None).order_by(col(DrillSet.created_at).desc(), col(DrillSet.id).desc())  # noqa: E711
    ).first()


def plan_next(session: Session, now: datetime | None = None) -> tuple[str, list[TopicScore]]:
    """What the next set should be: ("focused", [topic]) for the weakest topic not yet taught,
    else ("mixed", topics) over the weakest taught ones."""
    introduced = introduced_topics(session)
    ranked = [t for t in topic_scores(session, now) if t.score > 0]
    if not ranked:
        return "none", []
    top = ranked[0]
    if top.topic not in introduced:
        return "focused", [top]
    taught = [t for t in ranked if t.topic in introduced][:MIXED_TOPICS]
    if len(taught) >= 2:
        return "mixed", taught
    fresh = next((t for t in ranked if t.topic not in introduced), None)
    return ("focused", [fresh]) if fresh else ("focused", [top])


def next_set(session: Session, client: ClaudeClient | None = None, now: datetime | None = None) -> DrillSet | None:
    """Reuse the open set, or generate the planned one."""
    existing = open_set(session)
    if existing is not None:
        return existing
    kind, topics = plan_next(session, now)
    if kind == "none":
        return None
    client = client or ClaudeClient(session)
    if kind == "mixed":
        return generate_mixed(session, client, topics)
    return generate_focused(session, client, topics[0])


def complete_set(session: Session, drill_set: DrillSet, now: datetime | None = None) -> DrillSet:
    drill_set.completed_at = srs._utc(now or datetime.now().astimezone())
    session.add(drill_set)
    session.commit()
    return drill_set

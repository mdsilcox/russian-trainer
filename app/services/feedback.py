"""Claude feedback on story translations.

Feedback always targets the Russian side of a story: your translation when
the story was written in English, or the story itself when you wrote it in
Russian (then the English translation is only checked for meaning).
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field
from sqlmodel import Session

from app.models import Category, Setting, Story, TranslationAttempt
from app.services.claude import ClaudeClient, Task

CATEGORY_LABELS = {
    Category.case: "Case endings",
    Category.aspect: "Verb aspect",
    Category.motion_verb: "Verbs of motion",
    Category.participle: "Participles & gerunds",
    Category.agreement: "Agreement",
    Category.word_choice: "Word choice",
    Category.word_order: "Word order",
    Category.preposition: "Prepositions",
    Category.stress: "Stress",
    Category.spelling: "Spelling",
    Category.idiom: "Natural phrasing",
}

Severity = Literal["error", "unnatural", "style"]


class Issue(BaseModel):
    wrong: str = Field(description="The exact erroneous words copied character-for-character from the learner's Russian text; as short as possible (usually 1-4 words)")
    right: str = Field(description="The corrected replacement for exactly those words")
    category: Literal[tuple(c.value for c in Category)]  # type: ignore[valid-type]
    subcategory: str = Field(description="Short, reusable label for the specific rule, e.g. 'prepositional after в/на', 'genitive after numerals 5+', 'perfective for one completed action', 'идти vs ходить', 'ехать vs идти'")
    explanation: str = Field(description="One or two sentences explaining the rule, addressed to the learner")
    severity: Severity


class Rephrasing(BaseModel):
    original: str = Field(description="A sentence or phrase from the learner's (corrected) text that is grammatical but unnatural")
    natural: str = Field(description="How a native speaker in Moscow would actually say it")
    why: str


class VocabItem(BaseModel):
    ru: str = Field(description="Dictionary form with a stress mark (U+0301) on every word of 2+ syllables")
    en: str
    example_ru: str = Field(description="A short stress-marked example sentence, ideally reusing the story's context")
    example_en: str
    why: str = Field(description="Why this is worth learning for this learner")


class Feedback(BaseModel):
    summary: str = Field(description="2-3 sentences: what went well and the one or two patterns to focus on")
    corrected_text: str = Field(description="The learner's full Russian text with minimal corrections, keeping their wording wherever it was acceptable")
    issues: list[Issue]
    rephrasings: list[Rephrasing] = Field(description="Up to 3")
    vocab: list[VocabItem] = Field(description="2 or 3 items")
    translation_notes: list[str] = Field(description="Only for stories written in Russian: places where the English translation misrepresents the Russian. Empty otherwise.")


SYSTEM = """You are a warm, precise Russian tutor for an English-speaking adult at an intermediate (B1) level who is preparing for a family trip to Moscow. They write short original stories and translate them. You review the Russian text.

Explanations: write them in {language}. Keep each to one or two sentences and name the rule (e.g. "в + prepositional for location"), not just the fix.

Reporting issues:
- Copy `wrong` character-for-character from the learner's Russian text so it can be located; keep it as short as possible while still unambiguous (usually 1-4 words). One issue per distinct error. Never report the same error twice.
- `right` replaces exactly the `wrong` words.
- severity "error": ungrammatical or wrong meaning. "unnatural": grammatical but a native speaker wouldn't say it. "style": a minor preference. Don't pad with style issues; at most a few.
- Do not flag correct alternatives as errors. Accept ё written as е. Do not flag missing stress marks; use the "stress" category only if the learner wrote a stress mark (´) on the wrong vowel.
- Categories: case (wrong case ending/form), aspect (perfective vs imperfective choice), motion_verb (идти/ходить/ехать/ездить and prefixed forms), participle (participles and verbal adverbs), agreement (gender/number/person agreement), word_choice (wrong or unidiomatic word), word_order, preposition (wrong or missing preposition, not the case after it), stress, spelling, idiom (set phrases, collocations, how things are naturally said).
- Use consistent, reusable subcategory labels so the learner's mistakes can be grouped into drills over time.

This learner's known weak spots: {weak_spots}. Look especially carefully at these, but don't invent errors.

corrected_text: apply every "error" and "unnatural" fix and nothing else, so it stays the learner's own story.
rephrasings: up to 3 places where even the corrected text sounds translated from English; show what a Muscovite would say.
vocab: 2-3 words or phrases the learner reached for or avoided, useful for everyday life in Moscow, with stress marks.
summary: encouraging and specific; mention the one or two patterns most worth practising.

Punctuation: never use em dashes (—) in English text; use a comma, colon, full stop or parentheses instead. Inside Russian sentences, keep the dash only where Russian grammar requires it (e.g. Москва́ — столи́ца)."""


def _setting(session: Session, key: str, default):
    row = session.get(Setting, key)
    return row.value if row is not None else default


def build_system(session: Session) -> str:
    language = {"en": "English", "ru": "simple Russian"}.get(_setting(session, "feedback_language", "en"), "English")
    weak = _setting(session, "weak_areas_note", "") or "not specified yet"
    return SYSTEM.format(language=language, weak_spots=weak)


def russian_text(story: Story, attempt: TranslationAttempt) -> str:
    return attempt.text if story.source_lang == "en" else story.source_text


def build_prompt(story: Story, attempt: TranslationAttempt) -> str:
    if story.source_lang == "en":
        return (
            f"Story title: {story.title}\n\n"
            f"The learner wrote this story in English:\n<english>\n{story.source_text}\n</english>\n\n"
            f"Their Russian translation, which you are reviewing:\n<russian>\n{attempt.text}\n</russian>"
        )
    return (
        f"Story title: {story.title}\n\n"
        f"The learner wrote this story in Russian; this is the text you are reviewing:\n<russian>\n{story.source_text}\n</russian>\n\n"
        f"Their English translation (check it only for misunderstood meaning, in translation_notes):\n<english>\n{attempt.text}\n</english>"
    )


def request_feedback(session: Session, client: ClaudeClient, story: Story, attempt: TranslationAttempt) -> Feedback:
    """Ask Claude for feedback and store it on the attempt."""
    feedback = client.ask_structured(Task.feedback, build_system(session), build_prompt(story, attempt), Feedback)
    attempt.feedback_json = feedback.model_dump()
    attempt.corrected_text = feedback.corrected_text
    session.add(attempt)
    session.commit()
    return feedback


def load(attempt: TranslationAttempt) -> Feedback | None:
    return Feedback.model_validate(attempt.feedback_json) if attempt.feedback_json else None


# --- Self-correction ----------------------------------------------------------

_TRAILING = re.compile(r"[\s.,!?;:…»\"')\]]+$")


def normalize_answer(text: str) -> str:
    """Forgiving form for comparing a typed fix with the right answer.

    Lowercase, no stress marks, ё = е, collapsed whitespace, no trailing punctuation.
    Mirrored in static/feedback.js.
    """
    text = unicodedata.normalize("NFC", unicodedata.normalize("NFD", text).replace("́", ""))
    text = " ".join(text.lower().replace("ё", "е").split())
    return _TRAILING.sub("", text).strip()


# --- Rendering helpers ---------------------------------------------------------

@dataclass
class Segment:
    text: str
    issue: int | None = None  # index into feedback.issues


def annotate(text: str, issues: list[Issue]) -> tuple[list[Segment], set[int]]:
    """Split text into plain and highlighted segments; returns (segments, indexes of issues not found).

    Issues are located in order, falling back to a search from the start;
    overlapping or missing spans are left for the grouped list only.
    """
    spans: list[tuple[int, int, int]] = []
    unplaced: set[int] = set()
    cursor = 0
    for i, issue in enumerate(issues):
        needle = issue.wrong.strip()
        start = text.find(needle, cursor) if needle else -1
        if start < 0 and needle:
            start = text.find(needle)
        end = start + len(needle)
        if start < 0 or any(s < end and start < e for s, e, _ in spans):
            unplaced.add(i)
            continue
        spans.append((start, end, i))
        cursor = end
    segments: list[Segment] = []
    pos = 0
    for start, end, i in sorted(spans):
        if start > pos:
            segments.append(Segment(text[pos:start]))
        segments.append(Segment(text[start:end], i))
        pos = end
    if pos < len(text):
        segments.append(Segment(text[pos:]))
    return segments, unplaced


def grouped_issues(feedback: Feedback) -> list[tuple[str, list[tuple[int, Issue]]]]:
    """Issues grouped by category label, biggest group first; errors before other severities."""
    order = {"error": 0, "unnatural": 1, "style": 2}
    groups: dict[str, list[tuple[int, Issue]]] = {}
    for i, issue in enumerate(feedback.issues):
        groups.setdefault(CATEGORY_LABELS[Category(issue.category)], []).append((i, issue))
    for items in groups.values():
        items.sort(key=lambda pair: order[pair[1].severity])
    return sorted(groups.items(), key=lambda kv: -len(kv[1]))

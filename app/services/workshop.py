"""Story workshop: stories, translation attempts, revision diffs and bulk import."""

import difflib
import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, col, delete, select

from app.models import Mistake, Module, Story, TranslationAttempt, utcnow

LANGS = {"en": "English", "ru": "Russian"}


def other_lang(lang: str) -> str:
    return "ru" if lang == "en" else "en"


def create_story(session: Session, title: str, source_lang: str, source_text: str, translation: str = "") -> Story:
    title, source_text = title.strip(), source_text.strip()
    if not title:
        raise ValueError("Give the story a title")
    if source_lang not in LANGS:
        raise ValueError("Source language must be English or Russian")
    if not source_text:
        raise ValueError("The story text is empty")
    story = Story(title=title, source_lang=source_lang, source_text=source_text)
    session.add(story)
    session.commit()
    if translation.strip():
        add_attempt(session, story, translation)
    return story


def add_attempt(session: Session, story: Story, text: str) -> TranslationAttempt:
    text = text.strip()
    if not text:
        raise ValueError("The translation is empty")
    attempt = TranslationAttempt(story_id=story.id, text=text, created_at=utcnow())
    session.add(attempt)
    session.commit()
    return attempt


def attempts_for(session: Session, story_id: int) -> list[TranslationAttempt]:
    """Oldest first, so attempt numbers are stable."""
    query = select(TranslationAttempt).where(TranslationAttempt.story_id == story_id)
    return list(session.exec(query.order_by(col(TranslationAttempt.created_at), col(TranslationAttempt.id))).all())


def issue_counts(attempt: TranslationAttempt) -> dict[str, int] | None:
    """Issues per severity from an attempt's feedback, or None if it has none yet."""
    if not attempt.feedback_json:
        return None
    counts = {"error": 0, "unnatural": 0, "style": 0}
    for issue in attempt.feedback_json.get("issues", []):
        counts[issue.get("severity", "error")] = counts.get(issue.get("severity", "error"), 0) + 1
    return counts


def delete_story(session: Session, story_id: int) -> None:
    """Remove a story and its attempts. Logged mistakes stay, since they still describe your errors."""
    session.exec(delete(TranslationAttempt).where(TranslationAttempt.story_id == story_id))
    session.exec(delete(Story).where(Story.id == story_id))
    session.commit()


@dataclass
class StoryRow:
    story: Story
    attempts: int
    last_activity: datetime
    mistakes: int


def list_stories(session: Session) -> list[StoryRow]:
    attempts = dict(
        session.exec(
            select(TranslationAttempt.story_id, func.count()).group_by(TranslationAttempt.story_id)
        ).all()
    )
    last = dict(
        session.exec(
            select(TranslationAttempt.story_id, func.max(TranslationAttempt.created_at)).group_by(
                TranslationAttempt.story_id
            )
        ).all()
    )
    attempt_story = dict(session.exec(select(TranslationAttempt.id, TranslationAttempt.story_id)).all())
    mistakes: dict[int, int] = {}
    for ref_id in session.exec(select(Mistake.ref_id).where(Mistake.module == Module.story)).all():
        story_id = attempt_story.get(ref_id)
        if story_id:
            mistakes[story_id] = mistakes.get(story_id, 0) + 1
    rows = [
        StoryRow(s, attempts.get(s.id, 0), last.get(s.id) or s.created_at, mistakes.get(s.id, 0))
        for s in session.exec(select(Story)).all()
    ]
    return sorted(rows, key=lambda r: r.last_activity, reverse=True)


# --- Revision diff -------------------------------------------------------------

_TOKEN = re.compile(r"\s+|[^\s]+")


def word_diff(before: str, after: str) -> list[tuple[str, str]]:
    """Word-level diff as (op, text) pairs, op in {"same", "del", "ins"}."""
    a, b = _TOKEN.findall(before), _TOKEN.findall(after)
    out: list[tuple[str, str]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(("same", "".join(a[i1:i2])))
            continue
        if op in ("delete", "replace"):
            out.append(("del", "".join(a[i1:i2])))
        if op in ("insert", "replace"):
            out.append(("ins", "".join(b[j1:j2])))
    return out


# --- Bulk import ---------------------------------------------------------------

IMPORT_TEMPLATE = """# The night train
## EN
I took the night train to Kazan. The compartment was small but warm.
## RU
Я поехал на ночном поезде в Казань. Купе было маленькое, но тёплое.

# Second story title
## RU
Original story written in Russian…
## EN
Your English translation…"""


@dataclass
class ParsedStory:
    title: str
    source_lang: str
    source_text: str
    translation: str


def parse_import(text: str) -> tuple[list[ParsedStory], list[str]]:
    """Parse "# Title / ## EN / ## RU" blocks. The first language section is the source."""
    stories: list[ParsedStory] = []
    errors: list[str] = []
    blocks = re.split(r"(?m)^#(?!#)\s*", text.strip())
    for block in blocks:
        if not block.strip():
            continue
        title, _, body = block.partition("\n")
        title = title.strip()
        sections = re.split(r"(?mi)^##\s*(EN|RU)\s*$", body)
        # sections = [preamble, lang1, text1, lang2, text2, ...]
        langs = [(sections[i].lower(), sections[i + 1].strip()) for i in range(1, len(sections) - 1, 2)]
        if not langs or not langs[0][1]:
            errors.append(f"“{title or '(untitled)'}”: needs a ## EN or ## RU section with the story text.")
            continue
        source_lang, source_text = langs[0]
        translation = next((t for lang, t in langs[1:] if lang != source_lang), "")
        stories.append(ParsedStory(title or "Untitled", source_lang, source_text, translation))
    return stories, errors


def import_stories(session: Session, parsed: list[ParsedStory]) -> list[Story]:
    return [create_story(session, p.title, p.source_lang, p.source_text, p.translation) for p in parsed]

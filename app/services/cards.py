"""Creating, finding and enriching cards."""

import re
import unicodedata

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, update
from sqlmodel import Session, col, select

from app.models import Card, CardState, Direction, Mistake, Module, ReviewLog
from app.services.claude import ClaudeClient, Task

STRESS = "́"
LEECH_LAPSES = 6
VOWELS = "аеёиоуыэюяАЕЁИОУЫЭЮЯ"

# Fields where an apostrophe after a vowel means "stress here".
STRESSABLE_FIELDS = ("ru_stressed", "example_ru", "aspect_partner")

EDITABLE_FIELDS = (
    "ru", "ru_stressed", "en", "example_ru", "example_en", "pos", "gender",
    "aspect", "aspect_partner", "notes", "tags",
)


def normalize(text: str) -> str:
    """Key for duplicate detection: no stress marks, ё folded to е, lowercase, single spaces."""
    text = unicodedata.normalize("NFD", text).replace(STRESS, "")
    text = unicodedata.normalize("NFC", text).lower().replace("ё", "е")
    return " ".join(text.split())


# Latin vowels with an acute accent that models sometimes put inside Russian
# words (купé), mapped to the Cyrillic look-alike that takes a combining stress mark.
_LATIN_ACCENTED = {"á": "а", "é": "е", "ó": "о", "ý": "у", "Á": "А", "É": "Е", "Ó": "О"}
_LATIN_CHARS = "".join(_LATIN_ACCENTED)
_LATIN_IN_CYRILLIC = re.compile(rf"(?<=[а-яёА-ЯЁ])[{_LATIN_CHARS}]|[{_LATIN_CHARS}](?=[а-яёА-ЯЁ])")


def fix_latin_accents(text: str) -> str:
    """купé (Latin é) → купе́ (Cyrillic е + U+0301), only when touching Cyrillic letters."""
    return _LATIN_IN_CYRILLIC.sub(lambda m: _LATIN_ACCENTED[m.group()] + STRESS, text)


def drop_marks_beside_yo(text: str) -> str:
    """A word with ё is stressed on the ё, so any other stress mark in it is a mistake: при́нёс → принёс."""
    return re.sub(r"[\ẃ]+", lambda m: m.group().replace(STRESS, "") if "ё" in m.group().lower() else m.group(), text)


def apply_stress_marks(text: str) -> str:
    """Let you type stress with an apostrophe after the vowel: вокза'л → вокза́л."""
    return drop_marks_beside_yo(re.sub(rf"([{VOWELS}])'", rf"\1{STRESS}", fix_latin_accents(text)))


def clean_tags(tags: str) -> str:
    return " ".join(dict.fromkeys(t.lower() for t in tags.replace(",", " ").split()))


def find_duplicate(session: Session, ru: str, exclude_id: int | None = None) -> Card | None:
    key = normalize(ru)
    for card in session.exec(select(Card).where(Card.id != (exclude_id or -1))).all():
        if normalize(card.ru) == key:
            return card
    return None


def create_card(
    session: Session,
    *,
    source_module: Module = Module.manual,
    source_ref_id: int | None = None,
    stress_verified: bool = False,
    **fields,
) -> Card:
    """Add a card plus its recognition (RU→EN) schedule. Production cards come later (P1.7)."""
    card = Card(source_module=source_module, source_ref_id=source_ref_id, stress_verified=stress_verified)
    apply_fields(card, fields)
    session.add(card)
    session.commit()
    session.add(CardState(card_id=card.id, direction=Direction.recognition))
    session.commit()
    return card


def delete_card(session: Session, card_id: int) -> None:
    """Delete a card with its schedules and review history; mistakes keep their record but lose the link."""
    state_ids = select(CardState.id).where(CardState.card_id == card_id)
    session.exec(delete(ReviewLog).where(col(ReviewLog.card_state_id).in_(state_ids)))
    session.exec(delete(CardState).where(CardState.card_id == card_id))
    session.exec(update(Mistake).where(Mistake.card_id == card_id).values(card_id=None))
    session.exec(delete(Card).where(Card.id == card_id))
    session.commit()


def apply_fields(card: Card, fields: dict) -> None:
    for name in EDITABLE_FIELDS:
        if name not in fields:
            continue
        value = (fields[name] or "").strip()
        if name == "tags":
            card.tags = clean_tags(value)
            continue
        if name in STRESSABLE_FIELDS:
            value = apply_stress_marks(value)
        elif name == "ru":
            value = fix_latin_accents(value)
        setattr(card, name, value or None)
    if not card.ru:
        raise ValueError("Russian text is required")
    if not card.en:
        raise ValueError("English meaning is required")


def search_cards(
    session: Session,
    q: str = "",
    tag: str = "",
    source: str = "",
    leeches: bool = False,
    limit: int = 200,
) -> list[tuple[Card, int]]:
    """Cards matching the filters, newest first, with their worst lapse count.

    Text search ignores stress marks, ё/е and case, so it runs in Python;
    a personal deck of a few thousand cards makes that instant.
    """
    lapses = func.coalesce(func.max(CardState.lapses), 0).label("lapses")
    query = (
        select(Card, lapses)
        .join(CardState, CardState.card_id == Card.id, isouter=True)
        .group_by(Card.id)
        .order_by(col(Card.created_at).desc(), col(Card.id).desc())
    )
    if tag:
        query = query.where(func.instr(" " + Card.tags + " ", f" {tag.lower()} ") > 0)
    if source:
        query = query.where(Card.source_module == source)
    if leeches:
        query = query.having(lapses >= LEECH_LAPSES)
    rows = session.exec(query).all()
    if q.strip():
        key = normalize(q)
        rows = [r for r in rows if key in normalize(f"{r[0].ru} {r[0].en} {r[0].example_ru or ''}")]
    return [(card, n) for card, n in rows[:limit]]


def all_tags(session: Session) -> list[str]:
    tags: set[str] = set()
    for value in session.exec(select(Card.tags)).all():
        tags.update(value.split())
    return sorted(tags)


# --- Claude enrichment -------------------------------------------------------

class CardEnrichment(BaseModel):
    ru_stressed: str = Field(description="The Russian word or phrase with an acute accent (U+0301) after every stressed vowel of each word with 2+ syllables. Never mark ё.")
    en: str = Field(description="Concise English meaning(s), separated by '; '")
    pos: str | None = Field(description="Part of speech: noun, verb, adjective, adverb, phrase, ...")
    gender: str | None = Field(description="m, f or n for nouns; null otherwise")
    aspect: str | None = Field(description="impf or pf for verbs; null otherwise")
    aspect_partner: str | None = Field(description="The aspectual partner verb with stress mark, for verbs; null otherwise")
    example_ru: str = Field(description="A natural, everyday sentence using the word, stress-marked, useful for a traveller in Moscow")
    example_en: str = Field(description="English translation of the example")
    notes: str | None = Field(description="One short note only if genuinely useful: irregular forms, government (e.g. + dat.), stress shifts, or a common collocation")


ENRICH_SYSTEM = """You help an English-speaking intermediate learner of Russian build flashcards.
Given a Russian word or phrase (and possibly the learner's English gloss), fill in the card details.

Rules:
- Stress marks: put U+0301 COMBINING ACUTE ACCENT directly after the stressed vowel. Mark every word of two or more syllables. Do not mark ё (it is always stressed) or one-syllable words.
- Keep the learner's spelling of the headword; fix it only if it's clearly misspelt.
- For verbs give the aspect and its partner (e.g. говори́ть → сказа́ть). Verbs of motion: note the unidirectional/multidirectional pair instead when that's more useful.
- The example sentence must be natural modern Russian at roughly B1 level, ideally something a family visiting Moscow would say or hear.
- Explanations and glosses in English.

Punctuation: never use em dashes (—) in English text; use a comma, colon, full stop or parentheses instead. Inside Russian sentences, keep the dash only where Russian grammar requires it (e.g. Москва́ — столи́ца)."""


def enrich(client: ClaudeClient, ru: str, en: str = "") -> CardEnrichment:
    prompt = f"Russian: {ru.strip()}"
    if en.strip():
        prompt += f"\nLearner's English gloss: {en.strip()}"
    return client.ask_structured(Task.enrichment, ENRICH_SYSTEM, prompt, CardEnrichment, max_tokens=2000)

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

KINDS = ("word", "form", "stress", "chunk", "cloze")
KIND_LABELS = {"form": "Form in context", "stress": "Stress shift", "chunk": "Phrase", "cloze": "Cloze"}

EDITABLE_FIELDS = (
    "ru", "ru_stressed", "en", "example_ru", "example_en", "pos", "gender",
    "aspect", "aspect_partner", "notes", "tags",
)


def normalize(text: str) -> str:
    """Key for duplicate detection: no stress marks, ё folded to е, lowercase, single spaces."""
    text = unicodedata.normalize("NFD", text).replace(STRESS, "")
    text = unicodedata.normalize("NFC", text).lower().replace("ё", "е")
    return " ".join(text.split())


def strip_stress(text: str) -> str:
    """Remove stress marks, keeping everything else (ё stays ё)."""
    return unicodedata.normalize("NFC", unicodedata.normalize("NFD", text).replace(STRESS, ""))


# Latin vowels with an acute accent that models sometimes put inside Russian
# words (купé), mapped to the Cyrillic look-alike that takes a combining stress mark.
_LATIN_ACCENTED = {"á": "а", "é": "е", "ó": "о", "ý": "у", "Á": "А", "É": "Е", "Ó": "О"}
_LATIN_CHARS = "".join(_LATIN_ACCENTED)
_LATIN_IN_CYRILLIC = re.compile(rf"(?<=[а-яёА-ЯЁ])[{_LATIN_CHARS}]|[{_LATIN_CHARS}](?=[а-яёА-ЯЁ])")


def fix_latin_accents(text: str) -> str:
    """купé (Latin é) → купе́ (Cyrillic е + U+0301), only when touching Cyrillic letters.
    A combining mark that already followed the Latin letter is not doubled: Краснá́я → Красна́я."""
    fixed = _LATIN_IN_CYRILLIC.sub(lambda m: _LATIN_ACCENTED[m.group()] + STRESS, text)
    return re.sub(f"{STRESS}{{2,}}", STRESS, fixed)


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
    kind: str | None = None,
    **fields,
) -> Card:
    """Add a card plus its recognition (RU→EN) schedule. Production cards come later (P1.7).

    Without an explicit kind, a multi-word `ru` becomes a chunk and anything else a word.
    """
    card = Card(source_module=source_module, source_ref_id=source_ref_id, stress_verified=stress_verified)
    apply_fields(card, fields)
    if kind is None:
        kind = "chunk" if len(card.ru.split()) > 1 else "word"
    elif kind not in KINDS:
        raise ValueError(f"Unknown card kind: {kind}")
    card.kind = kind
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
    kind: str = "",
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
    if kind:
        query = query.where(Card.kind == kind)
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

class FormSuggestion(BaseModel):
    ru: str = Field(description="The form in a short natural context, with stress marks, e.g. «из Москвы́»")
    en: str = Field(description="English meaning of the whole phrase, e.g. 'from Moscow'")
    note: str = Field(description="Names the form and why it is used, e.g. 'genitive after из'")


class StressShift(BaseModel):
    base: str = Field(description="The dictionary form with stress mark, e.g. «рука́»")
    shifted: str = Field(description="The form where the stress moves, with stress mark, e.g. «ру́ку»")
    en: str = Field(description="English gloss naming the form, e.g. 'hand (accusative)'")
    note: str = Field(description="One short sentence on the shift, e.g. 'stress moves to the stem in the accusative singular'")


class CardEnrichment(BaseModel):
    ru_stressed: str = Field(description="The Russian word or phrase with an acute accent (U+0301) after every stressed vowel of each word with 2+ syllables. Never mark ё.")
    en: str = Field(description="Concise English meaning(s), separated by '; '")
    pos: str | None = Field(description="Part of speech: noun, verb, adjective, adverb, phrase, ...")
    gender: str | None = Field(description="m, f or n for nouns; null otherwise")
    aspect: str | None = Field(description="impf or pf for verbs; null otherwise")
    aspect_partner: str | None = Field(description="The aspectual partner verb with stress mark, for verbs; null otherwise")
    example_ru: str = Field(description="A natural, everyday sentence using the word, stress-marked, useful for a traveler in Moscow")
    example_en: str = Field(description="English translation of the example")
    notes: str | None = Field(description="One short note only if genuinely useful: irregular forms, government (e.g. + dat.), stress shifts, or a common collocation")
    forms: list[FormSuggestion] = Field(default_factory=list, description="0 to 3 of the forms a traveler will meet most, in a short context; empty when it adds nothing")
    stress_shift: StressShift | None = Field(default=None, description="Only for genuinely mobile stress in a form a learner will use; otherwise null")


ENRICH_SYSTEM = """You help an English-speaking intermediate learner of Russian build flashcards.
Given a Russian word or phrase (and possibly the learner's English gloss), fill in the card details.

Rules:
- Stress marks: put U+0301 COMBINING ACUTE ACCENT directly after the stressed vowel. Mark every word of two or more syllables. Do not mark ё (it is always stressed) or one-syllable words.
- Keep the learner's spelling of the headword; fix it only if it's clearly misspelt.
- For verbs give the aspect and its partner (e.g. говори́ть → сказа́ть). Verbs of motion: note the unidirectional/multidirectional pair instead when that's more useful.
- The example sentence must be natural modern Russian at roughly B1 level, ideally something a family visiting Moscow would say or hear.
- Explanations and glosses in English.
- forms: suggest 0 to 3 extra cards for the forms of this word a traveler will actually meet most often, each in a short natural context (a preposition plus the form, or a verb plus its object), e.g. «в Москве́» (in Moscow, prepositional after в) and «из Москвы́» (from Moscow, genitive after из). Put the headword's own form first only if it is a useful chunk. Do not repeat the form used for stress_shift. Give the English meaning of the whole phrase and a short note naming the form and why it is used. Mark stress in every word of two or more syllables. Return an empty list for words where this adds nothing: adverbs, particles, set phrases and indeclinable words.
- stress_shift: only when the word has genuinely mobile stress in a form the learner will really use, fill in base (dictionary form), shifted (the form where stress moves), en (gloss naming the form, e.g. "hand (accusative)") and note (one short sentence). Example: base «рука́», shifted «ру́ку». Use null for words with fixed stress or where the shift only occurs in rare forms.

Punctuation: never use em dashes (—) in English text; use a comma, colon, full stop or parentheses instead. Inside Russian sentences, keep the dash only where Russian grammar requires it (e.g. Москва́ — столи́ца)."""


def enrich(client: ClaudeClient, ru: str, en: str = "", context: str = "") -> CardEnrichment:
    """`context`: a sentence the learner met the word in (sentence mining); it becomes the example."""
    prompt = f"Russian: {ru.strip()}"
    if en.strip():
        prompt += f"\nLearner's English gloss: {en.strip()}"
    if context.strip():
        prompt += (f"\nThe learner met this word in the sentence: «{context.strip()}». Use exactly that sentence, "
                   "with stress marks added, as example_ru (fix nothing else in it), translate it naturally as example_en, "
                   "and give the meaning that fits it first in en.")
    result = client.ask_structured(Task.enrichment, ENRICH_SYSTEM, prompt, CardEnrichment, max_tokens=2000)
    # Claude sometimes writes stress with a Latin accented letter (опáздывать); fix it before any preview shows it.
    return result.model_copy(update={
        name: fix_latin_accents(value) for name, value in result.model_dump().items() if isinstance(value, str)
    })


# --- Suggested extra cards ------------------------------------------------------

def drop_stress_overlap(forms: list[dict], stress: dict | None) -> list[dict]:
    """Drop form suggestions that contain the stress-shift's shifted word (the stress card already covers it)."""
    shifted = normalize(stress.get("shifted", "")) if stress else ""
    if not shifted:
        return forms
    return [f for f in forms if shifted not in re.findall(r"[\w-]+", normalize(f.get("ru", "")))]


def create_suggested_cards(
    session: Session,
    *,
    headword: str,
    source_module: Module,
    forms: list[dict],
    stress: dict | None = None,
    extra_tags: str = "",
) -> int:
    """Create form / stress-shift cards chosen from an enrichment, skipping duplicates. Returns how many were added.

    `forms` items need ru, en, note; `stress` needs base, shifted, en, note.
    """
    added = 0
    forms = drop_stress_overlap(forms, stress)

    def add(kind: str, stressed: str, en: str, note: str, tag: str, head: str) -> None:
        nonlocal added
        stressed, en = (stressed or "").strip(), (en or "").strip()
        ru = strip_stress(stressed)
        if not ru or not en or find_duplicate(session, ru):
            return
        notes = (note or "").strip().rstrip(".")
        notes = f"{notes} (headword: {head})" if notes else f"Headword: {head}"
        create_card(
            session, kind=kind, source_module=source_module, ru=ru, ru_stressed=stressed, en=en,
            notes=notes, tags=f"{tag} {extra_tags}",
        )
        added += 1

    for f in forms:
        add("form", f.get("ru", ""), f.get("en", ""), f.get("note", ""), "form", headword)
    if stress:
        base = (stress.get("base") or "").strip() or headword
        add("stress", stress.get("shifted", ""), stress.get("en", ""), stress.get("note", ""), "stress", base)
    return added

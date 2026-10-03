"""Travel starter deck generation and the paste-a-list importer.

Both flows stage their items in a JSON file under the data dir so nothing
reaches the deck until the learner has reviewed it.
"""

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field
from sqlmodel import Session

from app.config import get_config
from app.models import Card, Module
from app.services import cards as card_service
from app.services.claude import ClaudeClient, ClaudeError, Task

ENRICH_CAP = 60
ENRICH_SLEEP = 0.5  # seconds between enrichment calls
CARD_FIELDS = (
    "ru", "ru_stressed", "en", "pos", "gender", "aspect", "aspect_partner",
    "example_ru", "example_en", "notes",
)


@dataclass(frozen=True)
class Topic:
    slug: str
    title: str
    count: int
    focus: str


TOPICS = [
    Topic("greetings", "Greetings & politeness", 15, "greetings, goodbyes, please/thank you/sorry, excuse me, asking someone to repeat or speak slowly, 'I don't understand'"),
    Topic("transport", "Metro, transport & taxi", 16, "metro stations and lines, changing trains, tickets and the Troika card, buses, taxis, airports, trains, 'which stop', 'how long'"),
    Topic("food", "Food & restaurants", 18, "ordering, the menu, the bill, tea/coffee, common dishes, allergies, vegetarian, table for several people, kids' meals"),
    Topic("numbers", "Numbers, money & prices", 14, "numbers, 'how much does it cost', rubles, cash/card, change, discounts, telling the time, days of the week"),
    Topic("directions", "Directions & places", 15, "left/right/straight, near/far, 'where is', street/square/bridge, museum, Red Square, the Kremlin, maps"),
    Topic("hotel", "Hotel & accommodation", 14, "booking, check-in/out, a family room, key, wifi, breakfast, towels, noise, problems in the room"),
    Topic("shopping", "Shopping", 14, "shops, markets, souvenirs, sizes, trying on, 'I'll take it', bags, opening hours, returns"),
    Topic("emergency", "Emergencies, health & pharmacy", 15, "help, police, doctor, pharmacy, 'I feel sick', pain, allergies, lost passport/phone, children's medicine"),
    Topic("smalltalk", "Small talk & family", 15, "where we are from, my wife/husband/son/daughter, ages, how long in Moscow, weather, likes/dislikes, 'I speak a little Russian'"),
    Topic("sightseeing", "Sightseeing, tickets & plans", 14, "tickets for several people, museums, theatre, parks, tours, 'what time does it open', photos, plans for the day"),
]
TOPICS_BY_SLUG = {t.slug: t for t in TOPICS}


class StarterItem(BaseModel):
    ru: str = Field(description="The Russian word or phrase, without stress marks")
    ru_stressed: str = Field(description="Same text with U+0301 after the stressed vowel of every word with 2+ syllables; never mark ё")
    en: str = Field(description="Concise English meaning")
    pos: str | None = Field(description="noun, verb, adjective, adverb, phrase, ...")
    gender: str | None = Field(description="m, f or n for nouns; null otherwise")
    aspect: str | None = Field(description="impf or pf for verbs; null otherwise")
    aspect_partner: str | None = Field(description="Aspect partner with stress mark, for verbs; null otherwise")
    example_ru: str = Field(description="Natural B1-level sentence a traveller would say or hear, stress-marked")
    example_en: str = Field(description="English translation of the example")
    notes: str | None = Field(description="One short note only if genuinely useful; otherwise null")


class TopicBatch(BaseModel):
    items: list[StarterItem]


SYSTEM = """You build flashcards for an English-speaking intermediate learner of Russian who is travelling to Moscow with their family.
Produce useful, high-frequency vocabulary and set phrases for the requested topic.

Rules:
- Mix single words and short ready-to-use phrases (roughly 60% words, 40% phrases). No duplicates.
- Use polite register (вы) in phrases unless it is clearly for a child.
- Stress marks: U+0301 COMBINING ACUTE ACCENT directly after the stressed vowel, on every word of two or more syllables. Never mark ё or one-syllable words.
- For verbs give the aspect and partner; give gender for nouns.
- Example sentences: natural modern Russian, stress-marked, ideally involving a family of travellers.
- Explanations in English.

Punctuation: never use em dashes (—) in English text; use a comma, colon, full stop or parentheses instead. Inside Russian sentences, keep the dash only where Russian grammar requires it (e.g. Москва́ — столи́ца)."""


def pending_path(name: str = "starter") -> Path:
    return get_config().data_dir / f"{name}_pending.json"


def load_pending(name: str = "starter") -> dict:
    try:
        return json.loads(pending_path(name).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def save_pending(data: dict, name: str = "starter") -> None:
    path = pending_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def clear_pending(name: str = "starter") -> None:
    pending_path(name).unlink(missing_ok=True)


def generate_topic(client: ClaudeClient, topic: Topic) -> list[dict]:
    prompt = f"Topic: {topic.title}\nCover: {topic.focus}\nGenerate about {topic.count} cards."
    batch = client.ask_structured(Task.deck_generation, SYSTEM, prompt, TopicBatch, max_tokens=6000)
    items, seen = [], set()
    for item in batch.items:
        key = card_service.normalize(item.ru)
        if key and key not in seen and item.en.strip():
            seen.add(key)
            items.append(item.model_dump())
    return items


def generate_topics(client: ClaudeClient, slugs: list[str], pending: dict) -> str:
    """Generate each topic into `pending["topics"]`; returns an error message ('' if all worked)."""
    topics = pending.setdefault("topics", {})
    for slug in slugs:
        try:
            topics[slug] = generate_topic(client, TOPICS_BY_SLUG[slug])
        except ClaudeError as e:
            return f"{TOPICS_BY_SLUG[slug].title}: {e}"
    return ""


@dataclass
class ReviewRow:
    key: str
    item: dict
    duplicate: Card | None
    repeat: bool = False  # repeats an earlier item in the same batch


def review_rows(session: Session, items: list[dict], prefix: str, seen: set[str]) -> list[ReviewRow]:
    """Flag items already in the deck, or repeating an earlier item (`seen` is shared across topics)."""
    rows = []
    for i, item in enumerate(items):
        key = card_service.normalize(item["ru"])
        rows.append(ReviewRow(f"{prefix}:{i}", item, card_service.find_duplicate(session, item["ru"]), key in seen))
        seen.add(key)
    return rows


def add_cards(session: Session, items: list[tuple[dict, str]], source: Module) -> int:
    """Create a card per (item, tags), skipping anything already in the deck. Returns how many were added."""
    added = 0
    for item, tags in items:
        if not item.get("ru") or not (item.get("en") or "").strip():
            continue
        if card_service.find_duplicate(session, item["ru"]):
            continue
        fields = {name: item.get(name) or "" for name in CARD_FIELDS}
        card_service.create_card(session, source_module=source, tags=tags, **fields)
        added += 1
    return added


# --- Paste-a-list importer ---------------------------------------------------

SEPARATORS = re.compile(r"\t|\s+[-–—]\s+|\s*;\s*")


def parse_paste(text: str) -> tuple[list[dict], int]:
    """Parse lines of `слово` or `слово - english` (an en or em dash, a tab or `;` also separate). Returns (items, duplicates dropped)."""
    items, seen, dropped = [], set(), 0
    for line in text.splitlines():
        parts = SEPARATORS.split(line.strip(), maxsplit=1)
        ru, en = parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")
        key = card_service.normalize(ru)
        if not key:
            continue
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        items.append({"ru": ru, "en": en})
    return items, dropped


def enrich_items(client: ClaudeClient, items: list[dict], sleep: float | None = None) -> str:
    """Fill in items lacking English via Claude, sequentially and capped. Returns a message ('' if all fine)."""
    sleep = ENRICH_SLEEP if sleep is None else sleep
    todo = [it for it in items if not it["en"]]
    done = 0
    for item in todo[:ENRICH_CAP]:
        if done:
            time.sleep(sleep)
        try:
            result = card_service.enrich(client, item["ru"]).model_dump()
        except ClaudeError as e:
            return f"Stopped after {done} word(s): {e}"
        item.update({k: v for k, v in result.items() if v})
        done += 1
    if len(todo) > ENRICH_CAP:
        return f"Enriched the first {ENRICH_CAP} words; paste the rest again to continue."
    return ""

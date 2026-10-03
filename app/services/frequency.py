"""Frequency deck builder: the next batch of the most common Russian words you don't have yet.

Batches are staged in a JSON file (like the travel starter deck) and only reach
the deck after the learner has reviewed them. Progress through the frequency
list is kept in the `frequency_next_rank` setting.
"""

from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.models import Card, Module, Setting
from app.services import cards as card_service
from app.services import starter
from app.services.claude import ClaudeClient, Task

BATCH_SIZE = 25
RANK_KEY = "frequency_next_rank"
KNOWN_KEY = "frequency_known"
PENDING = "frequency"
EXCLUDE_CAP = 1500  # most recent known words passed to Claude, to keep the prompt small
MAX_FORMS = 2


class FrequencyItem(starter.StarterItem):
    forms: list[card_service.FormSuggestion] = Field(
        default_factory=list,
        description="Up to 2 of the most common forms of this word in a short context, e.g. «в Москве́»; empty if it adds nothing",
    )


class FrequencyBatch(BaseModel):
    items: list[FrequencyItem]


SYSTEM = """You build flashcards for an English-speaking intermediate (B1) learner of Russian who is preparing for a family trip to Moscow.
Given a range of ranks in a Russian frequency list, list the most frequent Russian lemmas in that range, in rough frequency order.

Rules:
- Skip function words an intermediate learner already knows well (basic prepositions, conjunctions, particles, personal pronouns, the numbers 1-10, и, а, но, не, это, etc.) and anything on the learner's already-known list. Keep nouns, verbs, adjectives, adverbs and useful words that a B1 learner may still lack.
- Return exactly the requested number of lemmas. The ranks are approximate; do not repeat a word.
- Dictionary form (infinitive, nominative singular, masculine adjective). `ru` has no stress marks.
- Stress marks: U+0301 COMBINING ACUTE ACCENT directly after the stressed vowel, on every word of two or more syllables. Never mark ё or one-syllable words.
- For verbs give the aspect and its partner; give gender for nouns.
- Example sentences: natural modern everyday Russian at about B1 level, stress-marked.
- forms: for each word give up to 2 of its most frequent forms in a short natural context (e.g. «в Москве́», «из Москвы́»), each with stress marks, an English meaning of the phrase, and a note naming the form (e.g. "genitive after из"). Empty for adverbs, particles and set phrases.
- Explanations in English.

Punctuation: never use em dashes (—) in English text; use a comma, colon, full stop or parentheses instead. Inside Russian sentences, keep the dash only where Russian grammar requires it (e.g. Москва́ — столи́ца)."""


def next_rank(session: Session) -> int:
    row = session.get(Setting, RANK_KEY)
    try:
        return max(1, int(row.value)) if row else 1
    except (TypeError, ValueError):
        return 1


def set_next_rank(session: Session, rank: int) -> None:
    row = session.get(Setting, RANK_KEY)
    if row is None:
        session.add(Setting(key=RANK_KEY, value=rank))
    else:
        row.value = rank
        session.add(row)
    session.commit()


def remembered_known(session: Session) -> list[str]:
    row = session.get(Setting, KNOWN_KEY)
    return [str(k) for k in row.value] if row and isinstance(row.value, list) else []


def remember_known(session: Session, keys: list[str]) -> None:
    merged = list(dict.fromkeys(remembered_known(session) + keys))
    row = session.get(Setting, KNOWN_KEY)
    if row is None:
        session.add(Setting(key=KNOWN_KEY, value=merged))
    else:
        row.value = merged
        session.add(row)
    session.commit()


def known_words(session: Session) -> list[str]:
    """Normalized `ru` of word cards plus words the learner declined (newest last), capped for the prompt."""
    rows = session.exec(select(Card.ru).where(Card.kind == "word").order_by(Card.id)).all()
    deck = [card_service.normalize(ru) for ru in rows if ru]
    keys = list(dict.fromkeys(deck + remembered_known(session)))
    return keys[-EXCLUDE_CAP:]


def generate_batch(session: Session, client: ClaudeClient) -> dict:
    """Ask Claude for the next batch, drop words already in the deck, stage it and advance the rank.

    Raises ClaudeError (and changes nothing) if the call fails.
    """
    start = next_rank(session)
    end = start + BATCH_SIZE - 1
    known = known_words(session)
    prompt = f"Frequency ranks {start} to {end}. Return {BATCH_SIZE} lemmas."
    if known:
        prompt += "\n\nAlready known (do not include):\n" + ", ".join(known)
    batch = client.ask_structured(Task.deck_generation, SYSTEM, prompt, FrequencyBatch, max_tokens=12000)

    declined = set(remembered_known(session))
    items, seen, skipped = [], set(), 0
    for item in batch.items:
        key = card_service.normalize(item.ru)
        if not key or not item.en.strip() or key in seen or key in declined or card_service.find_duplicate(session, item.ru):
            skipped += 1
            continue
        seen.add(key)
        items.append(item.model_dump() | {"forms": [f.model_dump() for f in item.forms[:MAX_FORMS]]})
    pending = {"start": start, "end": end, "items": items, "skipped": skipped}
    starter.save_pending(pending, PENDING)
    set_next_rank(session, end + 1)
    return pending


def discard_batch(session: Session) -> None:
    """Throw the staged batch away; if nothing was generated since, rewind so its ranks come round again."""
    pending = starter.load_pending(PENDING)
    if pending.get("end") is not None and next_rank(session) == pending["end"] + 1:
        set_next_rank(session, pending["start"])
    starter.clear_pending(PENDING)


def add_batch(session: Session, pending: dict, selected: list[str], form_keys: set[str]) -> int:
    """Create cards for the ticked items (keys 'i:N') and their ticked forms (keys 'i:N:M'). Returns cards added in total."""
    added = 0
    items = pending.get("items", [])
    chosen = {k.partition(":")[2] for k in selected}
    declined = [card_service.normalize(it["ru"]) for i, it in enumerate(items) if str(i) not in chosen and it.get("ru")]
    if declined:
        remember_known(session, declined)  # unticked words are already known and won't come back
    for key in selected:
        try:
            item = items[int(key.partition(":")[2])]
        except (ValueError, IndexError):
            continue
        if not item.get("ru") or not (item.get("en") or "").strip():
            continue
        main_added = starter.add_cards(session, [(item, "frequency")], Module.starter)
        added += main_added
        forms = [f for j, f in enumerate(item.get("forms", [])) if f"{key}:{j}" in form_keys]
        if forms:
            added += card_service.create_suggested_cards(
                session, headword=item.get("ru_stressed") or item["ru"], source_module=Module.starter,
                forms=forms, extra_tags="frequency",
            )
    return added

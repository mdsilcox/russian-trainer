"""Cloze cards: fill-in-the-blank cards built from sentences the learner wrote in Russian."""

import re
from dataclasses import dataclass

from sqlmodel import Session, select

from app.models import Card, Module, Story, TranslationAttempt
from app.services import cards as cards_service
from app.services.cards import STRESS

BLANK = "____"

_SENTENCE = re.compile(r"\S.*?(?:[.!?…](?=\s|$)|$)", re.S)
_JOINERS = "-‐‑'’"


@dataclass
class ClozeSource:
    text: str
    story_id: int
    attempt_id: int


def split_sentences(text: str) -> list[str]:
    """Split on . ! ? … followed by whitespace or the end; closing punctuation stays."""
    return [m.group().strip() for m in _SENTENCE.finditer(text or "") if m.group().strip()]


def word_count(sentence: str) -> int:
    """Whitespace-separated tokens containing at least one letter or digit."""
    return sum(1 for token in sentence.split() if any(ch.isalnum() for ch in token))


def sentences(session: Session) -> list[ClozeSource]:
    """Sentences from the latest attempt of each English-source story, newest attempt first."""
    rows = session.exec(
        select(TranslationAttempt).join(Story, Story.id == TranslationAttempt.story_id).where(Story.source_lang == "en")
    ).all()
    latest: dict[int, TranslationAttempt] = {}
    for attempt in rows:
        best = latest.get(attempt.story_id)
        if best is None or (attempt.created_at, attempt.id) > (best.created_at, best.id):
            latest[attempt.story_id] = attempt
    ordered = sorted(latest.values(), key=lambda a: (a.created_at, a.id), reverse=True)
    result: list[ClozeSource] = []
    seen: set[str] = set()
    for attempt in ordered:
        for sentence in split_sentences(attempt.corrected_text or attempt.text):
            if word_count(sentence) < 3 or sentence in seen:
                continue
            seen.add(sentence)
            result.append(ClozeSource(text=sentence, story_id=attempt.story_id, attempt_id=attempt.id))
    return result


def _fold(text: str) -> tuple[str, list[int]]:
    """Lowercase, no stress marks, ё as е; plus, for each folded char, its index in the original."""
    chars: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if ch == STRESS:
            continue
        for out in ch.lower().replace("ё", "е"):
            chars.append(out)
            index.append(i)
    return "".join(chars), index


def _joined_before(folded: str, pos: int) -> bool:
    """True when the char before `pos` is a letter/digit, or a hyphen/apostrophe attached to one."""
    if pos <= 0:
        return False
    prev = folded[pos - 1]
    if prev.isalnum():
        return True
    return prev in _JOINERS and pos >= 2 and folded[pos - 2].isalnum()


def _joined_after(folded: str, pos: int) -> bool:
    if pos >= len(folded):
        return False
    nxt = folded[pos]
    if nxt.isalnum():
        return True
    return nxt in _JOINERS and pos + 1 < len(folded) and folded[pos + 1].isalnum()


def _locate(sentence: str, word: str) -> tuple[int, int]:
    """(start, end) of the first whole-word occurrence of `word` in `sentence`."""
    word = cards_service.apply_stress_marks((word or "").strip())
    key = cards_service.normalize(word)
    if not key:
        raise ValueError("Type the word you want to blank out.")
    folded, index = _fold(sentence)
    pattern = r"\s+".join(re.escape(part) for part in key.split(" "))
    for match in re.finditer(rf"(?=({pattern}))", folded):
        start = match.start()
        end = start + len(match.group(1))
        if _joined_before(folded, start) or _joined_after(folded, end):
            continue
        orig_start = index[start]
        orig_end = index[end - 1] + 1
        while orig_end < len(sentence) and sentence[orig_end] == STRESS:
            orig_end += 1
        return orig_start, orig_end
    raise ValueError(f"The word ‘{word}’ is not in this sentence. Pick a whole word from it.")


def split_cloze(sentence: str, word: str) -> tuple[str, str, str]:
    """(text before, answer as written, text after) around the first whole-word match."""
    start, end = _locate(sentence, word)
    return sentence[:start], sentence[start:end], sentence[end:]


def make_cloze(sentence: str, word: str) -> tuple[str, str]:
    """(blanked sentence, answer as written). Raises ValueError when the word is not in the sentence."""
    before, answer, after = split_cloze(sentence, word)
    return before + BLANK + after, answer


def create_cloze_card(session: Session, sentence: str, word: str, en: str, story_id: int | None = None) -> Card:
    sentence = (sentence or "").strip()
    if not (en or "").strip():
        raise ValueError("Add the English meaning of the word.")
    _, answer = make_cloze(sentence, word)
    sentence_key = cards_service.normalize(cards_service.apply_stress_marks(sentence))
    answer_key = cards_service.normalize(answer)
    for card in session.exec(select(Card).where(Card.kind == "cloze")).all():
        if (
            cards_service.normalize(card.example_ru or "") == sentence_key
            and cards_service.normalize(card.ru) == answer_key
        ):
            raise ValueError("You already have a cloze card for this word in this sentence.")
    return cards_service.create_card(
        session,
        kind="cloze",
        source_module=Module.story,
        source_ref_id=story_id,
        ru=cards_service.strip_stress(answer),
        ru_stressed=answer,
        example_ru=sentence,
        en=en,
    )


def cloze_sentence_keys(session: Session) -> set[str]:
    """Normalized sentences that already have a cloze card."""
    cards = session.exec(select(Card).where(Card.kind == "cloze")).all()
    return {cards_service.normalize(c.example_ru or "") for c in cards}

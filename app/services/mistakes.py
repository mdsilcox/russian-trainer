"""Mistake router: one place where every module reports mistakes.

- Every mistake is logged (it feeds the dashboard and, later, drills).
- Vocabulary-type mistakes (wrong word, unnatural phrase, stress, spelling)
  also become flashcards, using the sentence from your own text as the example.
- Grammar mistakes (cases, aspect, motion verbs, ...) are left for drills.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from sqlmodel import Session, col, select

from app.models import Card, Category, Mistake, Module, ReviewLog, CardState, Story, TranslationAttempt
from app.services import cards as card_service
from app.services.feedback import CATEGORY_LABELS, Feedback, russian_text

CARD_CATEGORIES = {Category.word_choice, Category.idiom, Category.stress, Category.spelling}
DRILL_CATEGORIES = set(Category) - CARD_CATEGORIES
LOGGED_SEVERITIES = {"error", "unnatural"}
MAX_AUTO_CARDS = 8

_SENTENCE = re.compile(r"[^.!?…\n]*[.!?…]?", re.UNICODE)


def strip_stress(text: str) -> str:
    text = card_service.fix_latin_accents(text)
    return unicodedata.normalize("NFC", unicodedata.normalize("NFD", text).replace(card_service.STRESS, ""))


def sentence_containing(text: str, phrase: str) -> str | None:
    """The sentence of `text` that contains `phrase`, trimmed."""
    if not phrase.strip():
        return None
    for match in _SENTENCE.finditer(text):
        sentence = match.group().strip()
        if phrase.strip() in sentence:
            return sentence
    return None


@dataclass
class RouteResult:
    mistakes: list[Mistake] = field(default_factory=list)
    new_cards: list[Card] = field(default_factory=list)
    linked_cards: list[Card] = field(default_factory=list)  # already in the deck

    @property
    def drill_mistakes(self) -> list[Mistake]:
        return [m for m in self.mistakes if m.category in DRILL_CATEGORIES]


def log_mistake(
    session: Session,
    result: RouteResult,
    *,
    module: Module,
    ref_id: int | None,
    category: Category,
    subcategory: str | None,
    wrong: str,
    right: str,
    explanation: str | None,
    example_ru: str | None = None,
    make_card: bool = True,
    topic: str | None = None,
) -> Mistake:
    """Record one mistake; vocabulary-type ones also get (or reuse) a card."""
    mistake = Mistake(
        module=module, ref_id=ref_id, category=category, subcategory=subcategory or None,
        wrong=wrong, right=right, explanation=explanation, topic=topic,
    )
    if make_card and category in CARD_CATEGORIES:
        card = card_service.find_duplicate(session, right)
        if card is not None:
            result.linked_cards.append(card)
        elif len(result.new_cards) < MAX_AUTO_CARDS:
            card = card_service.create_card(
                session,
                source_module=module,
                source_ref_id=ref_id,
                ru=strip_stress(right),
                ru_stressed=right if card_service.STRESS in right else "",
                en=f"Not “{wrong}”. {explanation or ''}".strip(),
                example_ru=example_ru or "",
                notes=CATEGORY_LABELS[category],
                tags=f"mistake {category.value}",
            )
            result.new_cards.append(card)
        mistake.card_id = card.id if card else None
    session.add(mistake)
    session.commit()
    result.mistakes.append(mistake)
    return mistake


def route_story_feedback(session: Session, story: Story, attempt: TranslationAttempt, feedback: Feedback) -> RouteResult:
    """Log the mistakes and vocab from one feedback run. Re-running replaces the attempt's earlier mistakes."""
    clear_attempt_mistakes(session, attempt.id)
    result = RouteResult()
    original = russian_text(story, attempt)
    for issue in feedback.issues:
        if issue.severity not in LOGGED_SEVERITIES:
            continue
        example = sentence_containing(feedback.corrected_text, issue.right) or sentence_containing(original, issue.wrong)
        log_mistake(
            session, result, module=Module.story, ref_id=attempt.id, category=Category(issue.category),
            subcategory=issue.subcategory, wrong=issue.wrong, right=issue.right,
            explanation=issue.explanation, example_ru=example,
        )
    for item in feedback.vocab:
        if len(result.new_cards) >= MAX_AUTO_CARDS:
            break
        existing = card_service.find_duplicate(session, item.ru)
        if existing:
            result.linked_cards.append(existing)
            continue
        result.new_cards.append(
            card_service.create_card(
                session, source_module=Module.story, source_ref_id=attempt.id,
                ru=strip_stress(item.ru), ru_stressed=item.ru, en=item.en,
                example_ru=item.example_ru, example_en=item.example_en, notes=item.why, tags="story vocab",
            )
        )
    return result


def clear_attempt_mistakes(session: Session, attempt_id: int) -> None:
    for mistake in session.exec(
        select(Mistake).where(Mistake.module == Module.story, Mistake.ref_id == attempt_id)
    ).all():
        session.delete(mistake)
    session.commit()


def attempt_summary(session: Session, attempt_id: int) -> RouteResult:
    """What an attempt's feedback has already produced, for redisplaying the panel."""
    mistakes = list(
        session.exec(select(Mistake).where(Mistake.module == Module.story, Mistake.ref_id == attempt_id)).all()
    )
    new_cards = list(
        session.exec(
            select(Card).where(Card.source_module == Module.story, Card.source_ref_id == attempt_id).order_by(col(Card.id))
        ).all()
    )
    own = {c.id for c in new_cards}
    linked_ids = {m.card_id for m in mistakes if m.card_id and m.card_id not in own}
    linked = [session.get(Card, i) for i in sorted(linked_ids)]
    return RouteResult(mistakes=mistakes, new_cards=new_cards, linked_cards=[c for c in linked if c])


def match_issues(mistakes: list[Mistake], issues: list) -> dict[int, Mistake]:
    """Map issue index -> its logged Mistake, matching on (wrong, right) in order."""
    pool = list(mistakes)
    found: dict[int, Mistake] = {}
    for i, issue in enumerate(issues):
        for m in pool:
            if m.wrong == issue.wrong and m.right == issue.right:
                found[i] = m
                pool.remove(m)
                break
    return found


def record_fix_attempt(session: Session, mistake_id: int, correct: bool) -> Mistake | None:
    """Store the outcome of one "Your fix" try. Returns None if it isn't a story mistake."""
    mistake = session.get(Mistake, mistake_id)
    if mistake is None or mistake.module != Module.story:
        return None
    mistake.fix_attempts = (mistake.fix_attempts or 0) + 1
    if correct:
        mistake.self_corrected = True
    elif mistake.self_corrected is None:
        mistake.self_corrected = False
    session.add(mistake)
    session.commit()
    session.refresh(mistake)
    return mistake


def discard_auto_card(session: Session, card_id: int) -> bool:
    """The "don't make a card" override: delete an auto-created card you haven't studied yet.

    Mistakes keep their record. Returns False if the card isn't an untouched auto-card.
    """
    card = session.get(Card, card_id)
    if card is None or card.source_module not in (Module.story, Module.drill, Module.scenario):
        return False
    reviewed = session.exec(
        select(ReviewLog.id).join(CardState, CardState.id == ReviewLog.card_state_id).where(CardState.card_id == card_id)
    ).first()
    if reviewed:
        return False
    card_service.delete_card(session, card_id)
    return True

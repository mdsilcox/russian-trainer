from datetime import datetime, timezone

import fsrs
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from app.db import get_session
from app.models import Card, CardState, Conversation, Lesson, Module, Scenario, Story, TranslationAttempt
from app.services import cards as cards_service
from app.services import cloze, srs
from app.web import templates

router = APIRouter(prefix="/review")

RATINGS = [(fsrs.Rating.Again, "Again"), (fsrs.Rating.Hard, "Hard"), (fsrs.Rating.Good, "Good"), (fsrs.Rating.Easy, "Easy")]


def source_label(session: Session, card: Card) -> str | None:
    """Where a card came from, e.g. "from your story ‘Поезд’"."""
    if card.source_module == Module.story and card.source_ref_id:
        # Cloze cards point at the story; cards from a story's mistakes point at the translation attempt.
        if card.kind == "cloze":
            story = session.get(Story, card.source_ref_id)
        else:
            attempt = session.get(TranslationAttempt, card.source_ref_id)
            story = attempt and session.get(Story, attempt.story_id)
        return f"from your story ‘{story.title}’" if story else "from one of your stories"
    if card.source_module == Module.scenario and card.source_ref_id:
        conversation = session.get(Conversation, card.source_ref_id)
        scenario = conversation and session.get(Scenario, conversation.scenario_id)
        return f"from the ‘{scenario.title}’ role-play" if scenario else "from a role-play"
    if card.source_module == Module.drill:
        return "from a grammar drill"
    if card.source_module == Module.starter:
        return "travel starter deck"
    if card.source_module == Module.tutor and card.source_ref_id:
        lesson = session.get(Lesson, card.source_ref_id)
        return f"from your lesson ‘{lesson.topic}’" if lesson else "from a tutor lesson"
    return None


def cloze_context(card: Card) -> dict:
    """What the review screen needs for a cloze card: the blanked sentence and the parts around the answer."""
    try:
        before, answer, after = cloze.split_cloze(card.example_ru or "", card.ru_stressed or card.ru)
    except ValueError:
        return {"blanked": cloze.BLANK, "parts": None}
    return {"blanked": before + cloze.BLANK + after, "parts": (before, answer, after)}


@router.get("", response_class=HTMLResponse)
def review_page(request: Request, session: Session = Depends(get_session)):
    now = datetime.now(timezone.utc)
    queue = srs.build_queue(session, now)
    context: dict = {"remaining": len(queue)}
    if not queue:
        next_due = srs.next_learning_due(session, now)
        if next_due:
            context["wait_seconds"] = max(1, int((next_due - now).total_seconds()))
    else:
        cs = queue[0]
        card = session.get(Card, cs.card_id)
        scheduler = srs.make_scheduler(session)
        intervals = srs.preview_intervals(scheduler, cs, now)
        context |= {
            "cs": cs,
            "card": card,
            "production": cs.direction == srs.Direction.production,
            "source": source_label(session, card),
            "ratings": [(int(r), label, srs.format_interval(intervals[int(r)])) for r, label in RATINGS],
            "new_left": sum(1 for c in queue if c.state == srs.NEW),
            "kind_labels": cards_service.KIND_LABELS,
            "is_leech": any(c.id == card.id for c in srs.leeches(session)),
        }
        if card.kind == "cloze":
            context["cloze"] = cloze_context(card)
    return templates.TemplateResponse(request, "review.html", context)


@router.post("/{card_state_id}")
def rate(
    card_state_id: int,
    rating: int = Form(...),
    duration_ms: int | None = Form(None),
    session: Session = Depends(get_session),
):
    cs = session.get(CardState, card_state_id)
    if cs is None:
        raise HTTPException(status_code=404, detail="Card not found")
    if rating not in (1, 2, 3, 4):
        raise HTTPException(status_code=422, detail="Rating must be 1-4")
    srs.review(session, cs, fsrs.Rating(rating), duration_ms=duration_ms)
    srs.maybe_unlock_production(session, cs)
    return RedirectResponse("/review", status_code=303)

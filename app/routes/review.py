from datetime import datetime, timezone

import fsrs
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from app.db import get_session
from app.models import Card, CardState, Conversation, Module, Scenario, Story
from app.services import srs
from app.web import templates

router = APIRouter(prefix="/review")

RATINGS = [(fsrs.Rating.Again, "Again"), (fsrs.Rating.Hard, "Hard"), (fsrs.Rating.Good, "Good"), (fsrs.Rating.Easy, "Easy")]


def source_label(session: Session, card: Card) -> str | None:
    """Where a card came from, e.g. "from your story ‘Поезд’"."""
    if card.source_module == Module.story and card.source_ref_id:
        story = session.get(Story, card.source_ref_id)
        return f"from your story ‘{story.title}’" if story else "from one of your stories"
    if card.source_module == Module.scenario and card.source_ref_id:
        conversation = session.get(Conversation, card.source_ref_id)
        scenario = conversation and session.get(Scenario, conversation.scenario_id)
        return f"from the ‘{scenario.title}’ role-play" if scenario else "from a role-play"
    if card.source_module == Module.drill:
        return "from a grammar drill"
    if card.source_module == Module.starter:
        return "travel starter deck"
    return None


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
        }
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

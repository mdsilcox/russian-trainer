from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from app.db import get_session
from app.models import Story, TranslationAttempt
from app.services import feedback as feedback_service
from app.services import mistakes as mistake_service
from app.services import workshop
from app.services.claude import ClaudeClient, ClaudeError
from app.web import templates

router = APIRouter(prefix="/workshop")


def _story(session: Session, story_id: int) -> Story:
    story = session.get(Story, story_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")
    return story


@router.get("", response_class=HTMLResponse)
def story_list(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(
        request, "workshop/list.html", {"rows": workshop.list_stories(session), "langs": workshop.LANGS}
    )


@router.get("/new", response_class=HTMLResponse)
def new_story_form(request: Request):
    return templates.TemplateResponse(request, "workshop/new.html", {"v": {"source_lang": "en"}, "error": ""})


@router.post("/new", response_class=HTMLResponse)
def create_story(
    request: Request,
    title: str = Form(""),
    source_lang: str = Form("en"),
    source_text: str = Form(""),
    translation: str = Form(""),
    session: Session = Depends(get_session),
):
    try:
        story = workshop.create_story(session, title, source_lang, source_text, translation)
    except ValueError as e:
        values = {"title": title, "source_lang": source_lang, "source_text": source_text, "translation": translation}
        return templates.TemplateResponse(
            request, "workshop/new.html", {"v": values, "error": str(e)}, status_code=422
        )
    return RedirectResponse(f"/workshop/{story.id}", status_code=303)


@router.get("/import", response_class=HTMLResponse)
def import_form(request: Request):
    return templates.TemplateResponse(
        request, "workshop/import.html", {"text": "", "template": workshop.IMPORT_TEMPLATE, "errors": [], "preview": None}
    )


@router.post("/import", response_class=HTMLResponse)
def import_stories(
    request: Request,
    text: str = Form(""),
    confirm: str = Form(""),
    session: Session = Depends(get_session),
):
    parsed, errors = workshop.parse_import(text)
    if confirm and parsed and not errors:
        workshop.import_stories(session, parsed)
        return RedirectResponse(f"/workshop?imported={len(parsed)}", status_code=303)
    return templates.TemplateResponse(
        request,
        "workshop/import.html",
        {"text": text, "template": workshop.IMPORT_TEMPLATE, "errors": errors, "preview": parsed, "langs": workshop.LANGS},
    )


def feedback_context(session: Session, story: Story, attempt: TranslationAttempt | None, error: str = "") -> dict:
    """Everything the feedback panel needs for one attempt."""
    fb = feedback_service.load(attempt) if attempt else None
    context = {"story": story, "attempt": attempt, "fb": fb, "feedback_error": error}
    if fb:
        routed = mistake_service.attempt_summary(session, attempt.id)
        drill_labels = sorted({feedback_service.CATEGORY_LABELS[m.category] for m in routed.drill_mistakes})
        context |= {"routed": routed, "drill_labels": drill_labels}
        russian = feedback_service.russian_text(story, attempt)
        segments, unplaced = feedback_service.annotate(russian, fb.issues)
        context |= {
            "segments": segments,
            "unplaced": unplaced,
            "groups": feedback_service.grouped_issues(fb),
            "correction_diff": workshop.word_diff(russian, fb.corrected_text),
            "labels": feedback_service.CATEGORY_LABELS,
        }
    return context


@router.get("/{story_id}", response_class=HTMLResponse)
def story_page(request: Request, story_id: int, session: Session = Depends(get_session)):
    story = _story(session, story_id)
    attempts = workshop.attempts_for(session, story_id)
    diffs = {
        later.id: workshop.word_diff(earlier.text, later.text) for earlier, later in zip(attempts, attempts[1:])
    }
    latest = attempts[-1] if attempts else None
    return templates.TemplateResponse(
        request,
        "workshop/story.html",
        {
            "attempts": attempts,
            "latest": latest,
            "diffs": diffs,
            "target_lang": workshop.other_lang(story.source_lang),
            "langs": workshop.LANGS,
            "issue_counts": {a.id: workshop.issue_counts(a) for a in attempts},
        }
        | feedback_context(session, story, latest),
    )


@router.post("/{story_id}/attempts/{attempt_id}/feedback", response_class=HTMLResponse)
def get_feedback(request: Request, story_id: int, attempt_id: int, session: Session = Depends(get_session)):
    story = _story(session, story_id)
    attempt = session.get(TranslationAttempt, attempt_id)
    if attempt is None or attempt.story_id != story_id:
        raise HTTPException(status_code=404, detail="Attempt not found")
    error = ""
    try:
        result = feedback_service.request_feedback(session, ClaudeClient(session), story, attempt)
        mistake_service.route_story_feedback(session, story, attempt, result)
    except ClaudeError as e:
        error = str(e)
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request, "workshop/_feedback.html", feedback_context(session, story, attempt, error)
        )
    return RedirectResponse(f"/workshop/{story_id}#feedback", status_code=303)


@router.post("/cards/{card_id}/discard", response_class=HTMLResponse)
def discard_card(request: Request, card_id: int, session: Session = Depends(get_session)):
    """"Don't make a card": removes an auto-created card you haven't reviewed yet."""
    if not mistake_service.discard_auto_card(session, card_id):
        raise HTTPException(status_code=409, detail="This card has been reviewed or wasn't auto-created")
    if request.headers.get("HX-Request"):
        return HTMLResponse('<li class="muted">Removed from your deck.</li>')
    return RedirectResponse(request.headers.get("referer", "/workshop"), status_code=303)


@router.post("/{story_id}/attempts")
def submit_attempt(story_id: int, text: str = Form(""), session: Session = Depends(get_session)):
    story = _story(session, story_id)
    try:
        workshop.add_attempt(session, story, text)
    except ValueError:
        return RedirectResponse(f"/workshop/{story_id}?error=empty", status_code=303)
    return RedirectResponse(f"/workshop/{story_id}#latest", status_code=303)


@router.post("/{story_id}/delete")
def delete_story(story_id: int, session: Session = Depends(get_session)):
    _story(session, story_id)
    workshop.delete_story(session, story_id)
    return RedirectResponse("/workshop", status_code=303)

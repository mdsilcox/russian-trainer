from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app.db import get_session
from app.models import Module
from app.services import cards as card_service
from app.services import shelf as shelf_service
from app.services.claude import ClaudeClient, ClaudeError
from app.web import templates

router = APIRouter(prefix="/shelf")

MINE_FIELDS = card_service.EDITABLE_FIELDS


def totals(session: Session) -> dict:
    now = datetime.now(timezone.utc)
    return {"week": shelf_service.this_week(session, now), "month": shelf_service.input_minutes(session, 30, now)}


def _log_response(request: Request, session: Session, *, error: str = "", ok: str = "", status: int = 200):
    return templates.TemplateResponse(
        request, "shelf/_log_result.html", {"error": error, "ok": ok, "totals": totals(session)}, status_code=status
    )


@router.get("", response_class=HTMLResponse)
def index(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(
        request,
        "shelf/index.html",
        {
            "levels": shelf_service.by_level(),
            "totals": totals(session),
            "kinds": shelf_service.KINDS,
            "kind_labels": shelf_service.KIND_LABELS,
            "shelf": shelf_service.items(),
        },
    )


@router.post("/log", response_class=HTMLResponse)
def log(
    request: Request,
    minutes: str = Form(""),
    kind: str = Form(""),
    title: str = Form(""),
    slug: str = Form(""),
    session: Session = Depends(get_session),
):
    """HTMX: log minutes of input; the reply updates the weekly total out of band."""
    try:
        if not minutes.strip().isdigit():
            raise ValueError(f"Minutes must be a whole number from 1 to {shelf_service.MAX_MINUTES}.")
        entry = shelf_service.log_minutes(session, int(minutes), kind, title, slug or None)
    except ValueError as e:
        return _log_response(request, session, error=str(e), status=422)
    return _log_response(request, session, ok=f"Logged {entry.minutes} min: {entry.title}")


# --- Sentence mining ------------------------------------------------------------------

def _source(slug: str, text: str) -> tuple[str, str]:
    """(source title, tag slug) for the chosen shelf item or the typed source."""
    item = shelf_service.get(slug)
    return (item.title, item.slug) if item else (text.strip(), "")


def _mine_response(request: Request, status: int = 200, **context):
    defaults = {"v": {}, "suggested": set(), "error": "", "done": None, "duplicate": None}
    return templates.TemplateResponse(request, "shelf/_mine_preview.html", defaults | context, status_code=status)


@router.post("/mine/enrich", response_class=HTMLResponse)
def mine_enrich(
    request: Request,
    line: str = Form(""),
    word: str = Form(""),
    source: str = Form(""),
    source_text: str = Form(""),
    session: Session = Depends(get_session),
):
    """HTMX: ask Claude about the line (or the chosen word in it) and show an editable card preview."""
    line, word = " ".join(line.split()), " ".join(word.split())
    if not line:
        return _mine_response(request, error="Paste the Russian line first.")
    headword = word or line
    try:
        result = card_service.enrich(ClaudeClient(session), headword, context=line if word else "")
    except ClaudeError as e:
        return _mine_response(request, error=str(e))

    source_title, slug = _source(source, source_text)
    notes = " ".join(n for n in (result.notes, f"Source: {source_title}." if source_title else "") if n)
    values = {
        **result.model_dump(exclude={"forms", "stress_shift"}),
        "ru": headword,
        "notes": notes,
        "tags": f"mined {slug}".strip(),
        "stress_verified": False,  # Claude's stress marks are a guess until the learner checks them
    }
    suggested = {name for name in ("ru_stressed", "en", "pos", "gender", "aspect", "aspect_partner", "example_ru", "example_en") if values.get(name)}
    return _mine_response(request, v=values, suggested=suggested)


@router.post("/mine/save", response_class=HTMLResponse)
async def mine_save(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    values = {name: str(form.get(name, "")) for name in MINE_FIELDS}
    duplicate = card_service.find_duplicate(session, values["ru"]) if values["ru"].strip() else None
    if duplicate:
        return _mine_response(request, duplicate=duplicate)
    try:
        card = card_service.create_card(
            session,
            source_module=Module.media,
            stress_verified=form.get("stress_verified") == "on",
            **values | {"tags": "mined " + values["tags"]},
        )
    except ValueError as e:
        return _mine_response(request, v=values, error=str(e), status=422)
    return _mine_response(request, done=card)

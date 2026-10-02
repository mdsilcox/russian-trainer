from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from app.db import get_session
from app.models import Card, Module
from app.services import cards as card_service
from app.services.claude import ClaudeClient, ClaudeError
from app.web import templates

router = APIRouter(prefix="/cards")


async def form_fields(request: Request) -> dict:
    form = await request.form()
    return {name: str(form.get(name, "")) for name in card_service.EDITABLE_FIELDS} | {
        "stress_verified": form.get("stress_verified") == "on",
        "force": form.get("force") == "1",
    }


def render_form(request: Request, card: Card | None, values: dict, error: str = "", duplicate=None, status=200):
    return templates.TemplateResponse(
        request,
        "cards/form.html",
        {"card": card, "v": values, "error": error, "duplicate": duplicate},
        status_code=status,
    )


@router.get("", response_class=HTMLResponse)
def browse(
    request: Request,
    q: str = "",
    tag: str = "",
    source: str = "",
    leeches: bool = False,
    session: Session = Depends(get_session),
):
    rows = card_service.search_cards(session, q=q, tag=tag, source=source, leeches=leeches)
    return templates.TemplateResponse(
        request,
        "cards/list.html",
        {
            "rows": rows,
            "q": q,
            "tag": tag,
            "source": source,
            "leeches": leeches,
            "tags": card_service.all_tags(session),
            "sources": [m.value for m in Module],
            "leech_lapses": card_service.LEECH_LAPSES,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_form(request: Request, ru: str = ""):
    return render_form(request, None, {"ru": ru})


@router.post("/new", response_class=HTMLResponse)
async def create(request: Request, session: Session = Depends(get_session)):
    values = await form_fields(request)
    duplicate = None if values["force"] else card_service.find_duplicate(session, values["ru"])
    if duplicate:
        return render_form(request, None, values, duplicate=duplicate, status=409)
    try:
        fields = {name: values[name] for name in card_service.EDITABLE_FIELDS}
        card_service.create_card(session, stress_verified=values["stress_verified"], **fields)
    except ValueError as e:
        return render_form(request, None, values, error=str(e), status=422)
    return RedirectResponse("/cards/new?added=1", status_code=303)


@router.get("/{card_id}", response_class=HTMLResponse)
def edit_form(request: Request, card_id: int, session: Session = Depends(get_session)):
    card = session.get(Card, card_id) or _not_found()
    return render_form(request, card, card.model_dump() | {"stress_verified": card.stress_verified})


@router.post("/{card_id}", response_class=HTMLResponse)
async def update(request: Request, card_id: int, session: Session = Depends(get_session)):
    card = session.get(Card, card_id) or _not_found()
    values = await form_fields(request)
    try:
        card_service.apply_fields(card, values)
    except ValueError as e:
        session.rollback()
        return render_form(request, card, values, error=str(e), status=422)
    card.stress_verified = values["stress_verified"]
    session.add(card)
    session.commit()
    return RedirectResponse("/cards", status_code=303)


@router.post("/{card_id}/suspend")
def toggle_suspend(card_id: int, session: Session = Depends(get_session)):
    card = session.get(Card, card_id) or _not_found()
    card.suspended = not card.suspended
    session.add(card)
    session.commit()
    return RedirectResponse(f"/cards/{card_id}", status_code=303)


@router.post("/{card_id}/delete")
def delete(card_id: int, session: Session = Depends(get_session)):
    session.get(Card, card_id) or _not_found()
    card_service.delete_card(session, card_id)
    return RedirectResponse("/cards", status_code=303)


@router.post("/enrich/suggest", response_class=HTMLResponse)
async def enrich(request: Request, session: Session = Depends(get_session)):
    """HTMX: ask Claude for details and re-render the fields pre-filled for review."""
    values = await form_fields(request)
    error = ""
    suggested: set[str] = set()
    if not values["ru"].strip():
        error = "Type the Russian word or phrase first."
    else:
        try:
            result = card_service.enrich(ClaudeClient(session), values["ru"], values["en"])
            for name, value in result.model_dump().items():
                if value and not values.get(name, "").strip():
                    values[name] = value
                    suggested.add(name)
            if "ru_stressed" in suggested:
                values["stress_verified"] = False
        except ClaudeError as e:
            error = str(e)
    return templates.TemplateResponse(
        request, "cards/_fields.html", {"v": values, "suggested": suggested, "enrich_error": error}
    )


def _not_found():
    raise HTTPException(status_code=404, detail="Card not found")

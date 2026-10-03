from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from app.db import get_session
from app.services import study_settings as service
from app.web import templates

router = APIRouter()

FIELDS = ("daily_new_cards", "desired_retention", "split_srs", "split_drill_or_story", "split_scenario")


def _render(request: Request, values: dict[str, str], errors: dict[str, str], status_code: int = 200):
    return templates.TemplateResponse(
        request, "settings/study.html", {"values": values, "errors": errors}, status_code=status_code
    )


@router.get("/settings/study", response_class=HTMLResponse)
def study_form(request: Request, session: Session = Depends(get_session)):
    current = service.load(session)
    values = {
        "daily_new_cards": str(current.daily_new_cards),
        "desired_retention": f"{current.desired_retention:g}",
        "split_srs": str(current.session_split["srs"]),
        "split_drill_or_story": str(current.session_split["drill_or_story"]),
        "split_scenario": str(current.session_split["scenario"]),
    }
    return _render(request, values, {})


@router.post("/settings/study")
async def study_save(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    values = {name: form[name] if isinstance(form.get(name), str) else "" for name in FIELDS}
    settings, errors = service.parse(values)
    if settings is None:
        return _render(request, values, errors, status_code=400)
    service.save(session, settings)
    return RedirectResponse("/settings?saved=study", status_code=303)

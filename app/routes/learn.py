import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from markupsafe import Markup, escape
from sqlmodel import Session

from app.db import get_session
from app.models import Module, TopicReview, Unit
from app.services import cards, plan, units
from app.services.drills import NotEnoughItems
from app.services.claude import ClaudeError
from app.web import templates

router = APIRouter(prefix="/learn")

STATUS_LABELS = {
    "not_started": "Not started", "active": "In progress", "remediation": "Remediation",
    "passed": "Passed", "secure": "Secure", "fast_tracked": "Fast-tracked",
}
STEP_LABELS = {"locked": "Locked", "available": "Ready", "done": "Done", "skipped": "Skipped"}
SELF_REPORTED = {"learn": "learn", "story": "story", "roleplay": "roleplay"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def guillemets(text: str) -> Markup:
    """Escape text and wrap «Russian» spans in lang="ru"."""
    parts = re.split(r"(«[^»]*»)", str(text))
    return Markup("").join(
        Markup('<span lang="ru">{}</span>').format(p) if p.startswith("«") else escape(p) for p in parts)


templates.env.filters["guillemets"] = guillemets


def display_status(session: Session, unit: Unit) -> str:
    p = units.progress(session, unit)
    if p.status in ("active", "not_started") and (p.steps_json or {}).get("fast_track"):
        return "fast_tracked"
    return p.status


def unit_row(session: Session, unit: Unit) -> dict:
    status = display_status(session, unit)
    return {"unit": unit, "status": status, "label": STATUS_LABELS.get(status, status),
            "mastery": round(units.progress(session, unit).mastery * 100)}


def month_units(session: Session, month_idx: int) -> list[dict]:
    return [unit_row(session, u) for u in units.units_for_month(session, month_idx)]


def _unit_or_404(session: Session, unit_id: str) -> Unit:
    unit = session.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(404, "No such unit")
    return unit


@router.get("", response_class=HTMLResponse)
def learn_index(request: Request, session: Session = Depends(get_session)):
    now = _now()
    current = units.current_unit(session, now)
    hero = None
    if current is not None:
        st = units.state(session, current, now)
        nxt = next((s for s in st.steps if s.status == "available"), None)
        hero = {**unit_row(session, current), "next": nxt, "started": units.progress(session, current).status != "not_started"}
    months = [{"m": m, "units": month_units(session, m.month_idx)} for m in plan.months(session)]
    current_month = plan.current_month(session, now)
    revisits = []
    for u in units.revisits_due(session, now):
        r = session.get(TopicReview, u.id)
        revisits.append({"unit": u, "step": r.step if r else 0})
    return templates.TemplateResponse(request, "learn/index.html", {
        "hero": hero, "months": months, "revisits": revisits,
        "current_idx": current_month.month_idx if current_month else None,
        "has_units": any(m["units"] for m in months)})


@router.get("/{unit_id}", response_class=HTMLResponse)
def unit_page(request: Request, unit_id: str, session: Session = Depends(get_session)):
    unit = _unit_or_404(session, unit_id)
    now = _now()
    units.start(session, unit, now)
    st = units.state(session, unit, now)
    return templates.TemplateResponse(request, "learn/unit.html", {
        "u": unit, "st": st, "row": unit_row(session, unit), "prompt": units.story_prompt(unit),
        "step_labels": STEP_LABELS, "self_reported": SELF_REPORTED})


@router.post("/{unit_id}/done/{step}")
def mark_done(unit_id: str, step: str, session: Session = Depends(get_session)):
    unit = _unit_or_404(session, unit_id)
    if step not in SELF_REPORTED:
        raise HTTPException(404, "That step cannot be marked by hand")
    units.finish_step(session, unit, SELF_REPORTED[step], 1.0, now=_now())
    return RedirectResponse(f"/learn/{unit_id}", status_code=303)


def _lesson_ctx(session: Session, unit: Unit) -> dict:
    ctx = {"u": unit, "lesson": None, "error": ""}
    try:
        ctx["lesson"] = units.get_lesson(session, unit)  # generates on first open and caches
    except NotImplementedError:
        ctx["error"] = "This lesson is not written yet. It will appear here once the unit's content is ready."
    except (ClaudeError, NotEnoughItems) as exc:
        ctx["error"] = f"The lesson could not be prepared: {exc}"
    return ctx


@router.get("/{unit_id}/lesson", response_class=HTMLResponse)
def lesson_page(request: Request, unit_id: str, session: Session = Depends(get_session)):
    """Cached lessons render at once; otherwise a shell loads the body by HTMX (generation takes ~25 s)."""
    unit = _unit_or_404(session, unit_id)
    units.start(session, unit, _now())
    cached = units.cached(session, unit.id, "lesson") is not None
    ctx = _lesson_ctx(session, unit) if cached else {"u": unit, "lesson": None, "error": ""}
    return templates.TemplateResponse(request, "learn/lesson.html", {**ctx, "loading": not cached})


@router.get("/{unit_id}/lesson/body", response_class=HTMLResponse)
def lesson_body(request: Request, unit_id: str, session: Session = Depends(get_session)):
    unit = _unit_or_404(session, unit_id)
    return templates.TemplateResponse(request, "learn/_lesson_body.html", _lesson_ctx(session, unit))


@router.post("/{unit_id}/lesson/words", response_class=HTMLResponse)
def add_words(request: Request, unit_id: str, session: Session = Depends(get_session)):
    unit = _unit_or_404(session, unit_id)
    ctx = _lesson_ctx(session, unit)
    added = skipped = 0
    if ctx["lesson"] is not None:
        for w in ctx["lesson"].words:
            if cards.find_duplicate(session, w.ru) is not None:
                skipped += 1
                continue
            cards.create_card(session, source_module=Module.manual, ru=w.ru, en=w.en, tags=f"unit {unit.id}")
            added += 1
    return templates.TemplateResponse(request, "learn/_added.html", {"added": added, "skipped": skipped, "error": ctx["error"]})

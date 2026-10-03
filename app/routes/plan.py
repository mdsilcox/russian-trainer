from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app.db import get_session
from app.models import PlanMonth, Setting
from app.routes.learn import month_units
from app.services import plan, stats, weakness
from app.web import templates

router = APIRouter(prefix="/plan")

RATING_LABELS = {1: "Rough", 2: "Slow", 3: "Okay", 4: "Good", 5: "Great"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _trip(session: Session) -> date | None:
    row = session.get(Setting, "trip_date")
    try:
        return date.fromisoformat(str(row.value)) if row is not None and row.value else None
    except ValueError:
        return None


def _month_view(session: Session, m: PlanMonth, today: date, now: datetime) -> dict:
    start, end = plan.month_range(m)
    state = "past" if end <= today else "current" if start <= today else "future"
    topics = [{"url": t, "label": weakness.topic_label(t)} for t in m.topics_json or []]
    rows = month_units(session, m.month_idx)
    view = {"m": m, "state": state, "start": start, "units": rows, "topics": topics, "review": m.review_json or None}
    view["passed"] = sum(1 for r in rows if r["status"] in ("passed", "secure"))
    if state == "current":
        view["expected_pct"] = round(plan.expected_ratio(m, now) * 100)
    return view


def _page_context(session: Session, now: datetime, **extra) -> dict:
    today = stats.local_date(now)
    months = plan.months(session)
    trip = _trip(session)
    ctx = {
        "empty": trip is None or not months,
        "trip": trip,
        "days_left": stats.days_until_trip(session, now),
        "months": [_month_view(session, m, today, now) for m in months],
        "due": plan.review_due(session, now),
        "rating_labels": RATING_LABELS,
        "kinds": plan.DAY_KINDS,
        "weekdays": plan.WEEKDAYS,
        "rhythm": plan.rhythm(session),
        "rhythm_error": "", "rhythm_saved": False,
        "checkin_error": "", "checkin_saved": None, "form_rating": 0, "form_notes": "",
    }
    ctx.update(extra)
    return ctx


@router.get("", response_class=HTMLResponse)
def plan_page(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "plan/index.html", _page_context(session, _now()))


@router.post("/checkin", response_class=HTMLResponse)
def save_checkin(request: Request, month_idx: int = Form(0), rating: str = Form(""), notes: str = Form(""),
                 session: Session = Depends(get_session)):
    now = _now()
    due = plan.review_due(session, now)
    error = ""
    value = int(rating) if rating.strip().isdigit() else 0
    if due is None or due.month_idx != month_idx:
        error = "There is no check-in open for that month."
    elif value not in RATING_LABELS:
        error = "Pick a rating from 1 to 5."
    elif len(notes) > 2000:
        error = "Keep the notes under 2000 characters."
    if error:
        ctx = _page_context(session, now, checkin_error=error, form_rating=value, form_notes=notes)
        return templates.TemplateResponse(request, "plan/_checkin.html", ctx)
    saved = plan.save_review(session, due, value, notes, now)
    ctx = _page_context(session, now, checkin_saved=saved)
    return templates.TemplateResponse(request, "plan/_checkin_saved.html", ctx)


def _rhythm_response(request: Request, session: Session, **extra):
    return templates.TemplateResponse(request, "plan/_rhythm.html", _page_context(session, _now(), **extra))


@router.post("/rhythm", response_class=HTMLResponse)
def save_rhythm(request: Request, kind: list[str] = Form(default_factory=list), session: Session = Depends(get_session)):
    try:
        plan.set_rhythm(session, kind)
    except ValueError as exc:
        return _rhythm_response(request, session, rhythm_error=str(exc), rhythm=list(kind) if len(kind) == 7 else plan.rhythm(session))
    return _rhythm_response(request, session, rhythm_saved=True)


@router.post("/rhythm/reset", response_class=HTMLResponse)
def reset_rhythm(request: Request, session: Session = Depends(get_session)):
    plan.set_rhythm(session, list(plan.DEFAULT_RHYTHM))
    return _rhythm_response(request, session, rhythm_saved=True)

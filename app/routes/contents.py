"""Contents: every section of the app, grouped like the main menu, each with a live hint."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlmodel import Session, select

from app.db import get_session
from app.models import Card
from app.services import drills, plan, shelf, stats, today, units
from app.web import NAV_GROUPS, templates

router = APIRouter()


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def hints(session: Session, now: datetime) -> dict[str, str]:
    """One short, live line per section. Each lookup is independent so one failure can't break the page."""
    out: dict[str, str] = {}

    def safe(href: str, fn) -> None:
        try:
            text = fn()
            if text:
                out[href] = text
        except Exception:
            pass

    def unit_hint() -> str:
        unit = units.current_unit(session, now)
        if unit is None:
            return ""
        nxt = next((s for s in units.state(session, unit, now).steps if s.status == "available"), None)
        return f"Now: {unit.title}" + (f" · next: {nxt.title}" if nxt else "")

    def drills_hint() -> str:
        open_set = drills.open_set(session)
        if open_set is not None:
            return "A drill set is waiting for you"
        kind, topics = drills.plan_next(session, now)
        return f"Up next: {', '.join(t.label for t in topics)}" if topics else ""

    safe("/learn", unit_hint)
    safe("/drills", drills_hint)
    safe("/review", lambda: _plural(today.plan_reviews(session, now).queued, "card", "cards") + " waiting today")
    safe("/workshop", lambda: (f"Revise: {s.title}" if (s := today.suggest_story(session)) else "Start a new story"))
    safe("/scenarios", lambda: (f"Suggested: {s.title}" if (s := today.suggest_scenario(session)) else ""))
    safe("/shelf", lambda: _plural(shelf.this_week(session, now), "minute", "minutes") + " logged this week")
    safe("/plan", lambda: (f"This month: {m.title}" if (m := plan.current_month(session, now)) else ""))
    safe("/dashboard", lambda: _plural(stats.streaks(session, now).current, "day", "days") + " streak")
    safe("/cards", lambda: _plural(session.exec(select(func.count()).select_from(Card).where(Card.suspended == False)).one(), "card", "cards") + " in your deck")  # noqa: E712
    return out


@router.get("/contents", response_class=HTMLResponse)
def contents(request: Request, session: Session = Depends(get_session)):
    now = datetime.now(timezone.utc)
    return templates.TemplateResponse(request, "contents.html", {"groups": NAV_GROUPS, "hints": hints(session, now)})

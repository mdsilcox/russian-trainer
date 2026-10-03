from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app.db import get_session
from app.services import medals, shelf, stats
from app.services.claude import month_spend
from app.web import templates

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)):
    now = datetime.now(timezone.utc)
    forecast = stats.review_forecast(session, now)
    spend = month_spend(session, now)
    medal_states = medals.evaluate(session, now)
    context = {
        "medals": medal_states,
        "medals_earned": sum(1 for m in medal_states if m.earned),
        "streak": stats.streaks(session, now),
        "due_today": stats.reviews_due_today(session, now),
        "forecast": forecast,
        "forecast_max": max([n for _, n in forecast] + [1]),
        "retention": stats.retention(session, now),
        "trip_days": stats.days_until_trip(session, now),
        "mistakes": stats.top_mistakes(session, now),
        "spend": spend,
        "spend_pct": min(100, round(spend.spent_usd / spend.budget_usd * 100)) if spend.budget_usd else None,
        "deck": stats.deck_counts(session),
        "input_week": shelf.this_week(session, now),
        "input_month": shelf.input_minutes(session, 30, now),
    }
    return templates.TemplateResponse(request, "dashboard.html", context)

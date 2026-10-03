"""Activity timeline (Phase 6, lane B): what you practiced, day by day."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app.db import get_session
from app.services import activity
from app.web import templates

router = APIRouter()


@router.get("/activity", response_class=HTMLResponse)
def activity_page(request: Request, session: Session = Depends(get_session)):
    days = activity.timeline(session, datetime.now(timezone.utc), days=14)
    return templates.TemplateResponse(request, "activity.html", {"days": days})

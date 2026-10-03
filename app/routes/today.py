from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from app.db import get_session
from app.services import lessons, srs, stats, today
from app.web import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def today_page(request: Request, msg: str = "", session: Session = Depends(get_session)):
    now = datetime.now(timezone.utc)
    local_today = stats.local_date(now)
    week = lessons.this_week(session, now)
    active = today.active_session(session, now)
    context = {
        "plan": today.build_plan(session, now),
        "active": active,
        "started_iso": srs._utc(active.started_at).isoformat() if active else "",
        "summary": today.day_summary(session, now),
        "streak": stats.streaks(session, now),
        "trip_days": stats.days_until_trip(session, now),
        "date_label": today.date_label(now),
        "trip": today.trip_progress(session, now),
        "weak_spots": today.weak_spots(session, now),
        "word": today.word_of_the_day(session, stats.local_date(now)),
        "clock": today.moscow_clock(now),
        "growth": today.growth_stage(stats.days_until_trip(session, now)),
        "too_short": msg == "too_short",
        "tutor_tasks": [(t, lessons.due_label(t.due, local_today)) for t in lessons.tasks_for_today(session, now)],
        "week": week,
        "next_lesson": lessons.next_lesson(session, now) if week.next_lesson_date else None,
        "next_label": lessons.next_label(week.days_until_next) if week.days_until_next is not None else "",
    }
    return templates.TemplateResponse(request, "today.html", context)


@router.post("/today/start")
def start(session: Session = Depends(get_session)):
    today.start_session(session)
    return RedirectResponse("/", status_code=303)


@router.post("/today/finish")
def finish(session: Session = Depends(get_session)):
    done = today.finish_session(session)
    return RedirectResponse("/" if done else "/?msg=too_short", status_code=303)

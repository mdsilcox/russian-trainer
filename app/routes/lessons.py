"""Tutor lessons, tasks and questions (Phase 6, lane C). Thin routes over `services/lessons.py`."""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from app.db import get_session
from app.services import cards, lessons, stats
from app.services.claude import ClaudeClient, ClaudeError
from app.web import templates

router = APIRouter()
templates.env.globals["lesson_date"] = lambda d: lessons.pretty_date(d, stats.local_date(datetime.now(timezone.utc)))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def _lesson_or_404(session: Session, lesson_id: int):
    lesson = lessons.get_lesson(session, lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="No such lesson")
    return lesson


# ---------------------------------------------------------------- list and create

def _list_page(request: Request, session: Session, form: dict | None = None, error: str = "", status: int = 200):
    rows = lessons.list_lessons(session)
    counts = lessons.lesson_counts(session, rows)
    today = stats.local_date(_now())
    form = form or {"date": today.isoformat(), "topic": "", "goals": "", "materials": "", "notes": ""}
    return templates.TemplateResponse(request, "lessons/index.html", {
        "rows": [(lesson, *counts[lesson.id]) for lesson in rows], "form": form, "error": error, "today": today,
    }, status_code=status)


@router.get("/lessons", response_class=HTMLResponse)
def lessons_page(request: Request, session: Session = Depends(get_session)):
    return _list_page(request, session)


@router.post("/lessons")
async def create_lesson(request: Request, session: Session = Depends(get_session)):
    data = await request.form()
    form = {k: str(data.get(k) or "") for k in ("date", "topic", "goals", "materials", "notes")}
    try:
        try:
            when = date.fromisoformat(form["date"].strip())
        except ValueError:
            raise ValueError("Pick a valid date (YYYY-MM-DD)")
        lesson = lessons.create_lesson(session, when, form["topic"], lessons.parse_goals(form["goals"]),
                                       lessons.parse_materials(form["materials"]), form["notes"])
    except ValueError as e:
        return _list_page(request, session, form, str(e), 400)
    return _redirect(f"/lessons/{lesson.id}")


# ---------------------------------------------------------------- one lesson

def _detail(request: Request, session: Session, lesson, status: int = 200, **extra):
    today = stats.local_date(_now())
    context = {
        "lesson": lesson,
        "words": lessons.lesson_words(session, lesson.id),
        "tasks": lessons.lesson_tasks(session, lesson.id),
        "questions": lessons.open_questions(session),
        "today": today,
        "due_label": lessons.due_label,
        "task_form": {"title": "", "due": today.isoformat()},
        "task_error": "",
    }
    return templates.TemplateResponse(request, "lessons/detail.html", context | extra, status_code=status)


@router.get("/lessons/{lesson_id}", response_class=HTMLResponse)
def lesson_page(lesson_id: int, request: Request, session: Session = Depends(get_session)):
    return _detail(request, session, _lesson_or_404(session, lesson_id))


# ---------------------------------------------------------------- word lists

@router.post("/lessons/{lesson_id}/words", response_class=HTMLResponse)
async def words_review(lesson_id: int, request: Request, session: Session = Depends(get_session)):
    lesson = _lesson_or_404(session, lesson_id)
    data = await request.form()
    items, errors = lessons.parse_word_list(str(data.get("text") or ""))
    rows = [{"ru": i.ru, "en": i.en, "ru_stressed": "", "example_ru": "", "example_en": "", "notes": "",
             "pos": "", "gender": "", "aspect": "", "aspect_partner": "",
             "duplicate": cards.find_duplicate(session, i.ru) is not None} for i in items]
    note = ""
    if rows:
        client = None
        try:
            client = ClaudeClient(session)  # raises when AI is off, so it is built inside the try
        except ClaudeError as e:
            note = f"{e} The words are listed without stress marks or examples."
        failed = 0
        for row in rows if client else []:
            try:
                e = cards.enrich(client, row["ru"], row["en"])
            except (ClaudeError, ValueError):
                failed += 1
                continue
            row.update(ru_stressed=e.ru_stressed or "", example_ru=e.example_ru or "", example_en=e.example_en or "",
                       notes=e.notes or "", pos=e.pos or "", gender=e.gender or "", aspect=e.aspect or "",
                       aspect_partner=e.aspect_partner or "")
        if failed:
            note = (f"Claude could not look up {failed} of {len(rows)} words, "
                    "so those are listed without stress marks or examples.")
    return templates.TemplateResponse(request, "lessons/words_review.html", {
        "lesson": lesson, "rows": rows, "errors": errors, "note": note})


@router.post("/lessons/{lesson_id}/words/add")
async def words_add(lesson_id: int, request: Request, session: Session = Depends(get_session)):
    _lesson_or_404(session, lesson_id)
    data = await request.form()
    fields = ("ru", "en", "ru_stressed", "example_ru", "example_en", "notes", "pos", "gender", "aspect", "aspect_partner")
    items, i = [], 0
    while f"items-{i}-ru" in data:
        if data.get(f"items-{i}-keep") == "on":
            items.append({f: str(data.get(f"items-{i}-{f}") or "") for f in fields})
        i += 1
    lessons.add_words(session, lesson_id, items)
    return _redirect(f"/lessons/{lesson_id}")


# ---------------------------------------------------------------- tasks

@router.post("/lessons/{lesson_id}/tasks")
async def task_add(lesson_id: int, request: Request, session: Session = Depends(get_session)):
    lesson = _lesson_or_404(session, lesson_id)
    data = await request.form()
    title, due_text = str(data.get("title") or ""), str(data.get("due") or "")
    try:
        try:
            due = date.fromisoformat(due_text.strip())
        except ValueError:
            raise ValueError("Pick a valid due date.")
        lessons.add_task(session, title, due, lesson_id)
    except ValueError as e:
        return _detail(request, session, lesson, 400, task_error=str(e), task_form={"title": title, "due": due_text})
    return _redirect(f"/lessons/{lesson_id}")


@router.post("/tasks/{task_id}/done")
async def task_done(task_id: int, request: Request, session: Session = Depends(get_session)):
    data = await request.form()
    try:
        lessons.complete_task(session, task_id, _now())
    except ValueError:
        raise HTTPException(status_code=404, detail="No such task")
    return _redirect(lessons.safe_path(str(data.get("next") or ""), "/"))


# ---------------------------------------------------------------- questions

@router.post("/questions", response_class=HTMLResponse)
async def question_add(request: Request, session: Session = Depends(get_session)):
    data = await request.form()
    page = str(data.get("page") or "")
    htmx = request.headers.get("HX-Request") == "true"
    try:
        lessons.add_question(session, str(data.get("text") or ""), page, _now())
    except ValueError as e:
        if htmx:
            return templates.TemplateResponse(request, "lessons/_question_saved.html", {"error": str(e)}, status_code=400)
        raise HTTPException(status_code=400, detail=str(e))
    if htmx:
        return templates.TemplateResponse(request, "lessons/_question_saved.html", {"error": ""})
    return _redirect(lessons.safe_path(page, "/"))


@router.post("/questions/{question_id}/asked")
async def question_asked(question_id: int, request: Request, session: Session = Depends(get_session)):
    data = await request.form()
    try:
        lessons.mark_asked(session, question_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No such question")
    return _redirect(lessons.safe_path(str(data.get("next") or ""), "/lessons"))


# ---------------------------------------------------------------- pre-lesson summary

@router.post("/lessons/{lesson_id}/summary", response_class=HTMLResponse)
def summary(lesson_id: int, request: Request, session: Session = Depends(get_session)):
    _lesson_or_404(session, lesson_id)
    result, error = None, ""
    try:
        result = lessons.pre_lesson_summary(session, lesson_id, ClaudeClient(session), _now())
    except ClaudeError as e:
        error = str(e)
    return templates.TemplateResponse(request, "lessons/_summary.html", {
        "lesson_id": lesson_id, "result": result, "error": error})

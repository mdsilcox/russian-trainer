from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app.db import get_session
from app.models import DrillSet
from app.services import drill_player, drills
from app.services.claude import ClaudeError
from app.web import templates

router = APIRouter(prefix="/drills")


def _plan_text(session: Session) -> tuple[str, list[str]]:
    kind, topics = drills.plan_next(session)
    return kind, [t.label for t in topics]


def _item_view(session: Session, drill_set: DrillSet, idx: int | None = None, **extra) -> dict:
    prog = drill_player.progress(session, drill_set)
    if prog.done:
        return _done_view(drill_set, prog)
    idx = prog.next_idx if idx is None else idx
    item = drill_set.items_json[idx]
    before, _, after = item["prompt_ru"].partition(drills.BLANK)
    return {"view": "item", "set": drill_set, "prog": prog, "idx": idx, "item": item, "before": before, "after": after,
            "attempt": 1, "value": "", "hint": False, "empty": False, **extra}


def _done_view(drill_set: DrillSet, prog: drill_player.Progress) -> dict:
    labels = list(dict.fromkeys(i.get("topic_label", "") for i in drill_set.items_json if i.get("topic_label")))
    return {"view": "done", "set": drill_set, "prog": prog, "labels": labels}


def _open_view(session: Session, drill_set: DrillSet) -> dict:
    prog = drill_player.progress(session, drill_set)
    if drill_set.kind == "focused" and drill_set.intro_json and prog.answered == 0:
        return {"view": "card", "set": drill_set, "intro": drill_set.intro_json, "prog": prog}
    return _item_view(session, drill_set)


def _plan_view(session: Session, error: str = "") -> dict:
    kind, labels = _plan_text(session)
    return {"view": "plan", "kind": kind, "labels": labels, "error": error}


def _render(request: Request, ctx: dict, status_code: int = 200):
    return templates.TemplateResponse(request, "drills/_stage.html", ctx, status_code=status_code)


@router.get("", response_class=HTMLResponse)
def drills_page(request: Request, session: Session = Depends(get_session)):
    current = drills.open_set(session)
    ctx = _open_view(session, current) if current else _plan_view(session)
    return templates.TemplateResponse(request, "drills/index.html", ctx)


@router.get("/item", response_class=HTMLResponse)
def current_item(request: Request, session: Session = Depends(get_session)):
    current = drills.open_set(session)
    return _render(request, _item_view(session, current) if current else _plan_view(session))


@router.get("/done", response_class=HTMLResponse)
def finished(request: Request, set_id: int, session: Session = Depends(get_session)):
    drill_set = session.get(DrillSet, set_id)
    if drill_set is None:
        raise HTTPException(status_code=404, detail="Drill set not found")
    prog = drill_player.progress(session, drill_set)
    if not prog.done:
        return _render(request, _item_view(session, drill_set))
    return _render(request, _done_view(drill_set, prog))


@router.post("/generate", response_class=HTMLResponse)
def generate(request: Request, session: Session = Depends(get_session)):
    try:
        drill_set = drills.next_set(session)
    except (ClaudeError, drills.NotEnoughItems) as e:
        return _render(request, _plan_view(session, str(e) or "That set didn't come out well. Try again."))
    if drill_set is None:
        return _render(request, _plan_view(session))
    return _render(request, _open_view(session, drill_set))


@router.post("/answer", response_class=HTMLResponse)
def answer(
    request: Request,
    set_id: int = Form(...),
    idx: int = Form(...),
    attempt: int = Form(1),
    answer: str = Form(""),
    session: Session = Depends(get_session),
):
    drill_set = session.get(DrillSet, set_id)
    if drill_set is None or not 0 <= idx < len(drill_set.items_json):
        raise HTTPException(status_code=404, detail="Drill not found")
    result = drill_player.submit(session, drill_set, idx, answer, attempt, datetime.now(timezone.utc))
    if result.final:
        prog = drill_player.progress(session, drill_set)
        return _render(request, {"view": "result", "set": drill_set, "prog": prog, "idx": idx, "r": result,
                                 "item": drill_set.items_json[idx], "given": answer.strip()})
    ctx = _item_view(session, drill_set, idx)
    if result.empty:
        return _render(request, ctx | {"attempt": 1 if attempt < 2 else 2, "hint": attempt >= 2, "empty": True})
    return _render(request, ctx | {"attempt": 2, "hint": True, "value": answer.strip()})

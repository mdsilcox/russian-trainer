"""The exercise player for guided-learning units: one item at a time over HTMX.

Stateless like the drill player: the position, running score (first-try correct answers) and attempt
number travel in the form. Every answer is recorded with `units.record_attempt`; the last item calls
`units.finish_step`.

Item templates live in `templates/learn/items/_<type>.html` and render only the answer controls. They
receive `item`, `attempt`, `tried` (the wrong response on a second try) and, for build and match,
`tiles` / `lefts` / `rights`. The player's form posts the learner's answer as `response`.
"""

import random

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import TemplateNotFound
from sqlmodel import Session

from app.db import get_session
from app.models import Unit
from app.services import exercises, units
from app.services.claude import ClaudeError
from app.web import templates

router = APIRouter(prefix="/learn")

ONE_TRY = {"pretest", "quiz"}  # no second chance, no hints
BLANK = "___"


def _unit(session: Session, unit_id: str) -> Unit:
    unit = session.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="Unit not found")
    return unit


def _kind(kind: str) -> str:
    if kind not in units.ITEM_KINDS:
        raise HTTPException(status_code=404, detail="Unknown exercise set")
    return kind


def _render(request: Request, ctx: dict, status_code: int = 200):
    return templates.TemplateResponse(request, "learn/_stage.html", ctx, status_code=status_code)


def _template_for(item) -> str:
    name = f"learn/items/_{item.type}.html"
    try:
        templates.env.get_template(name)
    except TemplateNotFound:
        return "learn/items/_missing.html"
    return name


def _shuffled(seed: str, values: list, avoid: list | None = None) -> list:
    """A shuffle that is stable for the same seed, and differs from `avoid` when it can."""
    out = list(values)
    for salt in range(8):
        random.Random(f"{seed}:{salt}").shuffle(out)
        if avoid is None or len(out) < 2 or out != avoid:
            break
    return out


def _reveal(item) -> str:
    """The right answer as one line of text."""
    if item.type in ("choice", "listen_choice"):
        right = item.options[item.answer_index]
        if item.type == "choice" and BLANK in item.question_ru:
            return item.question_ru.replace(BLANK, right)
        return right
    if item.type == "fill":
        return item.prompt_ru.replace(BLANK, item.answer)
    if item.type == "dictation":
        return item.audio_ru
    if item.type == "match":
        return "; ".join(f"{p['left']} = {p['right']}" for p in item.pairs)
    return item.answer


def _given(item, response: str) -> str:
    """What the learner answered, as readable text."""
    if item.type in ("choice", "listen_choice"):
        try:
            return item.options[int(response)]
        except (ValueError, IndexError):
            return response
    if item.type == "fill":
        return item.prompt_ru.replace(BLANK, response)
    return response


def _base(unit: Unit, kind: str, variant: int, title: str, items: list, idx: int, score: int, intro: str = "") -> dict:
    return {"intro": intro, "unit": unit, "kind": kind, "variant": variant, "title": title, "total": len(items), "idx": idx,
            "score": score, "one_try": kind in ONE_TRY}


def _item_view(base: dict, item, **extra) -> dict:
    ctx = base | {"view": "item", "item": item, "attempt": 1, "tried": "", "hint": False, "empty": False,
                  "answered": False, "item_template": _template_for(item)}
    if item.type == "build":
        order = list(range(len(item.tiles)))
        ctx["tiles"] = [(i, item.tiles[i]) for i in _shuffled(item.id + "|".join(item.tiles), order, order)]
    if item.type == "match":
        lefts = list(range(len(item.pairs)))
        ctx["lefts"] = [(i, item.pairs[i]["left"]) for i in lefts]
        ctx["rights"] = [(i, item.pairs[i]["right"]) for i in _shuffled(item.id + "r", lefts, lefts)]
    return ctx | extra


def _error_view(unit: Unit, kind: str, variant: int, error: Exception) -> dict:
    if isinstance(error, NotImplementedError):
        message = "This set hasn't been written yet. It will appear once the unit's exercises are generated."
    else:
        message = str(error) or "The exercises couldn't be prepared just now."
    return {"view": "error", "unit": unit, "kind": kind, "variant": variant, "message": message,
            "retryable": isinstance(error, ClaudeError)}


def _load(session: Session, unit: Unit, kind: str, variant: int):
    """(title, items, intro), or an error view dict when the set can't be prepared."""
    try:
        title, items = units.get_items(session, unit, kind, variant)
    except (NotImplementedError, ClaudeError) as e:
        return _error_view(unit, kind, variant, e)
    if not items:
        return _error_view(unit, kind, variant, NotImplementedError())
    body = units.cached(session, unit.id, kind, variant) or units.cached(session, unit.id, kind, 0) or {}
    return title, items, body.get("intro", "")


def _show_item(request: Request, session: Session, unit: Unit, kind: str, variant: int, idx: int, score: int):
    loaded = _load(session, unit, kind, variant)
    if isinstance(loaded, dict):
        return _render(request, loaded)
    title, items, intro = loaded
    if not 0 <= idx < len(items):
        raise HTTPException(status_code=404, detail="Item not found")
    return _render(request, _item_view(_base(unit, kind, variant, title, items, idx, score, intro), items[idx]))


@router.get("/{unit_id}/play/{kind}", response_class=HTMLResponse)
def play(request: Request, unit_id: str, kind: str, variant: int = 0, session: Session = Depends(get_session)):
    unit, kind = _unit(session, unit_id), _kind(kind)
    ctx = {"unit": unit, "kind": kind, "variant": variant}
    if units.cached(session, unit.id, kind, variant) is None:
        # Not stored yet: the first item request generates it, behind a loading state.
        return templates.TemplateResponse(request, "learn/play.html", ctx | {"view": "loading"})
    loaded = _load(session, unit, kind, variant)
    if isinstance(loaded, dict):
        return templates.TemplateResponse(request, "learn/play.html", loaded)
    title, items, intro = loaded
    return templates.TemplateResponse(
        request, "learn/play.html", _item_view(_base(unit, kind, variant, title, items, 0, 0, intro), items[0]))


@router.get("/{unit_id}/play/{kind}/item", response_class=HTMLResponse)
def item(request: Request, unit_id: str, kind: str, variant: int = 0, idx: int = 0, score: int = 0,
         session: Session = Depends(get_session)):
    unit, kind = _unit(session, unit_id), _kind(kind)
    return _show_item(request, session, unit, kind, variant, idx, score)


@router.post("/{unit_id}/play/{kind}/answer", response_class=HTMLResponse)
def answer(request: Request, unit_id: str, kind: str, variant: int = Form(0), idx: int = Form(...),
           score: int = Form(0), attempt: int = Form(1), misses: int = Form(0), response: str = Form(""),
           session: Session = Depends(get_session)):
    unit, kind = _unit(session, unit_id), _kind(kind)
    loaded = _load(session, unit, kind, variant)
    if isinstance(loaded, dict):
        return _render(request, loaded)
    title, items, intro = loaded
    if not 0 <= idx < len(items):
        raise HTTPException(status_code=404, detail="Item not found")
    the_item, base = items[idx], _base(unit, kind, variant, title, items, idx, score, intro)
    response = response.strip()
    attempt = 2 if attempt >= 2 and not base["one_try"] else 1
    tried = response if attempt == 2 else ""

    if not response or response in ("[]", "null"):
        return _render(request, _item_view(base, the_item, attempt=attempt, empty=True, tried=""))

    correct = exercises.check(the_item, response)
    given = _given(the_item, response)
    if the_item.type == "match":
        # Pairs only lock in when right, so what counts is how many wrong taps it took.
        credited, final = correct and misses == 0, True
        units.record_attempt(session, unit, kind, variant, the_item, given, credited, 1)
    else:
        units.record_attempt(session, unit, kind, variant, the_item, given, correct, attempt)
        credited = correct and attempt == 1
        final = correct or attempt == 2 or base["one_try"]
    if not final:
        return _render(request, _item_view(base, the_item, attempt=2, hint=True, tried=response))

    new_score = score + int(credited)
    if credited:
        verdict, good = "Correct", True
    elif correct and the_item.type == "match":
        # Pairs only lock in when right, so "correct" here means matched after some wrong taps.
        verdict, good = ("Not this time", False) if base["one_try"] else (f"Matched, with {misses} {'slip' if misses == 1 else 'slips'}", True)
    elif correct:
        verdict, good = "Correct on the second try", True
    else:
        verdict, good = "Not this time", False
    return _render(request, base | {
        "view": "result", "item": the_item, "score": new_score, "credited": credited, "correct": good, "verdict": verdict,
        "given": given, "revealed": _reveal(the_item),
        "last": idx + 1 >= len(items),
    })


@router.post("/{unit_id}/play/{kind}/next", response_class=HTMLResponse)
def next_item(request: Request, unit_id: str, kind: str, variant: int = Form(0), idx: int = Form(...),
              score: int = Form(0), session: Session = Depends(get_session)):
    """Move on to item `idx`, or finish the step when that is past the end."""
    unit, kind = _unit(session, unit_id), _kind(kind)
    loaded = _load(session, unit, kind, variant)
    if isinstance(loaded, dict):
        return _render(request, loaded)
    title, items, intro = loaded
    if idx < len(items):
        return _show_item(request, session, unit, kind, variant, idx, score)
    total = len(items)
    score = max(0, min(score, total))
    result = units.finish_step(session, unit, kind, score / total, variant)
    return _render(request, {"view": "done", "unit": unit, "kind": kind, "variant": variant, "title": title,
                             "correct": score, "total": total, "result": result,
                             "percent": round(result.score * 100)})


@router.post("/{unit_id}/fast-track")
def fast_track(unit_id: str, session: Session = Depends(get_session)):
    unit = _unit(session, unit_id)
    try:
        units.fast_track(session, unit)
    except ValueError:
        pass  # not earned (or a stale click): the unit page shows where things stand
    return RedirectResponse(f"/learn/{unit.id}", status_code=303)

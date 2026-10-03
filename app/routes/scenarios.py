from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from sqlmodel import Session, col, select

from app.db import get_session
from app.models import Conversation, Message, Module, Scenario
from app.services import cards as card_service
from app.services import roleplay, scenarios
from app.services.claude import ClaudeClient, ClaudeError
from app.services.feedback import Issue, annotate
from app.web import templates

router = APIRouter(prefix="/scenarios")

NOTICES: dict[str, str] = {}
STREAM_ERROR = "\x1e"  # a streamed reply that fails mid-way ends with this marker followed by the message


def _get(session: Session, slug: str) -> Scenario:
    scenario = session.exec(select(Scenario).where(Scenario.slug == slug)).first()
    if scenario is None:
        raise HTTPException(404, "No such scenario")
    return scenario


@router.get("", response_class=HTMLResponse)
def scenario_list(request: Request, notice: str = "", session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "scenarios/index.html", {
        "groups": scenarios.grouped(session), "levels": scenarios.LEVEL_LABELS, "flash": NOTICES.get(notice),
    })


@router.get("/{slug}", response_class=HTMLResponse)
def scenario_detail(request: Request, slug: str, notice: str = "", session: Session = Depends(get_session)):
    s = _get(session, slug)
    return templates.TemplateResponse(request, "scenarios/detail.html", {
        "s": s, "levels": scenarios.LEVEL_LABELS, "flash": NOTICES.get(notice),
        "unfinished": session.exec(
            select(Conversation).where(Conversation.scenario_id == s.id, col(Conversation.ended_at).is_(None))
            .order_by(col(Conversation.started_at).desc(), col(Conversation.id).desc())
        ).first(),
    })


@router.post("/{slug}/start")
def start(slug: str, level: Annotated[int, Form(ge=1, le=3)], session: Session = Depends(get_session)):
    conv = roleplay.start(session, _get(session, slug), level)
    return RedirectResponse(f"/scenarios/c/{conv.id}", status_code=303)


# --- Chat -----------------------------------------------------------------------------------


def _conversation(session: Session, conversation_id: int) -> Conversation:
    conv = session.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(404, "No such conversation")
    return conv


def _error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _learner_view(message: Message) -> dict:
    """What the learner bubble template needs: text segments with correction spans, notes, 'more natural'."""
    issues, better = roleplay.corrections(message)
    segments, unplaced = annotate(message.content, issues)
    return {"m": message, "issues": issues, "segments": segments, "unplaced": unplaced, "better": better,
            "reviewed": message.corrections_json is not None}


def _bubble_html(message: Message, ended: bool = False) -> str:
    return templates.get_template("scenarios/_learner_text.html").render(**_learner_view(message), ended=ended)


@router.get("/c/{conversation_id}", response_class=HTMLResponse)
def chat_page(request: Request, conversation_id: int, session: Session = Depends(get_session)):
    conv = _conversation(session, conversation_id)
    history = roleplay.messages(session, conv)
    return templates.TemplateResponse(request, "scenarios/chat.html", {
        "conv": conv, "s": roleplay.scenario_of(session, conv), "levels": scenarios.LEVEL_LABELS,
        "ended": conv.ended_at is not None,
        "rows": [(m, _learner_view(m) if m.role == roleplay.LEARNER else None) for m in history],
        "awaiting_reply": bool(history) and history[-1].role == roleplay.LEARNER,
        "debrief": roleplay.Debrief(**conv.debrief_json) if conv.debrief_json else None,
        **(_debrief_ctx(session, conv, history) if conv.ended_at is not None else {}),
    })


@router.post("/c/{conversation_id}/turn")
def chat_turn(conversation_id: int, text: Annotated[str, Form()] = "", session: Session = Depends(get_session)):
    """Save the learner's line. The browser then asks for the partner's reply."""
    conv = _conversation(session, conversation_id)
    try:
        msg = roleplay.add_learner_turn(session, conv, text)
    except ValueError as e:
        return _error(str(e), 409 if conv.ended_at else 422)
    return {"id": msg.id}


@router.post("/c/{conversation_id}/reply")
def chat_reply(conversation_id: int, session: Session = Depends(get_session)):
    """Stream the partner's reply as plain text; it is saved when the stream completes.
    A failure part-way ends the body with STREAM_ERROR plus the message, so the page can offer a retry."""
    conv = _conversation(session, conversation_id)
    if conv.ended_at is not None:
        return _error("This conversation has ended", 409)
    history = roleplay.messages(session, conv)
    if not history or history[-1].role != roleplay.LEARNER:
        return _error("Nothing to reply to yet", 409)

    def body():
        live = session.get(Conversation, conversation_id)
        try:
            yield from roleplay.partner_stream(session, ClaudeClient(session), live)
        except ClaudeError as e:
            yield STREAM_ERROR + str(e)

    return StreamingResponse(body(), media_type="text/plain; charset=utf-8", headers={"Cache-Control": "no-store"})


@router.post("/c/{conversation_id}/review/{message_id}")
def chat_review(conversation_id: int, message_id: int, session: Session = Depends(get_session)):
    """Corrections for one learner line (computed once), plus the goals achieved so far."""
    conv = _conversation(session, conversation_id)
    msg = session.get(Message, message_id)
    if msg is None or msg.conversation_id != conv.id or msg.role != roleplay.LEARNER:
        raise HTTPException(404, "No such line")
    if msg.corrections_json is None:
        try:
            roleplay.review_turn(session, ClaudeClient(session), conv, msg)
        except ClaudeError as e:
            return _error(str(e), 502)
        session.refresh(msg)
        session.refresh(conv)
    return {"html": _bubble_html(msg), "goals_met": conv.goals_met_json or []}


@router.post("/c/{conversation_id}/hint")
def chat_hint(conversation_id: int, session: Session = Depends(get_session)):
    conv = _conversation(session, conversation_id)
    if conv.ended_at is not None:
        return _error("This conversation has ended", 409)
    try:
        return roleplay.hint(session, ClaudeClient(session), conv).model_dump()
    except ClaudeError as e:
        return _error(str(e), 502)


@router.post("/c/{conversation_id}/end")
def chat_end(conversation_id: int, session: Session = Depends(get_session)):
    roleplay.end(session, _conversation(session, conversation_id))
    return RedirectResponse(f"/scenarios/c/{conversation_id}", status_code=303)


# --- Debrief ----------------------------------------------------------------------------------


def _debrief_ctx(session: Session, conv: Conversation, history: list[Message] | None = None) -> dict:
    """Goals achieved vs missed and the chat's corrections grouped by rule, for the debrief panel."""
    s = roleplay.scenario_of(session, conv)
    met = set(conv.goals_met_json or [])
    goals = list(enumerate(s.goals_json or []))
    groups: dict[tuple[str, str], list[Issue]] = {}
    for m in history if history is not None else roleplay.messages(session, conv):
        if m.role == roleplay.LEARNER:
            for issue in roleplay.corrections(m)[0]:
                groups.setdefault((issue.category, issue.subcategory), []).append(issue)
    return {
        "conv": conv, "s": s, "levels": scenarios.LEVEL_LABELS,
        "goals_done": [g for i, g in goals if i in met], "goals_missed": [g for i, g in goals if i not in met],
        "fix_groups": [{"category": c, "subcategory": sub, "issues": issues} for (c, sub), issues in groups.items()],
    }


@router.post("/c/{conversation_id}/debrief", response_class=HTMLResponse)
def chat_debrief(request: Request, conversation_id: int, session: Session = Depends(get_session)):
    """HTMX: the debrief panel. The first call asks Claude (about 9 s); later calls read the cached copy."""
    conv = _conversation(session, conversation_id)
    if conv.ended_at is None:
        raise HTTPException(409, "End the conversation first")
    ctx = _debrief_ctx(session, conv)
    try:
        ctx["debrief"] = roleplay.debrief(session, ClaudeClient(session), conv)
    except ClaudeError as e:
        ctx["debrief"], ctx["error"] = None, str(e)
    return templates.TemplateResponse(request, "scenarios/_debrief.html", ctx)


@router.post("/c/{conversation_id}/debrief/cards", response_class=HTMLResponse)
def chat_debrief_cards(conversation_id: int, i: Annotated[list[int] | None, Form()] = None,
                       session: Session = Depends(get_session)):
    """HTMX: add the ticked phrases as cards, skipping ones already in the deck."""
    conv = _conversation(session, conversation_id)
    if not conv.debrief_json:
        raise HTTPException(409, "No debrief yet")
    slug = roleplay.scenario_of(session, conv).slug
    phrases = roleplay.Debrief(**conv.debrief_json).phrases
    added = skipped = 0
    for idx in dict.fromkeys(i or []):
        if not 0 <= idx < len(phrases):
            continue
        p = phrases[idx]
        if card_service.find_duplicate(session, card_service.strip_stress(p.ru)):
            skipped += 1
            continue
        card_service.create_card(
            session, source_module=Module.scenario, source_ref_id=conv.id,
            ru=card_service.strip_stress(p.ru), ru_stressed=p.ru, en=p.en, example_ru=p.example_ru,
            example_en=p.example_en, notes=p.why, tags=f"scenario {slug}",
        )
        added += 1
    if not added and not skipped:
        text = "Tick at least one phrase first."
    else:
        text = f"Added {added} card{'' if added == 1 else 's'}." if added else "Nothing new to add."
        if skipped:
            text += f" {skipped} already in your deck."
    return HTMLResponse(f'<span class="ch-added" role="status">{text}</span>')

import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from app.db import get_session
from app.models import Card, Story
from app.services import cards as cards_service
from app.services import cloze
from app.web import templates

router = APIRouter(prefix="/cloze")

_EDGE_PUNCTUATION = re.compile("^[^\\ẃ]+|[^\\ẃ]+$")


def _tokens(sentence: str) -> list[dict]:
    """Words of a sentence, each with the form a click should put in the word field."""
    return [{"shown": token, "word": _EDGE_PUNCTUATION.sub("", token)} for token in sentence.split()]


def _page(request: Request, session: Session, *, made: int | None = None, error: dict | None = None, status_code: int = 200):
    items = []
    done = cloze.cloze_sentence_keys(session)
    titles: dict[int, str] = {}
    for source in cloze.sentences(session):
        if source.story_id not in titles:
            story = session.get(Story, source.story_id)
            titles[source.story_id] = story.title if story else "Your story"
        items.append(
            {
                "text": source.text,
                "story_id": source.story_id,
                "title": titles[source.story_id],
                "tokens": _tokens(source.text),
                "has_card": cards_service.normalize(source.text) in done,
            }
        )
    groups: list[dict] = []
    for item in items:
        if groups and groups[-1]["story_id"] == item["story_id"]:
            groups[-1]["sentences"].append(item)
        else:
            groups.append({"story_id": item["story_id"], "title": item["title"], "sentences": [item]})

    made_card = None
    if made is not None:
        card = session.get(Card, made)
        if card is not None and card.kind == "cloze":
            try:
                blanked, answer = cloze.make_cloze(card.example_ru or "", card.ru_stressed or card.ru)
            except ValueError:
                blanked, answer = cloze.BLANK, card.ru_stressed or card.ru
            made_card = {"id": card.id, "blanked": blanked, "answer": answer, "en": card.en}

    inline_error = bool(error) and any(
        item["text"] == error["sentence"] and str(item["story_id"]) == error["story_id"] for item in items
    )
    context = {"groups": groups, "made": made_card, "error": error, "inline_error": inline_error, "total": len(items)}
    return templates.TemplateResponse(request, "cloze/index.html", context, status_code=status_code)


@router.get("", response_class=HTMLResponse)
def cloze_page(request: Request, made: int | None = None, session: Session = Depends(get_session)):
    return _page(request, session, made=made)


@router.post("", response_class=HTMLResponse)
def make_card(
    request: Request,
    sentence: str = Form(""),
    word: str = Form(""),
    en: str = Form(""),
    story_id: str = Form(""),
    session: Session = Depends(get_session),
):
    story_ref = int(story_id) if story_id.strip().isdigit() else None
    try:
        card = cloze.create_cloze_card(session, sentence, word, en, story_ref)
    except ValueError as exc:
        error = {
            "message": str(exc),
            "sentence": sentence.strip(),
            "story_id": story_id.strip(),
            "word": word,
            "en": en,
        }
        return _page(request, session, error=error, status_code=400)
    return RedirectResponse(f"/cloze?made={card.id}", status_code=303)

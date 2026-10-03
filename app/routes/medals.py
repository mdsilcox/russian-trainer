from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db import get_session
from app.services import medals
from app.web import templates

router = APIRouter()


def _art(state: medals.MedalState) -> str:
    module = templates.env.get_template("_medals.html").module
    return str(module.art(state.design, state.field, state.dot))


@router.get("/medals/pending")
def pending(session: Session = Depends(get_session)):
    """Earned medallions whose ceremony has not been shown, newest first."""
    return {
        "medals": [
            {"key": s.key, "ru": s.ru, "en": s.en, "how": s.how, "story": s.defn.story,
             "date": s.date_label, "art": _art(s)}
            for s in medals.pending(session)
        ]
    }


@router.post("/medals/{key}/seen")
def seen(key: str, session: Session = Depends(get_session)):
    if not medals.mark_seen(session, key):
        raise HTTPException(status_code=404, detail="Medal not earned")
    return {"ok": True}

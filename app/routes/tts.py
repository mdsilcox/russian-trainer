from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from sqlmodel import Session

from app.config import ROOT
from app.db import get_session
from app.services import tts

router = APIRouter()

SETUP_DOC = ROOT / "docs" / "voices.md"


def _error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


@router.get("/tts/status")
def tts_status(session: Session = Depends(get_session)):
    return {"available": tts.available(), "default_voice": tts.default_voice(session), "voices": tts.voices()}


@router.get("/tts")
def tts_audio(text: str = "", voice: str = "", rate: float = 1.0, session: Session = Depends(get_session)):
    if not tts.available():
        return _error("Natural voices are off: no Azure Speech key is set.", 503)
    voice = voice or tts.default_voice(session)
    if not tts.is_voice(voice):
        return _error("Unknown voice.", 400)
    cleaned = tts.clean_text(text)
    if not cleaned:
        return _error("There is no text to speak.", 400)
    if len(cleaned) > tts.MAX_CHARS:
        return _error(f"That is too long to speak (the limit is {tts.MAX_CHARS} characters).", 400)
    try:
        audio = tts.synthesize(cleaned, voice, rate)
    except tts.TTSUnavailable as e:
        return _error(str(e), 503)
    except tts.TTSError as e:
        return _error(str(e), 502)
    return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=2592000, immutable"})


@router.get("/tts/setup")
def tts_setup():
    """The setup steps, shown as plain text (the settings page links here)."""
    if not SETUP_DOC.exists():
        return _error("The setup notes are missing.", 404)
    return Response(SETUP_DOC.read_text(encoding="utf-8"), media_type="text/plain; charset=utf-8")

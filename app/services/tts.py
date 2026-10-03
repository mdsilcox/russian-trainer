"""Natural cloud voices through Azure Speech, with an on-disk cache.

Only the text of a spoken line is sent to Azure. Every result is stored as
`<data_dir>/tts/<sha256 of voice|rate|text>.mp3`, so a line is paid for once and replays are free.
When no key is configured `available()` is False and the browser's own voices are used instead.
"""

import hashlib
from xml.sax.saxutils import escape

import httpx
from sqlmodel import Session

from app.config import get_config
from app.models import Setting
from app.services import cards

MAX_CHARS = 1000
TIMEOUT = httpx.Timeout(15.0, connect=6.0)
OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
SETTING_KEY = "tts_voice"

# (voice id, label shown to the learner)
VOICES: list[tuple[str, str]] = [
    ("ru-RU-SvetlanaNeural", "Svetlana (female)"),
    ("ru-RU-DariyaNeural", "Dariya (female)"),
    ("ru-RU-DmitryNeural", "Dmitry (male)"),
]
DEFAULT_VOICE = VOICES[0][0]

# The speak control's speeds as SSML prosody rates. Natural voices already run brisk, so 1x is a touch slower.
RATE_PERCENT = {0.6: -45, 0.75: -30, 0.9: -18, 1.0: -10, 1.2: 5}


class TTSError(Exception):
    """A failure whose message is safe to show to the learner."""


class TTSUnavailable(TTSError):
    """No Azure key is configured."""


def available() -> bool:
    return get_config().has_tts


def voices() -> list[dict]:
    return [{"id": v, "label": label} for v, label in VOICES]


def is_voice(voice: str) -> bool:
    return any(v == voice for v, _ in VOICES)


def default_voice(session: Session) -> str:
    row = session.get(Setting, SETTING_KEY)
    return row.value if row and is_voice(str(row.value)) else DEFAULT_VOICE


def set_default_voice(session: Session, voice: str) -> None:
    if not is_voice(voice):
        raise ValueError("Unknown voice")
    row = session.get(Setting, SETTING_KEY) or Setting(key=SETTING_KEY, value=voice)
    row.value = voice
    session.add(row)
    session.commit()


def clean_text(text: str) -> str:
    """Stress marks (and Latin accented vowels) are dropped; ё has no combining mark so it stays."""
    text = cards.fix_latin_accents(text or "")
    return " ".join(text.replace(cards.STRESS, "").split())


def prosody_rate(rate: float) -> str:
    try:
        r = float(rate)
    except (TypeError, ValueError):
        r = 1.0
    nearest = min(RATE_PERCENT, key=lambda x: abs(x - r))
    pct = RATE_PERCENT[nearest]
    return f"{pct:+d}%" if pct else "0%"


def build_ssml(text: str, voice: str, rate: float) -> str:
    return (
        '<speak version="1.0" xml:lang="ru-RU">'
        f'<voice name="{voice}"><prosody rate="{prosody_rate(rate)}">{escape(text)}</prosody></voice>'
        "</speak>"
    )


def cache_path(text: str, voice: str, rate: float):
    key = hashlib.sha256(f"{voice}|{prosody_rate(rate)}|{text}".encode("utf-8")).hexdigest()
    return get_config().data_dir / "tts" / f"{key}.mp3"


def _post(url: str, headers: dict, content: bytes) -> httpx.Response:
    """The one network call; tests replace it."""
    return httpx.post(url, headers=headers, content=content, timeout=TIMEOUT)


def synthesize(text: str, voice: str = DEFAULT_VOICE, rate: float = 1.0) -> bytes:
    """MP3 bytes for `text`. Raises TTSUnavailable without a key, TTSError (friendly message) on failure."""
    config = get_config()
    if not config.has_tts:
        raise TTSUnavailable("Natural voices are off: no Azure Speech key is set.")
    if not is_voice(voice):
        raise TTSError("Unknown voice.")
    text = clean_text(text)
    if not text:
        raise TTSError("There is no text to speak.")
    if len(text) > MAX_CHARS:
        raise TTSError(f"That is too long to speak (the limit is {MAX_CHARS} characters).")

    path = cache_path(text, voice, rate)
    if path.exists():
        return path.read_bytes()

    url = f"https://{config.azure_speech_region}.tts.speech.microsoft.com/cognitiveservices/v1"
    headers = {
        "Ocp-Apim-Subscription-Key": config.azure_speech_key,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": OUTPUT_FORMAT,
        "User-Agent": "russian-trainer",
    }
    try:
        res = _post(url, headers, build_ssml(text, voice, rate).encode("utf-8"))
    except httpx.HTTPError:
        raise TTSError("Could not reach Azure. Check your internet connection and try again.") from None
    if res.status_code in (401, 403):
        raise TTSError("The Azure key was rejected. Check AZURE_SPEECH_KEY and AZURE_SPEECH_REGION.")
    if res.status_code == 429:
        raise TTSError("Azure's free allowance is used up for now.")
    if res.status_code != 200 or not res.content:
        raise TTSError("Azure could not make that audio. Try again in a moment.")

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(res.content)
    tmp.replace(path)
    return res.content

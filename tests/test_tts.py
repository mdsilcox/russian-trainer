"""Azure TTS: the HTTP call is always faked, never real."""

import httpx
import pytest
from sqlmodel import select

from app.config import Config
from app.models import Scenario, Setting
from app.services import scenarios, tts


class FakeResponse:
    def __init__(self, status=200, content=b"MP3DATA"):
        self.status_code = status
        self.content = content


class FakePost:
    def __init__(self, response=None, exc=None):
        self.response = response or FakeResponse()
        self.exc = exc
        self.calls = []

    def __call__(self, url, headers, content):
        self.calls.append((url, headers, content))
        if self.exc:
            raise self.exc
        return self.response


@pytest.fixture
def keyed(monkeypatch, tmp_path):
    cfg = Config(azure_speech_key="secret-key", azure_speech_region="westeurope", data_dir=tmp_path)
    monkeypatch.setattr(tts, "get_config", lambda: cfg)
    fake = FakePost()
    monkeypatch.setattr(tts, "_post", fake)
    return fake


@pytest.fixture
def keyless(monkeypatch, tmp_path):
    cfg = Config(data_dir=tmp_path)
    monkeypatch.setattr(tts, "get_config", lambda: cfg)
    monkeypatch.setattr(tts, "_post", FakePost(exc=AssertionError("must not call Azure")))


def test_config_masks_key_and_reports_has_tts():
    cfg = Config(azure_speech_key="secret-key", azure_speech_region="westeurope")
    assert cfg.has_tts
    assert "secret-key" not in repr(cfg)
    assert not Config(azure_speech_key="k").has_tts
    assert not Config().has_tts


def test_ssml_is_escaped_and_uses_voice_and_rate():
    ssml = tts.build_ssml("Том & <Джерри>", "ru-RU-DmitryNeural", 0.9)
    assert ssml.startswith('<speak version="1.0" xml:lang="ru-RU">')
    assert '<voice name="ru-RU-DmitryNeural">' in ssml
    assert "&amp;" in ssml and "&lt;Джерри&gt;" in ssml
    assert '<prosody rate="-18%">' in ssml


def test_rate_mapping_covers_every_speed_and_snaps():
    assert [tts.prosody_rate(r) for r in (0.6, 0.75, 0.9, 1.0, 1.2)] == ["-45%", "-30%", "-18%", "-10%", "+5%"]
    assert tts.prosody_rate(1.19) == "+5%"
    assert tts.prosody_rate("junk") == "-10%"


def test_clean_text_strips_stress_keeps_yo_and_fixes_latin_accents():
    assert tts.clean_text("Здра́вствуйте, всё хорошо́") == "Здравствуйте, всё хорошо"
    assert tts.clean_text("купé  билéт") == "купе билет"


def test_synthesize_sends_expected_request(keyed):
    assert tts.synthesize("Привет", "ru-RU-DariyaNeural", 1.0) == b"MP3DATA"
    url, headers, body = keyed.calls[0]
    assert url == "https://westeurope.tts.speech.microsoft.com/cognitiveservices/v1"
    assert headers["Ocp-Apim-Subscription-Key"] == "secret-key"
    assert headers["Content-Type"] == "application/ssml+xml"
    assert headers["X-Microsoft-OutputFormat"] == "audio-24khz-48kbitrate-mono-mp3"
    assert headers["User-Agent"] == "russian-trainer"
    assert "Привет".encode() in body


def test_second_call_is_served_from_cache(keyed, tmp_path):
    first = tts.synthesize("Привет", "ru-RU-DariyaNeural", 1.0)
    second = tts.synthesize("Приве́т", "ru-RU-DariyaNeural", 1.0)
    assert first == second and len(keyed.calls) == 1
    assert len(list((tmp_path / "tts").glob("*.mp3"))) == 1
    tts.synthesize("Привет", "ru-RU-DariyaNeural", 0.6)  # a different rate is a different file
    tts.synthesize("Привет", "ru-RU-DmitryNeural", 1.0)
    assert len(keyed.calls) == 3


@pytest.mark.parametrize("status,phrase", [(401, "key was rejected"), (403, "key was rejected"),
                                           (429, "free allowance is used up"), (500, "could not make")])
def test_http_errors_map_to_friendly_messages(keyed, tmp_path, status, phrase):
    keyed.response = FakeResponse(status, b"")
    with pytest.raises(tts.TTSError, match=phrase):
        tts.synthesize("Привет", tts.DEFAULT_VOICE, 1.0)
    assert not (tmp_path / "tts").exists() or not list((tmp_path / "tts").glob("*.mp3"))


def test_network_error_is_friendly(keyed):
    keyed.exc = httpx.ConnectError("boom with secret-key")
    with pytest.raises(tts.TTSError) as e:
        tts.synthesize("Привет", tts.DEFAULT_VOICE, 1.0)
    assert "secret-key" not in str(e.value) and "internet" in str(e.value)


def test_unavailable_without_key(keyless):
    with pytest.raises(tts.TTSUnavailable):
        tts.synthesize("Привет")


def test_synthesize_rejects_bad_input(keyed):
    with pytest.raises(tts.TTSError):
        tts.synthesize("   ")
    with pytest.raises(tts.TTSError):
        tts.synthesize("а" * 1001)
    with pytest.raises(tts.TTSError):
        tts.synthesize("Привет", "ru-RU-Nobody")
    assert keyed.calls == []


def test_default_voice_setting(session):
    assert tts.default_voice(session) == "ru-RU-SvetlanaNeural"
    tts.set_default_voice(session, "ru-RU-DmitryNeural")
    assert tts.default_voice(session) == "ru-RU-DmitryNeural"
    session.get(Setting, "tts_voice").value = "gone"
    assert tts.default_voice(session) == "ru-RU-SvetlanaNeural"
    with pytest.raises(ValueError):
        tts.set_default_voice(session, "gone")


# ---- routes ----------------------------------------------------------------------------------

def test_status_with_key(client, keyed):
    body = client.get("/tts/status").json()
    assert body["available"] is True
    assert body["default_voice"] == "ru-RU-SvetlanaNeural"
    assert [v["id"] for v in body["voices"]] == ["ru-RU-SvetlanaNeural", "ru-RU-DariyaNeural", "ru-RU-DmitryNeural"]


def test_status_without_key(client, keyless):
    assert client.get("/tts/status").json()["available"] is False
    res = client.get("/tts", params={"text": "Привет"})
    assert res.status_code == 503 and "error" in res.json()


def test_audio_route(client, keyed):
    res = client.get("/tts", params={"text": "Привет", "voice": "ru-RU-DmitryNeural", "rate": 0.75})
    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/mpeg"
    assert "max-age" in res.headers["cache-control"]
    assert res.content == b"MP3DATA"
    assert b'rate="-30%"' in keyed.calls[0][2]


def test_audio_route_uses_saved_default_voice(client, keyed):
    client.post("/settings/voice", data={"voice": "ru-RU-DmitryNeural"})
    client.get("/tts", params={"text": "Привет"})
    assert b"ru-RU-DmitryNeural" in keyed.calls[0][2]


@pytest.mark.parametrize("params", [{"text": ""}, {"text": "   "}, {"text": "а" * 1001},
                                    {"text": "Привет", "voice": "ru-RU-Nobody"}])
def test_audio_route_validation(client, keyed, params):
    assert client.get("/tts", params=params).status_code == 400
    assert keyed.calls == []


def test_audio_route_azure_failure_is_json(client, keyed):
    keyed.response = FakeResponse(429, b"")
    res = client.get("/tts", params={"text": "Привет"})
    assert res.status_code == 502 and "allowance" in res.json()["error"]


# ---- settings --------------------------------------------------------------------------------

def test_settings_voice_section_and_save(client, keyed):
    page = client.get("/settings").text
    assert "Natural voices on" in page and "Play a sample" in page and "ru-RU-DariyaNeural" in page
    res = client.post("/settings/voice", data={"voice": "ru-RU-DariyaNeural"}, follow_redirects=False)
    assert res.status_code == 303
    assert 'value="ru-RU-DariyaNeural" selected' in client.get("/settings").text
    client.post("/settings/voice", data={"voice": "bogus"})
    assert 'value="ru-RU-DariyaNeural" selected' in client.get("/settings").text


def test_settings_without_key_points_to_setup(client, keyless):
    page = client.get("/settings").text
    assert "Using your browser" in page and "/tts/setup" in page
    assert "Play a sample" in page
    assert "Azure" in client.get("/tts/setup").text


# ---- scenario voices -------------------------------------------------------------------------

def test_every_scenario_has_a_valid_voice():
    valid = {v for v, _ in tts.VOICES}
    assert all(s["voice"] in valid for s in scenarios.SCENARIOS)
    male = {"taxi", "train", "restaurant", "hotel-problem", "market", "wrong-order"}
    for s in scenarios.SCENARIOS:
        assert (s["voice"] == "ru-RU-DmitryNeural") == (s["slug"] in male), s["slug"]


def test_scenario_voice_is_seeded(session):
    scenarios.seed(session)
    taxi = session.exec(select(Scenario).where(Scenario.slug == "taxi")).one()
    assert taxi.voice == "ru-RU-DmitryNeural"

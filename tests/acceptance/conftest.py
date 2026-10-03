"""Acceptance tests ported from the Orchestration Lab's hidden tests (Phase 6).

Adapted only where main differs from the Lab's base: names and markup that changed since
(American spelling, the grouped menu, Phase 5) and choices the user made for this phase.
Never weaken an assertion."""

from datetime import datetime, time, timezone

import pytest
from sqlmodel import Session

from app.db import make_engine, migrate


@pytest.fixture(autouse=True)
def _no_real_claude(monkeypatch):
    """API backend, no key: any unfaked Claude call fails fast instead of reaching the network."""
    from app.config import get_config
    from app.services import claude

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_config.cache_clear()
    monkeypatch.setitem(claude._current, "backend", claude.Backend.api)
    yield
    get_config.cache_clear()


@pytest.fixture
def engine(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'hidden.db'}")
    migrate(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def client(engine):
    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import app

    def override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


class FakeClaude:
    """Stands in for ClaudeClient. Queue responses with `push`; inspect `calls`.

    A response is a dict (validated into the requested output model), a model
    instance, or an exception instance (raised).
    """

    def __init__(self):
        self.responses: list = []
        self.calls: list[dict] = []

    def push(self, *responses):
        self.responses.extend(responses)
        return self

    def ask_structured(self, task, system, messages, output_model, max_tokens=16000):
        prompt = messages if isinstance(messages, str) else "\n".join(
            m["content"] if isinstance(m.get("content"), str) else str(m.get("content")) for m in messages
        )
        self.calls.append({"task": task, "system": system, "prompt": prompt, "model": output_model, "max_tokens": max_tokens})
        if not self.responses:
            raise AssertionError("FakeClaude: no response queued")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, dict):
            return output_model.model_validate(response)
        return response


def _normalise(args, kwargs):
    names = ["task", "system", "messages", "output_model", "max_tokens"]
    bound = dict(zip(names, args))
    bound.update(kwargs)
    return bound


@pytest.fixture
def fake_claude(monkeypatch):
    """Patch ClaudeClient wherever it is imported (class-level), and report AI as available."""
    from app.services import claude

    fake = FakeClaude()

    def init(self, session=None, *args, **kwargs):
        self.session = session
        self.backend = claude.Backend.api

    def ask(self, *args, **kwargs):
        b = _normalise(args, kwargs)
        return fake.ask_structured(b["task"], b.get("system", ""), b["messages"], b["output_model"], b.get("max_tokens", 16000))

    monkeypatch.setattr(claude.ClaudeClient, "__init__", init)
    monkeypatch.setattr(claude.ClaudeClient, "ask_structured", ask)
    monkeypatch.setattr(claude, "ai_status", lambda backend=None: (True, ""))
    # Templates read AI availability through globals bound at import time.
    from app.web import templates

    monkeypatch.setitem(templates.env.globals, "ai_enabled", lambda *a, **k: True)
    monkeypatch.setitem(templates.env.globals, "ai_off_reason", lambda *a, **k: "")
    return fake


@pytest.fixture
def ai_off():
    """AI unavailable: the default here (API backend, no key). Named for readability."""
    return None


def local_noon(day) -> datetime:
    """A UTC datetime that is noon on `day` in the machine's local time zone."""
    return datetime.combine(day, time(12, 0)).astimezone().astimezone(timezone.utc)


@pytest.fixture
def now_local():
    return local_noon


# --- UI checks (Playwright) ---------------------------------------------------------------
# Used only by tasks/<task>/ui_checks. The live app runs from the repo under test on a fresh
# copy of the seed database (LAB_FIXTURE_DB, set by the harness), seeded through the repo's
# own code before the server starts.

VIEWPORTS = {"mobile": {"width": 375, "height": 812}, "desktop": {"width": 1280, "height": 800}}


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_app(tmp_path):
    """Call live_app(seed=None) -> base URL. `seed(session)` runs before the server starts."""
    import os
    import shutil
    import subprocess
    import sys
    import time
    import urllib.request

    procs = []

    def start(seed=None) -> str:
        data = tmp_path / "data"
        data.mkdir(exist_ok=True)
        fixture = os.environ.get("LAB_FIXTURE_DB")
        if fixture:
            shutil.copy2(fixture, data / "russian.db")
        eng = make_engine(f"sqlite:///{data / 'russian.db'}")
        migrate(eng)
        if seed is not None:
            with Session(eng) as s:
                seed(s)
                s.commit()
        eng.dispose()
        port = _free_port()
        env = dict(os.environ, RT_DATA_DIR=str(data))
        env.pop("ANTHROPIC_API_KEY", None)
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        procs.append(proc)
        url = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                urllib.request.urlopen(url + "/", timeout=1)
                return url
            except Exception:
                time.sleep(0.2)
        raise RuntimeError("app did not start")

    yield start
    for proc in procs:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(params=sorted(VIEWPORTS))
def page(request, browser):
    """A fresh page at each viewport (mobile 375px, desktop 1280px)."""
    context = browser.new_context(viewport=VIEWPORTS[request.param])
    pg = context.new_page()
    pg.viewport_name = request.param
    yield pg
    context.close()


def assert_no_hscroll(pg) -> None:
    overflow = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 1, f"horizontal scroll of {overflow}px at {pg.viewport_size['width']}px"

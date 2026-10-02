from sqlalchemy import text
from sqlmodel import select

from app.db import make_engine, migrate
from app.models import Mistake
from app.routes import workshop as workshop_routes
from app.services import feedback as fb
from app.services import mistakes
from app.services.claude import ClaudeClient
from tests.test_claude import FakeAnthropic, fake_response
from tests.test_mistakes import make_feedback, setup_story


def test_normalize_answer():
    assert fb.normalize_answer("  Ночно́м   ПОЕЗДЕ. ") == "ночном поезде"
    assert fb.normalize_answer("всё!") == fb.normalize_answer("все")
    assert fb.normalize_answer("тёплое…») ") == "теплое"
    assert fb.normalize_answer("Идти́") == "идти"
    assert fb.normalize_answer("й") == "й"  # breve is not a stress mark


def _panel(client, session, monkeypatch):
    story, attempt = setup_story(session)
    fake = FakeAnthropic(fake_response(parsed=make_feedback()))
    monkeypatch.setattr(workshop_routes, "ClaudeClient", lambda s: ClaudeClient(s, client=fake))
    panel = client.post(f"/workshop/{story.id}/attempts/{attempt.id}/feedback", headers={"HX-Request": "true"}).text
    return story, attempt, panel


def test_try_mode_markup(client, session, monkeypatch):
    story, attempt, panel = _panel(client, session, monkeypatch)
    assert "try-mode" in panel
    assert 'class="fix-input"' in panel and 'for="fix-0"' in panel
    assert panel.count(">Rule</a>") == 4
    assert 'href="/grammar' in panel
    assert 'data-act="reveal-all"' in panel and 'data-act="check"' in panel
    assert "<ins>ночном поезде</ins>" in panel  # answers stay in the DOM, hidden by CSS
    assert 'data-right="ночном поезде"' in panel
    assert panel.count("data-mistake=") == 3  # the style issue isn't logged


def test_attempt_endpoint_stores_outcome(client, session, monkeypatch):
    story, attempt, _ = _panel(client, session, monkeypatch)
    first = session.exec(select(Mistake).where(Mistake.ref_id == attempt.id)).first()
    r = client.post(f"/workshop/mistakes/{first.id}/attempt", data={"correct": "false"})
    assert r.json()["self_corrected"] is False and r.json()["fix_attempts"] == 1
    r = client.post(f"/workshop/mistakes/{first.id}/attempt", data={"correct": "true"})
    assert r.json() == {"ok": True, "self_corrected": True, "fix_attempts": 2}
    assert client.post(f"/workshop/mistakes/{first.id}/attempt", data={"correct": "false"}).json()["self_corrected"] is True
    assert client.post("/workshop/mistakes/9999/attempt", data={"correct": "true"}).status_code == 404


def test_reload_returns_to_try_mode_until_all_corrected(client, session, monkeypatch):
    story, attempt, _ = _panel(client, session, monkeypatch)
    assert "try-mode" in client.get(f"/workshop/{story.id}").text
    for m in session.exec(select(Mistake).where(Mistake.ref_id == attempt.id)).all():
        client.post(f"/workshop/mistakes/{m.id}/attempt", data={"correct": "true"})
    page = client.get(f"/workshop/{story.id}").text
    assert "feedback try-mode" not in page and "resolved solved" in page


def test_match_issues_handles_duplicates(session):
    story, attempt = setup_story(session)
    feedback = make_feedback()
    result = mistakes.route_story_feedback(session, story, attempt, feedback)
    matched = mistakes.match_issues(result.mistakes, feedback.issues)
    assert sorted(matched) == [0, 1, 2]


def test_migration_adds_self_correction_columns(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version VALUES (4)"))
        conn.execute(text(
            "CREATE TABLE mistakes (id INTEGER PRIMARY KEY, module VARCHAR, ref_id INTEGER, category VARCHAR, "
            "subcategory VARCHAR, wrong VARCHAR, right VARCHAR, explanation VARCHAR, card_id INTEGER, "
            "drilled_count INTEGER, mastered BOOLEAN, created_at DATETIME)"))
        conn.execute(text("INSERT INTO mistakes (module, category, wrong, right, drilled_count, mastered) VALUES ('story','case','a','b',0,0)"))
    migrate(engine)
    with engine.connect() as conn:
        row = conn.execute(text("SELECT self_corrected, fix_attempts FROM mistakes")).one()
    assert row[0] is None and row[1] == 0
    migrate(engine)  # idempotent

from datetime import datetime, timezone

import pytest

from app.models import Card, Setting
from app.services.claude import ClaudeError
from app.services.drills import NotEnoughItems
from app.services import cards, plan, unit_content, units

MID = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
UNIT = "u01-where-you-are"


@pytest.fixture
def learn(session, client, monkeypatch):
    row = session.get(Setting, "trip_date") or Setting(key="trip_date", value=None)
    row.value = "2027-09-30"
    session.add(row)
    session.commit()
    plan.seed(session, MID)
    units.seed_curriculum(session)
    unit_content.seed_demo(session)
    monkeypatch.setattr("app.routes.learn._now", lambda: MID)
    return client


def test_map_and_hero_render(learn):
    html = learn.get("/learn").text
    assert "Where you are: в and на + prepositional" in html
    assert "Say where you are and where things are" in html and "Start here" in html
    assert 'href="/learn/u02-where-to"' in html
    assert "Units coming" in html  # months 3 to 12 have no units yet
    assert "Not started" in html and "\u2014" not in html
    assert '<a href="/learn"' in learn.get("/plan").text


def test_revisit_list_links_to_player(learn, session):
    u = session.get(units.Unit, UNIT)
    units.finish_step(session, u, "quiz", 0.9, now=MID)
    html = learn.get("/learn").text  # not due yet
    assert "Revisits due" not in html
    from datetime import timedelta
    monkey_now = MID + timedelta(days=4)
    assert units.revisits_due(session, monkey_now)[0].id == UNIT


def test_revisit_due_shows_link(learn, session, monkeypatch):
    from datetime import timedelta
    u = session.get(units.Unit, UNIT)
    units.finish_step(session, u, "quiz", 0.9, now=MID)
    monkeypatch.setattr("app.routes.learn._now", lambda: MID + timedelta(days=4))
    assert f"/learn/{UNIT}/play/revisit?variant=0" in learn.get("/learn").text


def test_unit_page_step_states_and_start(learn, session):
    html = learn.get(f"/learn/{UNIT}").text
    assert "Pre-test" in html and "Quiz" in html
    assert 'href="/learn/u01-where-you-are/play/pretest"' in html
    assert "Locked" in html and "Mark as done" not in html  # story and speak locked until practice
    assert units.progress(session, session.get(units.Unit, UNIT)).status == "active"
    assert learn.get("/learn/nope").status_code == 404


def test_fast_track_offer_and_story_speak_blocks(learn, session):
    u = session.get(units.Unit, UNIT)
    units.finish_step(session, u, "pretest", 0.9, now=MID)
    units.finish_step(session, u, "practice", 0.9, variant=0, now=MID)
    html = learn.get(f"/learn/{UNIT}").text
    assert f'action="/learn/{UNIT}/fast-track"' in html
    assert "/workshop/new" in html and "Write 5 to 8 sentences" in html
    assert 'href="/scenarios/directions"' in html and "Say where you are right now" in html
    assert f'action="/learn/{UNIT}/done/story"' in html and f'action="/learn/{UNIT}/done/roleplay"' in html


def test_mark_done_routes(learn, session):
    u = session.get(units.Unit, UNIT)
    units.finish_step(session, u, "practice", 0.9, variant=0, now=MID)
    for step in ("story", "roleplay"):
        r = learn.post(f"/learn/{UNIT}/done/{step}", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == f"/learn/{UNIT}"
    session.expire_all()
    steps = units.progress(session, u).steps_json
    assert steps["story"]["score"] == 1.0 and "roleplay" in steps
    html = learn.get(f"/learn/{UNIT}").text
    assert "Mark as done" not in html
    assert learn.post(f"/learn/{UNIT}/done/quiz", follow_redirects=False).status_code == 404


def test_lesson_renders(learn):
    html = learn.get(f"/learn/{UNIT}/lesson").text
    assert "Most travel sentences say where" in html
    assert '<span lang="ru">«в»</span>' in html  # guillemet spans become Russian text
    assert 'data-speak="Мы в гости' in html and "speak.js" in html
    assert "Find every place after" in html and "Add these words to my cards" in html
    assert "I've got it" in html


@pytest.mark.parametrize("exc, text", [(NotImplementedError("x"), "not written yet"), (ClaudeError("Claude is busy"), "Claude is busy"),
                                       (NotEnoughItems("short"), "short")])
def test_lesson_content_errors_are_friendly(learn, monkeypatch, exc, text):
    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(unit_content, "generate_lesson", boom)
    shell = learn.get("/learn/u02-where-to/lesson").text  # uncached: loading shell first
    assert 'hx-get="/learn/u02-where-to/lesson/body"' in shell and "Preparing your lesson" in shell
    body = learn.get("/learn/u02-where-to/lesson/body").text
    assert text in body and 'role="alert"' in body and "Try again" in body
    assert "Add these words" not in learn.post("/learn/u02-where-to/lesson/words").text


def test_cached_lesson_skips_loading_shell(learn):
    assert "Preparing your lesson" not in learn.get(f"/learn/{UNIT}/lesson").text


def test_add_words_skips_duplicates(learn, session):
    cards.create_card(session, ru="вокза́л", en="station")
    r = learn.post(f"/learn/{UNIT}/lesson/words")
    assert "Added 11 words, skipped 1" in r.text
    session.expire_all()
    from sqlmodel import select
    tagged = session.exec(select(Card).where(Card.tags.contains(UNIT))).all()
    assert len(tagged) == 11 and all("unit" in c.tags for c in tagged)
    again = learn.post(f"/learn/{UNIT}/lesson/words")
    assert "already in your cards" in again.text


def test_got_it_finishes_learn_step(learn, session):
    r = learn.post(f"/learn/{UNIT}/done/learn", follow_redirects=False)
    assert r.status_code == 303
    session.expire_all()
    assert "learn" in units.progress(session, session.get(units.Unit, UNIT)).steps_json
    assert "Done" in learn.get(f"/learn/{UNIT}").text


def test_fast_track_pill_follows_status_and_skipped_steps_have_no_buttons(learn, session):
    u = session.get(units.Unit, UNIT)
    units.finish_step(session, u, "pretest", 0.9, now=MID)
    units.fast_track(session, u, MID)
    html = learn.get(f"/learn/{UNIT}").text
    assert "Fast-tracked" in html and "Mark as done" not in html  # story and speak are skipped
    units.finish_step(session, u, "quiz", 0.3, now=MID)
    html = learn.get(f"/learn/{UNIT}").text
    assert "Remediation" in html and "Fast-tracked" not in html
    assert "Remediation" in learn.get("/learn").text

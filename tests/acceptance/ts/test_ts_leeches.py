"""Hidden tests for T-S (Leeches). Public contracts from SPEC.md only."""

import re

from ts_conftest_task import make_card
from sqlmodel import select

# --- Feature 1: finding leeches ----------------------------------------------------


def test_f1_sum_across_directions_is_not_leech(session):
    from app.services import cards, srs

    make_card(session, ru="сумма", rec=3, prod=3)
    assert 3 + 3 >= cards.LEECH_LAPSES
    assert srs.leeches(session) == []


def test_f1_production_lapses_count(session):
    from app.services import cards, srs

    card = make_card(session, ru="выход", rec=0, prod=cards.LEECH_LAPSES)
    assert [c.id for c in srs.leeches(session)] == [card.id]


def test_f1_threshold_is_inclusive(session):
    from app.services import cards, srs

    at = make_card(session, ru="ровно", rec=cards.LEECH_LAPSES)
    make_card(session, ru="почти", rec=cards.LEECH_LAPSES - 1)
    assert [c.id for c in srs.leeches(session)] == [at.id]


def test_f1_suspended_excluded(session):
    from app.services import srs

    make_card(session, ru="спящий", rec=9, suspended=True)
    live = make_card(session, ru="живой", rec=6)
    assert [c.id for c in srs.leeches(session)] == [live.id]


def test_f1_worst_first_ties_by_id(session):
    from app.services import srs

    a = make_card(session, ru="альфа", rec=7)
    b = make_card(session, ru="бета", rec=9)
    c = make_card(session, ru="гамма", rec=2, prod=9)
    d = make_card(session, ru="дельта", rec=6)
    e = make_card(session, ru="эпсилон", rec=7, prod=1)
    # worst direction per card: a=7, b=9, c=9, d=6, e=7
    assert [x.id for x in srs.leeches(session)] == [b.id, c.id, a.id, e.id, d.id]


def test_f1_agrees_with_cards_filter(session):
    from app.services import cards, srs

    make_card(session, ru="один", rec=6)
    make_card(session, ru="два", rec=3, prod=3)
    make_card(session, ru="три", rec=0, prod=8)
    make_card(session, ru="четыре", rec=12, suspended=True)
    make_card(session, ru="пять", rec=5, prod=5)
    from_filter = {card.id for card, _ in cards.search_cards(session, leeches=True) if not card.suspended}
    assert {c.id for c in srs.leeches(session)} == from_filter
    assert len(from_filter) == 2


# --- Feature 2: badge in review ---------------------------------------------------


def test_f2_badge_shown_for_leech(session, client):
    make_card(session, ru="пиявка", rec=6, due_past=True)
    assert "data-leech-badge" in client.get("/review").text


def test_f2_badge_links_to_card_edit_page(session, client):
    card = make_card(session, ru="ссылка", rec=7, due_past=True)
    html = client.get("/review").text
    anchors = re.findall(r"<a(?=[\s>])[^>]*>.*?</a>", html, re.S)
    assert any(f'href="/cards/{card.id}"' in a and "data-leech-badge" in a for a in anchors), (
        "the badge must be, or sit inside, a link to /cards/{id}"
    )


def test_f2_no_badge_for_non_leech(session, client):
    from app.models import CardState

    card = make_card(session, ru="здоровый", rec=5, due_past=True)
    html = client.get("/review").text
    assert "здоровый" in html
    assert "data-leech-badge" not in html
    # One more lapse turns the same card into a leech, and the badge appears.
    cs = session.exec(select(CardState).where(CardState.card_id == card.id)).one()
    cs.lapses = 6
    session.add(cs)
    session.commit()
    assert "data-leech-badge" in client.get("/review").text


def test_f2_badge_for_production_direction_leech(session, client):
    make_card(session, ru="обратно", rec=0, prod=6, due_past=True)
    assert "data-leech-badge" in client.get("/review").text


# --- Feature 3: leeches on /cards ---------------------------------------------------


def test_f3_filter_link_shows_count(session, client):
    make_card(session, ru="первая", rec=6)
    make_card(session, ru="вторая", rec=0, prod=7)
    make_card(session, ru="третья", rec=3, prod=3)
    make_card(session, ru="четвёртая", rec=8, suspended=True)
    assert "Leeches (2)" in client.get("/cards").text
    assert "Leeches (2)" in client.get("/cards?leeches=1").text


def test_f3_suspend_button_when_filter_active(session, client):
    make_card(session, ru="плохая", rec=6)
    assert "Suspend all leeches" in client.get("/cards?leeches=1").text
    assert "Suspend all leeches" not in client.get("/cards").text


def test_f3_no_button_without_leeches(session, client):
    make_card(session, ru="хорошая", rec=1)
    html = client.get("/cards?leeches=1").text
    assert "Suspend all leeches" not in html
    assert "Leeches (0)" in html


# --- Feature 4: suspend all leeches ----------------------------------------------------


def _suspended_ids(session):
    from app.models import Card

    session.expire_all()
    return {c.id for c in session.exec(select(Card)).all() if c.suspended}


def test_f4_suspend_leeches_returns_count(session):
    from app.services import srs

    a = make_card(session, ru="раз", rec=6)
    b = make_card(session, ru="два", rec=0, prod=10)
    ok = make_card(session, ru="норма", rec=3, prod=3)
    assert srs.suspend_leeches(session) == 2
    assert _suspended_ids(session) == {a.id, b.id}
    assert ok.id not in _suspended_ids(session)
    assert srs.leeches(session) == []
    assert srs.suspend_leeches(session) == 0


def test_f4_suspended_leave_review_queue(session):
    from datetime import datetime, timezone

    from app.services import srs

    leech = make_card(session, ru="уйду", rec=6, due_past=True)
    other = make_card(session, ru="останусь", rec=0, due_past=True)
    now = datetime.now(timezone.utc)
    assert leech.id in {cs.card_id for cs in srs.build_queue(session, now)}
    srs.suspend_leeches(session)
    queue_cards = {cs.card_id for cs in srs.build_queue(session, now)}
    assert leech.id not in queue_cards and other.id in queue_cards


def test_f4_post_confirm_suspends_all(session, client):
    a = make_card(session, ru="цель", rec=6)
    b = make_card(session, ru="вторая", rec=0, prod=6)
    keep = make_card(session, ru="целая", rec=2)
    r = client.post("/cards/leeches/suspend", data={"confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].endswith("/cards?leeches=1")
    assert _suspended_ids(session) == {a.id, b.id}
    assert keep.id not in _suspended_ids(session)


def test_f4_get_is_confirmation_only(session, client):
    make_card(session, ru="одна", rec=6)
    make_card(session, ru="другая", rec=7)
    make_card(session, ru="третья", rec=9)
    r = client.get("/cards/leeches/suspend")
    assert r.status_code == 200
    assert "3" in r.text
    assert "<form" in r.text.lower() and "confirm" in r.text
    assert _suspended_ids(session) == set()


def test_f4_post_without_confirm_changes_nothing(session, client):
    make_card(session, ru="тихая", rec=6)
    for data in ({}, {"confirm": "no"}):
        r = client.post("/cards/leeches/suspend", data=data, follow_redirects=False)
        assert r.status_code == 200
        assert _suspended_ids(session) == set()


def test_f4_single_card_suspend_route_still_reachable(session, client):
    card = make_card(session, ru="одиночка", rec=0)
    # A leech suspend route registered carelessly must not break the per-card route; and the
    # new route must not 422 (checked above). Here: the per-card toggle still works.
    r = client.post(f"/cards/{card.id}/suspend", follow_redirects=False)
    assert r.status_code == 303
    assert card.id in _suspended_ids(session)
    r = client.post("/cards/leeches/suspend", data={"confirm": "yes"}, follow_redirects=False)
    assert r.status_code == 303


# --- Feature 5: rewrite via Claude --------------------------------------------------------

REWRITE = {
    "example_ru": "Я купи'л молоко́ на вокза'ле",
    "example_en": "I bought milk at the station",
    "mnemonic": "Picture a MOLE drinking milk",
    "notes": "Easy to confuse with молоток",
}


def test_f5_task_uses_sonnet():
    from app.services import claude

    assert claude.Task.leech_rewrite.value == "leech_rewrite"
    assert claude.TASK_MODELS[claude.Task.leech_rewrite] == claude.SONNET


def test_f5_suggest_rewrite_one_call_with_card_in_prompt(session, fake_claude):
    from app.services import cards
    from app.services.claude import ClaudeClient, Task

    card = make_card(session, ru="собака", en="dog", rec=6, example_ru="Моя собака большая", example_en="My dog is big")
    fake_claude.push(REWRITE)
    result = cards.suggest_rewrite(ClaudeClient(session), card)
    assert isinstance(result, cards.LeechRewrite)
    assert result.mnemonic == REWRITE["mnemonic"]
    assert len(fake_claude.calls) == 1
    call = fake_claude.calls[0]
    assert call["task"] == Task.leech_rewrite
    assert call["model"] is cards.LeechRewrite
    for needle in ("собака", "dog", "Моя собака большая"):
        assert needle in call["prompt"]


def test_f5_rewrite_route_renders_suggestion_with_apply(session, client, fake_claude):
    card = make_card(session, ru="пример", en="example", rec=6)
    fake_claude.push(REWRITE)
    r = client.post(f"/cards/{card.id}/rewrite")
    assert r.status_code == 200
    assert "Picture a MOLE drinking milk" in r.text
    assert "Easy to confuse" in r.text
    assert f"/cards/{card.id}/rewrite/apply" in r.text
    assert "Apply" in r.text


def test_f5_rewrite_route_claude_error_inline(session, client, fake_claude):
    from app.services.claude import ClaudeError

    card = make_card(session, ru="ошибка", en="error", rec=6)
    fake_claude.push(ClaudeError("Service busy"))
    r = client.post(f"/cards/{card.id}/rewrite")
    assert r.status_code == 200
    assert "Service busy" in r.text


def test_f5_rewrite_unknown_card_404(session, client, fake_claude):
    card = make_card(session, ru="есть", en="exists", rec=6)
    fake_claude.push(REWRITE, REWRITE)
    assert client.post(f"/cards/{card.id}/rewrite").status_code == 200
    assert client.post("/cards/99999/rewrite").status_code == 404


def test_f5_apply_writes_fields_and_redirects(session, client):
    from app.models import Card

    card = make_card(session, ru="молоко", en="milk", rec=6, example_ru="старый", notes="old note")
    r = client.post(
        f"/cards/{card.id}/rewrite/apply",
        data={"example_ru": "Я пью молоко", "example_en": "I drink milk", "notes": "fresh note"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].endswith(f"/cards/{card.id}")
    session.expire_all()
    card = session.get(Card, card.id)
    assert card.example_ru == "Я пью молоко"
    assert card.example_en == "I drink milk"
    assert card.notes == "fresh note"
    assert card.ru == "молоко" and card.en == "milk"


def test_f5_apply_normalises_stress(session, client):
    from app.models import Card

    card = make_card(session, ru="молоко", en="milk", rec=6)
    client.post(
        f"/cards/{card.id}/rewrite/apply",
        data={"example_ru": "Он купил молокó на вокза'ле", "example_en": "He bought milk at the station", "notes": "n"},
        follow_redirects=False,
    )
    session.expire_all()
    stored = session.get(Card, card.id).example_ru
    assert stored == "Он купил молоко́ на вокза́ле"


def test_f5_apply_keeps_schedule(session, client):
    from app.models import CardState
    from app.services import srs

    card = make_card(session, ru="расписание", en="schedule", rec=7, prod=2, due_past=True)

    def snapshot():
        session.expire_all()
        rows = session.exec(select(CardState).where(CardState.card_id == card.id)).all()
        return {cs.id: (cs.lapses, cs.state, cs.due, cs.reps, cs.stability) for cs in rows}

    before = snapshot()
    client.post(
        f"/cards/{card.id}/rewrite/apply",
        data={"example_ru": "Новый пример", "example_en": "New example", "notes": "new"},
        follow_redirects=False,
    )
    assert snapshot() == before
    assert card.id in {c.id for c in srs.leeches(session)}


def test_f5_edit_page_has_rewrite_button_for_leech(session, client, fake_claude, monkeypatch):
    from app.web import templates

    # The templates' own AI switch (the existing ai_enabled() global) is bound at import time.
    monkeypatch.setitem(templates.env.globals, "ai_enabled", lambda: True)
    card = make_card(session, ru="кнопка", en="button", rec=6)
    assert f"/cards/{card.id}/rewrite" in client.get(f"/cards/{card.id}").text

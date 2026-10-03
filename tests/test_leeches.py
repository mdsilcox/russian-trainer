"""Leeches: edge cases beyond the acceptance tests."""

from sqlmodel import select

from app.models import Card, CardState, Direction
from app.services import cards, srs


def make(session, ru, rec=0, prod=None, **fields):
    card = cards.create_card(session, ru=ru, en="word", **fields)
    cs = session.exec(select(CardState).where(CardState.card_id == card.id)).one()
    cs.lapses = rec
    session.add(cs)
    if prod is not None:
        session.add(CardState(card_id=card.id, direction=Direction.production, lapses=prod))
    session.commit()
    return card


def test_card_with_no_states_is_not_a_leech(session):
    session.add(Card(ru="сирота", en="orphan"))
    session.commit()
    assert srs.leeches(session) == []


def test_suspend_leeches_keeps_lapses(session):
    card = make(session, "пиявка", rec=8)
    srs.suspend_leeches(session)
    session.expire_all()
    cs = session.exec(select(CardState).where(CardState.card_id == card.id)).one()
    assert cs.lapses == 8 and session.get(Card, card.id).suspended


def test_confirmation_page_zero_leeches(client):
    r = client.get("/cards/leeches/suspend")
    assert r.status_code == 200 and "no leeches" in r.text and 'name="confirm"' not in r.text


def test_rewrite_prompt_omits_missing_example(session):
    class Fake:
        def ask_structured(self, task, system, prompt, model, max_tokens=0):
            self.prompt = prompt
            return model(example_ru="Я пью молоко", example_en="I drink milk", mnemonic="m", notes="n")

    card = make(session, "молоко", rec=6)
    fake = Fake()
    result = cards.suggest_rewrite(fake, card)
    assert "(none)" in fake.prompt and result.example_ru == "Я пью молоко"


def test_rewrite_partial_keeps_existing_notes(session, client, monkeypatch):
    from app.routes import cards as routes

    class Fake:
        def __init__(self, session):
            pass

        def ask_structured(self, task, system, prompt, model, max_tokens=0):
            return model(example_ru="Новый пример", example_en="New", mnemonic="hook", notes="slippery")

    monkeypatch.setattr(routes, "ClaudeClient", Fake)
    card = make(session, "память", rec=6, notes="my own note")
    html = client.post(f"/cards/{card.id}/rewrite").text
    assert "<textarea" in html and "Memory hook: hook\nslippery\n\nmy own note</textarea>" in html

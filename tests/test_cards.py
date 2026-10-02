from types import SimpleNamespace

import pytest
from sqlmodel import select

from app.models import Card, CardState, Direction, Module
from app.routes import cards as card_routes
from app.services import cards as svc
from app.services.claude import HAIKU, ClaudeClient
from tests.test_claude import FakeAnthropic, fake_response


def test_normalize_ignores_stress_yo_case_and_spacing():
    assert svc.normalize("  Ещё  вокза́л ") == svc.normalize("еще вокзал")


def test_apostrophe_becomes_stress_mark():
    assert svc.apply_stress_marks("вокза'л") == "вокза́л"
    assert svc.apply_stress_marks("don't") == "don't"


def test_create_card_adds_recognition_state(session):
    card = svc.create_card(session, ru="вокзал", en="station", tags="Travel, transport travel", ru_stressed="вокза'л",
                           example_ru="Где вокза'л?")
    state = session.exec(select(CardState).where(CardState.card_id == card.id)).one()
    assert state.direction == Direction.recognition and state.state == 0
    assert card.tags == "travel transport"
    assert card.ru_stressed == "вокза́л"
    assert card.example_ru == "Где вокза́л?"
    assert card.notes is None


def test_create_card_requires_ru_and_en(session):
    with pytest.raises(ValueError):
        svc.create_card(session, ru="вокзал", en="")


def test_find_duplicate(session):
    card = svc.create_card(session, ru="ещё", en="more")
    assert svc.find_duplicate(session, "Еще").id == card.id
    assert svc.find_duplicate(session, "еще", exclude_id=card.id) is None


def test_search_filters(session):
    a = svc.create_card(session, ru="вокза́л", en="station", tags="travel")
    b = svc.create_card(session, ru="молоко", en="milk", tags="food", source_module=Module.story)
    session.exec(select(CardState).where(CardState.card_id == b.id)).one().lapses = 7
    session.commit()

    def ids(**kw):
        return [c.id for c, _ in svc.search_cards(session, **kw)]

    assert ids(q="вокзал") == [a.id]
    assert ids(q="MILK") == [b.id]
    assert ids(tag="travel") == [a.id]
    assert ids(source="story") == [b.id]
    assert ids(leeches=True) == [b.id]
    assert set(ids()) == {a.id, b.id}


def test_add_card_via_form_and_duplicate_warning(client, session):
    response = client.post("/cards/new", data={"ru": "поезд", "en": "train"}, follow_redirects=False)
    assert response.status_code == 303
    dup = client.post("/cards/new", data={"ru": "Поезд", "en": "train"})
    assert dup.status_code == 409 and "already in your deck" in dup.text
    forced = client.post("/cards/new", data={"ru": "Поезд", "en": "train", "force": "1"}, follow_redirects=False)
    assert forced.status_code == 303
    assert len(session.exec(select(Card)).all()) == 2


def test_browse_edit_suspend_delete(client, session):
    card_id = svc.create_card(session, ru="метро", en="metro").id
    assert "метро" in client.get("/cards").text
    client.post(f"/cards/{card_id}", data={"ru": "метро", "en": "underground", "stress_verified": "on"})
    client.post(f"/cards/{card_id}/suspend")
    session.expire_all()
    card = session.get(Card, card_id)
    assert card.en == "underground" and card.stress_verified and card.suspended
    client.post(f"/cards/{card_id}/delete")
    session.expunge_all()
    assert session.get(Card, card_id) is None
    assert client.get(f"/cards/{card_id}").status_code == 404


def test_enrich_fills_only_empty_fields(client, monkeypatch):
    parsed = svc.CardEnrichment(
        ru_stressed="вокза́л", en="railway station", pos="noun", gender="m", aspect=None,
        aspect_partner=None, example_ru="Где вокза́л?", example_en="Where is the station?", notes=None,
    )
    fake = FakeAnthropic(fake_response(model=HAIKU, parsed=parsed))
    monkeypatch.setattr(card_routes, "ClaudeClient", lambda session: ClaudeClient(session, client=fake))

    response = client.post("/cards/enrich/suggest", data={"ru": "вокзал", "en": "station"})
    assert response.status_code == 200
    assert 'value="station"' in response.text  # your gloss is kept
    assert "вокза́л" in response.text and "Где вокза́л?" in response.text
    assert response.text.count("suggested</em>") == 5  # ru_stressed, pos, gender, example_ru, example_en


def test_enrich_without_key_shows_message(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from app.config import get_config
    get_config.cache_clear()
    try:
        response = client.post("/cards/enrich/suggest", data={"ru": "вокзал"})
    finally:
        get_config.cache_clear()
    assert "ANTHROPIC_API_KEY" in response.text


def test_delete_reviewed_card_removes_history_and_unlinks_mistakes(client, session):
    from app.models import Category, Mistake, ReviewLog

    card = svc.create_card(session, ru="вокзал", en="station")
    card_id = card.id
    cs = session.exec(select(CardState).where(CardState.card_id == card_id)).one()
    client.post(f"/review/{cs.id}", data={"rating": 3})
    session.add(Mistake(module=Module.story, category=Category.case, wrong="на вокзал", right="на вокзале",
                        card_id=card_id))
    session.commit()

    assert client.post(f"/cards/{card_id}/delete", follow_redirects=False).status_code == 303
    session.expunge_all()
    assert session.get(Card, card_id) is None
    assert session.exec(select(ReviewLog)).all() == []
    assert session.exec(select(Mistake)).one().card_id is None


def test_latin_accents_inside_russian_words_are_fixed():
    assert svc.fix_latin_accents("купé") == "купе́"
    assert svc.fix_latin_accents("мóре") == "мо́ре"
    assert svc.fix_latin_accents("café crème") == "café crème"  # French stays French
    assert svc.apply_stress_marks("купé и вокза'л") == "купе́ и вокза́л"


def test_stress_mark_dropped_in_words_with_yo():
    assert svc.apply_stress_marks("Проводни́к при́нёс чай") == "Проводни́к принёс чай"
    assert svc.apply_stress_marks("ещё вокза'л") == "ещё вокза́л"

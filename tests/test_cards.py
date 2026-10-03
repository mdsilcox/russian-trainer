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


# --- Card kinds ------------------------------------------------------------------

def test_create_card_kind_defaults(session):
    assert svc.create_card(session, ru="вокзал", en="station").kind == "word"
    assert svc.create_card(session, ru="где вокзал", en="where is the station").kind == "chunk"
    assert svc.create_card(session, ru="из Москвы", en="from Moscow", kind="form").kind == "form"
    assert svc.create_card(session, ru="кто-то", en="someone").kind == "word"  # hyphen is not a space
    with pytest.raises(ValueError):
        svc.create_card(session, ru="слово", en="word", kind="bogus")


def test_migration_adds_kind_and_backfills_chunks(engine):
    from sqlalchemy import text

    from app.db import MIGRATIONS, migrate

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE cards DROP COLUMN kind"))
        conn.execute(text("DELETE FROM schema_version WHERE version = :v"), {"v": len(MIGRATIONS)})
        conn.execute(text("INSERT INTO cards (ru, en, tags, source_module, stress_verified, suspended, created_at) "
                          "VALUES ('вокзал', 'station', '', 'manual', 0, 0, '2026-01-01'), "
                          "('где вокзал', 'where is the station', '', 'manual', 0, 0, '2026-01-01')"))
    assert migrate(engine) == len(MIGRATIONS)
    with engine.connect() as conn:
        kinds = dict(conn.execute(text("SELECT ru, kind FROM cards")).all())
    assert kinds == {"вокзал": "word", "где вокзал": "chunk"}
    assert migrate(engine) == len(MIGRATIONS)  # idempotent


def enrichment_with_extras():
    return svc.CardEnrichment(
        ru_stressed="рука́", en="hand", pos="noun", gender="f", aspect=None, aspect_partner=None,
        example_ru="У меня́ боли́т рука́.", example_en="My hand hurts.", notes=None,
        forms=[
            svc.FormSuggestion(ru="в руке́", en="in the hand", note="prepositional after в"),
            svc.FormSuggestion(ru="без руки́", en="without a hand", note="genitive after без"),
        ],
        stress_shift=svc.StressShift(base="рука́", shifted="ру́ку", en="hand (accusative)",
                                     note="stress moves to the stem in the accusative singular"),
    )


def use_enrichment(monkeypatch, parsed):
    fake = FakeAnthropic(fake_response(model=HAIKU, parsed=parsed))
    monkeypatch.setattr(card_routes, "ClaudeClient", lambda session: ClaudeClient(session, client=fake))


def test_enrich_shows_suggestions_with_first_form_ticked(client, monkeypatch):
    use_enrichment(monkeypatch, enrichment_with_extras())
    page = client.post("/cards/enrich/suggest", data={"ru": "рука"}).text
    assert "Also add as cards" in page and "в руке́" in page and "ру́ку" in page
    assert page.count('name="extra"') == 3
    assert 'value="form:0" checked' in page
    assert 'value="form:1" checked' not in page and 'value="stress" checked' not in page


def test_enrich_on_edit_form_gives_no_suggestions(client, monkeypatch):
    use_enrichment(monkeypatch, enrichment_with_extras())
    page = client.post("/cards/enrich/suggest", data={"ru": "рука", "editing": "1"}).text
    assert "Also add as cards" not in page


def post_with_extras(client, extra, **overrides):
    data = {
        "ru": "рука", "en": "hand",
        "form_ru_0": "в руке́", "form_en_0": "in the hand", "form_note_0": "prepositional after в",
        "form_ru_1": "без руки́", "form_en_1": "without a hand", "form_note_1": "genitive after без",
        "stress_base": "рука́", "stress_shifted": "ру́ку", "stress_en": "hand (accusative)",
        "stress_note": "stress moves to the stem in the accusative singular",
        "extra": extra,
    } | overrides
    return client.post("/cards/new", data=data, follow_redirects=False)


def test_saving_creates_ticked_extra_cards(client, session):
    r = post_with_extras(client, ["form:0", "stress"])
    assert r.status_code == 303 and "extras=2" in r.headers["location"]
    session.expunge_all()
    cards = {c.ru: c for c in session.exec(select(Card)).all()}
    assert set(cards) == {"рука", "в руке", "руку"}
    form = cards["в руке"]
    assert form.kind == "form" and form.ru_stressed == "в руке́" and form.tags == "form"
    assert form.source_module == cards["рука"].source_module == Module.manual
    assert "prepositional after в" in form.notes and "рука" in form.notes
    stress = cards["руку"]
    assert stress.kind == "stress" and stress.ru_stressed == "ру́ку" and stress.tags == "stress"
    assert "рука" in stress.notes and "accusative" in stress.notes
    assert cards["рука"].kind == "word"
    assert len(session.exec(select(CardState)).all()) == 3  # each extra card is reviewable


def test_saving_with_nothing_ticked_adds_only_main_card(client, session):
    post_with_extras(client, [])
    assert [c.ru for c in session.exec(select(Card)).all()] == ["рука"]


def test_extra_cards_skip_duplicates(client, session):
    svc.create_card(session, ru="в руке", en="in the hand")
    svc.create_card(session, ru="руку", en="hand (acc)")
    r = post_with_extras(client, ["form:0", "form:1", "stress"])
    assert "extras=1" in r.headers["location"]  # only "без руки" is new
    session.expunge_all()
    assert sorted(c.ru for c in session.exec(select(Card)).all()) == ["без руки", "в руке", "рука", "руку"]


def test_duplicate_warning_keeps_suggestions(client, session):
    svc.create_card(session, ru="рука", en="hand")
    page = post_with_extras(client, ["form:0"])
    assert page.status_code == 409
    assert 'name="form_ru_1"' in page.text and 'value="form:0" checked' in page.text


# --- Review badge and list filter ----------------------------------------------------

def test_review_badge_only_for_non_word_kinds(client, session):
    card = svc.create_card(session, ru="вокзал", en="station")
    assert "rv-kind" not in client.get("/review").text
    for kind, label in [("form", "Form in context"), ("stress", "Stress shift"), ("chunk", "Phrase")]:
        card.kind = kind
        session.add(card)
        session.commit()
        assert label in client.get("/review").text


def test_list_kind_filter(client, session):
    svc.create_card(session, ru="вокзал", en="station")
    svc.create_card(session, ru="из Москвы", en="from Moscow", kind="form")
    svc.create_card(session, ru="где вокзал", en="where is the station")
    assert [c.ru for c, _ in svc.search_cards(session, kind="chunk")] == ["где вокзал"]
    page = client.get("/cards?kind=form").text
    assert "из Москвы" in page and "где вокзал" not in page
    assert '<option value="form" selected>' in page
    assert "1 card" in page


def test_form_repeating_the_stress_shift_is_dropped(client, session, monkeypatch):
    parsed = enrichment_with_extras()
    parsed.forms.insert(0, svc.FormSuggestion(ru="Дай мне ру́ку", en="Give me your hand", note="accusative"))
    use_enrichment(monkeypatch, parsed)
    page = client.post("/cards/enrich/suggest", data={"ru": "рука"}).text
    assert "Дай мне" not in page and page.count('name="extra"') == 3
    assert 'value="form:0" checked' in page  # the first remaining form is ticked

    r = post_with_extras(client, ["form:0", "stress"], form_ru_0="Дай мне ру́ку", form_en_0="Give me your hand")
    assert "extras=1" in r.headers["location"]
    assert sorted(c.ru for c in session.exec(select(Card)).all()) == ["рука", "руку"]


def test_stress_overlap_ignores_punctuation():
    forms = [{"ru": "Дай мне ру́ку."}, {"ru": "в руке́"}, {"ru": "«Ру́ку!»"}]
    assert svc.drop_stress_overlap(forms, {"shifted": "ру́ку"}) == [{"ru": "в руке́"}]

"""Feature 3: tutor word lists."""

from datetime import datetime, timedelta, timezone

import pytest

from tl_h import D, STRESS, enrichment, input_tag, location_ok, make_card


def _lesson(session, topic="Cafe talk"):
    from app.services import lessons

    return lessons.create_lesson(session, D, topic)


@pytest.mark.parametrize("sep", ["—", "–", " - ", ":", "\t", " — ", ": "])
def test_f3_parse_separators(sep):
    from app.services import lessons

    items, errors = lessons.parse_word_list(f"привет{sep}hello")
    assert errors == []
    assert [(i.ru, i.en) for i in items] == [("привет", "hello")]


def test_f3_parse_first_separator_wins():
    from app.services import lessons

    items, errors = lessons.parse_word_list("да — yes: sure\nнет: no - never")
    assert errors == []
    assert [(i.ru, i.en) for i in items] == [("да", "yes: sure"), ("нет", "no - never")]


def test_f3_parse_hyphenated_words():
    from app.services import lessons

    text = "из-за — because of\nчто-то - something\nкто-нибудь: somebody\nкое-как\tsomehow"
    items, errors = lessons.parse_word_list(text)
    assert errors == []
    assert [(i.ru, i.en) for i in items] == [
        ("из-за", "because of"), ("что-то", "something"), ("кто-нибудь", "somebody"), ("кое-как", "somehow")]


def test_f3_parse_no_split_on_bare_hyphen():
    from app.services import lessons

    items, errors = lessons.parse_word_list("из-за")
    assert items == []
    assert len(errors) == 1 and "из-за" in errors[0]


def test_f3_parse_blank_lines_and_errors():
    from app.services import lessons

    items, errors = lessons.parse_word_list("\n\nпривет — hello\n   \nэто без разделителя\nпока — bye\n")
    assert [(i.ru, i.en) for i in items] == [("привет", "hello"), ("пока", "bye")]
    assert len(errors) == 1 and "это без разделителя" in errors[0]


def test_f3_worditem_is_stripped_dataclass():
    import dataclasses

    from app.services import lessons

    assert dataclasses.is_dataclass(lessons.WordItem)
    items, _ = lessons.parse_word_list("  привет  –  hello there  ")
    assert items[0].ru == "привет" and items[0].en == "hello there"
    assert lessons.WordItem(ru="а", en="b").ru == "а"


def test_f3_module_tutor_value():
    from app.models import Module

    assert Module("tutor") is Module.tutor
    assert Module.tutor.value == "tutor"


def test_f3_add_words_fields(session):
    from app.models import Module
    from app.services import lessons

    lesson = _lesson(session)
    made = lessons.add_words(session, lesson.id, [
        {"ru": "привет", "en": "hello", "ru_stressed": "приве'т", "example_ru": "Приве'т, как дела?", "example_en": "Hi, how are you?", "notes": "informal"},
        {"ru": "купе", "en": "compartment", "ru_stressed": "купé", "example_ru": "", "example_en": "", "notes": ""},
    ])
    assert len(made) == 2
    first, second = made
    for card in made:
        assert card.id is not None
        assert card.source_module == Module.tutor
        assert card.source_ref_id == lesson.id
        assert "tutor" in card.tags.split()
    assert first.ru == "привет" and first.en == "hello"
    assert first.ru_stressed == "приве" + "́" + "т"
    assert first.example_ru == "Приве" + "́" + "т, как дела?"
    assert first.example_en == "Hi, how are you?" and first.notes == "informal"
    assert second.ru_stressed == "купе" + STRESS


def test_f3_add_words_skips_duplicates(session):
    from sqlmodel import select

    from app.models import Card
    from app.services import lessons

    make_card(session, ru="привет", en="hello")
    lesson = _lesson(session)
    made = lessons.add_words(session, lesson.id, [
        {"ru": "приве́т", "en": "hi"}, {"ru": "спасибо", "en": "thanks"}, {"ru": "спаси́бо", "en": "thank you"}])
    assert [c.ru for c in made] == ["спасибо"]
    assert sorted(c.ru for c in session.exec(select(Card)).all()) == ["привет", "спасибо"]
    assert lessons.add_words(session, lesson.id, []) == []


def test_f3_words_page_without_ai(client, session):
    lesson = _lesson(session)
    r = client.post(f"/lessons/{lesson.id}/words", data={"text": "привет — hello\nпока - bye\nбез разделителя"})
    assert r.status_code == 200
    for text in ["привет", "hello", "пока", "bye", "без разделителя"]:
        assert text in r.text, text
    assert input_tag(r.text, "items-0-ru") and 'value="привет"' in input_tag(r.text, "items-0-ru")
    assert input_tag(r.text, "items-1-ru") and 'value="пока"' in input_tag(r.text, "items-1-ru")
    for i in (0, 1):
        keep = input_tag(r.text, f"items-{i}-keep")
        assert keep and "checked" in keep and 'type="checkbox"' in keep
    assert input_tag(r.text, "items-2-ru") is None


def test_f3_words_page_when_enrich_fails(client, session, fake_claude):
    from app.services.claude import ClaudeError

    lesson = _lesson(session)
    fake_claude.push(ClaudeError("busy"), enrichment("пока́", "bye", example_ru="Ну, пока́!"))
    r = client.post(f"/lessons/{lesson.id}/words", data={"text": "привет — hello\nпока — bye"})
    assert r.status_code == 200
    assert len(fake_claude.calls) == 2
    assert input_tag(r.text, "items-0-ru") and input_tag(r.text, "items-1-ru")
    assert "привет" in r.text and "hello" in r.text and "bye" in r.text
    assert "Ну, пока́!" in r.text


def test_f3_words_page_enriched(client, session, fake_claude):
    from app.services.claude import Task

    lesson = _lesson(session)
    fake_claude.push(enrichment("приве́т", "hello", example_ru="Приве́т, Анна!", example_en="Hi, Anna!"),
                     enrichment("спаси́бо", "thanks", example_ru="Большо́е спаси́бо!", example_en="Thanks a lot!"))
    r = client.post(f"/lessons/{lesson.id}/words", data={"text": "привет — hello\nспасибо — thanks"})
    assert r.status_code == 200
    assert len(fake_claude.calls) == 2
    assert all(c["task"] == Task.enrichment for c in fake_claude.calls)
    assert "Приве́т, Анна!" in r.text and "Большо́е спаси́бо!" in r.text
    tag = input_tag(r.text, "items-0-ru_stressed")
    assert tag and "приве́т" in tag
    assert input_tag(r.text, "items-1-example_ru") and input_tag(r.text, "items-1-example_en") is not None
    assert "checked" in input_tag(r.text, "items-1-keep")


def test_f3_words_add_route(client, session):
    from sqlmodel import select

    from app.models import Card, Module

    lesson = _lesson(session)
    r = client.post(f"/lessons/{lesson.id}/words/add", data={
        "items-0-ru": "привет", "items-0-en": "hello", "items-0-ru_stressed": "приве́т", "items-0-example_ru": "Приве́т!",
        "items-0-example_en": "Hi!", "items-0-notes": "", "items-0-keep": "on",
        "items-1-ru": "пока", "items-1-en": "bye", "items-1-ru_stressed": "", "items-1-example_ru": "", "items-1-example_en": "",
        "items-1-notes": "",
        "items-2-ru": "спасибо", "items-2-en": "thanks", "items-2-ru_stressed": "", "items-2-example_ru": "", "items-2-example_en": "",
        "items-2-notes": "", "items-2-keep": "on",
    }, follow_redirects=False)
    assert r.status_code == 303 and location_ok(r, f"/lessons/{lesson.id}")
    cards = {c.ru: c for c in session.exec(select(Card)).all()}
    assert set(cards) == {"привет", "спасибо"}
    assert cards["привет"].source_module == Module.tutor and cards["привет"].source_ref_id == lesson.id
    assert "tutor" in cards["привет"].tags.split()
    assert cards["привет"].ru_stressed == "приве́т"


def test_f3_words_add_route_duplicate_is_not_an_error(client, session):
    lesson = _lesson(session)
    make_card(session, ru="привет", en="hello")
    r = client.post(f"/lessons/{lesson.id}/words/add", data={
        "items-0-ru": "привет", "items-0-en": "hello", "items-0-keep": "on",
        "items-1-ru": "пока", "items-1-en": "bye", "items-1-keep": "on"}, follow_redirects=False)
    assert r.status_code == 303
    assert location_ok(r, f"/lessons/{lesson.id}")


def test_f3_dashboard_after_tutor_review(client, session):
    """stats.retention_by_source indexes SOURCE_LABELS for every module that has reviews."""
    import fsrs
    from sqlmodel import select

    from app.models import CardState
    from app.services import lessons, srs

    lesson = _lesson(session)
    card = lessons.add_words(session, lesson.id, [{"ru": "привет", "en": "hello"}])[0]
    cs = session.exec(select(CardState).where(CardState.card_id == card.id)).one()
    now = datetime.now(timezone.utc)
    srs.review(session, cs, fsrs.Rating.Good, now - timedelta(days=2))
    srs.review(session, cs, fsrs.Rating.Good, now - timedelta(days=1))
    srs.review(session, cs, fsrs.Rating.Again, now)
    r = client.get("/dashboard")
    assert r.status_code == 200


def test_f3_review_source_line(client, session):
    from app.services import lessons

    lesson = _lesson(session, "Cafe talk")
    lessons.add_words(session, lesson.id, [{"ru": "привет", "en": "hello"}])
    r = client.get("/review")
    assert r.status_code == 200
    assert "from your lesson ‘Cafe talk’" in r.text

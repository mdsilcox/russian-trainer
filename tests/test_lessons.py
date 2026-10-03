"""Lane C extras: things the acceptance tests do not pin down."""

from datetime import date, timedelta

import pytest

from app.services import lessons

D = date(2026, 3, 10)
ENRICHED = {"ru_stressed": "вода́", "en": "water", "pos": "noun", "gender": "f", "aspect": None,
            "aspect_partner": None, "example_ru": "Во́да хо́лодная.", "example_en": "The water is cold.",
            "notes": None, "forms": [], "stress_shift": None}


@pytest.mark.parametrize("path,expected", [
    ("/lessons/3", "/lessons/3"), ("//evil.example", "/"), ("/\\evil.example", "/"), ("/a\r\nb", "/"),
    ("", "/"), ("https://x.example", "/"), ("evil", "/"),
])
def test_safe_path(path, expected):
    assert lessons.safe_path(path, "/") == expected


def test_parse_materials():
    got = lessons.parse_materials("Site | https://a.example/x?y=1|2\nhttps://b.example\n\nNo title| http://c.example")
    assert got == [{"title": "Site", "url": "https://a.example/x?y=1|2"}, {"title": "", "url": "https://b.example"},
                   {"title": "No title", "url": "http://c.example"}]


def test_parse_word_list_empty_side_is_an_error():
    items, errors = lessons.parse_word_list("привет —\n— hello")
    assert items == [] and len(errors) == 2


def test_due_label():
    assert [lessons.due_label(D + timedelta(days=n), D) for n in (-1, 0, 1, 2)] == ["overdue", "today", "tomorrow", "Thursday"]


def test_today_panel_is_titled_next_lesson(client):
    r = client.get("/")
    assert "<h3>Next lesson</h3>" in r.text and "<h3>This week" not in r.text


def test_question_control_only_where_chosen(client):
    assert "data-tutor-question" in client.get("/review").text
    assert "data-tutor-question" not in client.get("/cards").text


def test_words_page_keeps_hidden_enrichment_fields(client, session, monkeypatch):
    lesson = lessons.create_lesson(session, D, "Cafe")
    from app.routes import lessons as routes
    from app.services.cards import CardEnrichment

    class Fake:
        def __init__(self, session):
            pass

        def ask_structured(self, task, system, prompt, model, max_tokens=0):
            return CardEnrichment.model_validate(ENRICHED)

    monkeypatch.setattr(routes, "ClaudeClient", Fake)
    html = client.post(f"/lessons/{lesson.id}/words", data={"text": "вода — water"}).text
    assert 'name="items-0-gender" value="f"' in html
    client.post(f"/lessons/{lesson.id}/words/add", data={
        "items-0-ru": "вода", "items-0-en": "water", "items-0-gender": "f", "items-0-pos": "noun", "items-0-keep": "on"})
    card = lessons.lesson_words(session, lesson.id)[0]
    assert card.gender == "f" and card.pos == "noun"


def test_unknown_lesson_summary_and_words_404(client):
    assert client.post("/lessons/999/summary").status_code == 404
    assert client.post("/lessons/999/words", data={"text": "а — b"}).status_code == 404

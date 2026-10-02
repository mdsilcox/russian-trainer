import pytest
from sqlmodel import select

from app.models import Category, Mistake, Module, Story, TranslationAttempt
from app.services import workshop


def test_create_story_with_and_without_translation(session):
    story = workshop.create_story(session, "Поезд", "ru", "Я ехал в Казань.", "")
    assert workshop.attempts_for(session, story.id) == []
    other = workshop.create_story(session, "The train", "en", "I took the train.", "Я поехал на поезде.")
    assert [a.text for a in workshop.attempts_for(session, other.id)] == ["Я поехал на поезде."]


@pytest.mark.parametrize("title, lang, text", [("", "en", "x"), ("T", "de", "x"), ("T", "en", "  ")])
def test_create_story_validation(session, title, lang, text):
    with pytest.raises(ValueError):
        workshop.create_story(session, title, lang, text)


def test_word_diff_marks_changes():
    diff = workshop.word_diff("Я поехал на вокзал.", "Я поехал на вокзале.")
    assert ("del", "вокзал.") in diff and ("ins", "вокзале.") in diff
    assert "".join(t for op, t in diff if op != "del") == "Я поехал на вокзале."


def test_parse_import_multiple_stories():
    text = """# The night train
## EN
I took the night train.
## RU
Я поехал на ночном поезде.

# Рынок
## RU
Мы пошли на рынок.
"""
    parsed, errors = workshop.parse_import(text)
    assert errors == []
    assert [(p.title, p.source_lang, p.translation) for p in parsed] == [
        ("The night train", "en", "Я поехал на ночном поезде."),
        ("Рынок", "ru", ""),
    ]


def test_parse_import_reports_missing_sections():
    parsed, errors = workshop.parse_import("# Only a title\nno sections here")
    assert parsed == [] and "Only a title" in errors[0]


def test_list_stories_counts_attempts_and_mistakes(session):
    story = workshop.create_story(session, "T", "en", "Text.", "Текст.")
    attempt = workshop.add_attempt(session, story, "Текст!")
    session.add(Mistake(module=Module.story, ref_id=attempt.id, category=Category.case, wrong="a", right="b"))
    session.commit()
    row = workshop.list_stories(session)[0]
    assert (row.attempts, row.mistakes) == (2, 1)


def test_story_pages_end_to_end(client, session):
    response = client.post("/workshop/new", data={"title": "Метро", "source_lang": "en",
                                                   "source_text": "We took the metro.", "translation": "Мы ехали на метро."},
                           follow_redirects=False)
    assert response.status_code == 303
    story_id = int(response.headers["location"].rsplit("/", 1)[1])

    client.post(f"/workshop/{story_id}/attempts", data={"text": "Мы поехали на метро."})
    page = client.get(f"/workshop/{story_id}").text
    assert "Attempt 2" in page and "<ins>поехали</ins>" in page
    assert "Метро" in client.get("/workshop").text

    assert client.post("/workshop/new", data={"title": "", "source_text": "x"}).status_code == 422
    empty = client.post(f"/workshop/{story_id}/attempts", data={"text": " "}, follow_redirects=False)
    assert "error=empty" in empty.headers["location"]

    client.post(f"/workshop/{story_id}/delete")
    session.expunge_all()
    assert session.get(Story, story_id) is None
    assert session.exec(select(TranslationAttempt)).all() == []


def test_import_preview_then_confirm(client, session):
    text = "# A\n## EN\nHello.\n## RU\nПривет.\n\n# B\n## RU\nПока."
    preview = client.post("/workshop/import", data={"text": text})
    assert "Ready to import 2 stories" in preview.text
    assert session.exec(select(Story)).all() == []
    done = client.post("/workshop/import", data={"text": text, "confirm": "1"}, follow_redirects=False)
    assert done.headers["location"] == "/workshop?imported=2"
    assert len(session.exec(select(Story)).all()) == 2

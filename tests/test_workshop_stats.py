import re

import pytest

from app.models import Story
from app.services import workshop

ACUTE = chr(0x0301)


def text_of(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


# --- word_count ---------------------------------------------------------------------------


def test_word_count_example_with_stress_hyphen_apostrophe_and_dash():
    text = f"Я иду{ACUTE} домо{ACUTE}й из-за дождя{ACUTE} — don't worry!"
    assert workshop.word_count(text) == 7


@pytest.mark.parametrize(
    "text, expected",
    [
        ("", 0),
        ("   \n ", 0),
        ("— ... !", 0),
        ("- – — ...", 0),
        ("В 2027 году", 3),
        ("кто-нибудь уже", 2),
        ("don’t stop", 2),
        ("one,two", 2),
        ("a - b", 2),
        ("Hello, world.", 2),
    ],
)
def test_word_count(text, expected):
    assert workshop.word_count(text) == expected


def test_stress_mark_at_end_of_word_does_not_add_a_word():
    assert workshop.word_count(f"дождя{ACUTE}") == 1
    assert workshop.word_count(f"из-за дождя{ACUTE}.") == 2


# --- reading_minutes ----------------------------------------------------------------------


def test_reading_minutes_zero_and_rounding_up():
    assert workshop.reading_minutes(0, "en") == 0
    assert workshop.reading_minutes(0, "ru") == 0
    assert workshop.reading_minutes(1, "en") == 1
    assert workshop.reading_minutes(180, "en") == 1
    assert workshop.reading_minutes(181, "en") == 2
    assert workshop.reading_minutes(120, "ru") == 1
    assert workshop.reading_minutes(121, "ru") == 2


def test_reading_minutes_russian_slower_than_english_and_unknown_uses_english():
    assert workshop.reading_minutes(360, "en") == 2
    assert workshop.reading_minutes(360, "ru") == 3
    assert workshop.reading_minutes(360, "de") == 2


# --- StoryRow and the page ------------------------------------------------------------------


def test_story_row_fields(session):
    english = workshop.create_story(session, "Train", "en", " ".join(["word"] * 214))
    russian = workshop.create_story(session, "Поезд", "ru", " ".join(["слово"] * 121), "Translation")
    rows = {r.story.id: r for r in workshop.list_stories(session)}
    assert (rows[english.id].words, rows[english.id].reading_minutes, rows[english.id].attempts) == (214, 2, 0)
    assert (rows[russian.id].words, rows[russian.id].reading_minutes, rows[russian.id].attempts) == (121, 2, 1)
    assert rows[russian.id].mistakes == 0


def test_workshop_page_shows_story_stats(client, session):
    story = workshop.create_story(session, "Train", "en", " ".join(["word"] * 214))
    for text in ("a", "b", "c"):
        workshop.add_attempt(session, story, text)
    page = text_of(client.get("/workshop").text)
    assert "214 words · 2 min read · 3 attempts" in page


def test_workshop_page_singular_and_zero(client, session):
    workshop.create_story(session, "Short", "ru", "Привет", "")
    page = text_of(client.get("/workshop").text)
    assert "1 word · 1 min read · 0 attempts" in page
    workshop.add_attempt(session, session.get(Story, 1), "Hello")
    assert "1 word · 1 min read · 1 attempt " in text_of(client.get("/workshop").text) + " "


def test_workshop_page_links_to_cloze(client):
    html = client.get("/workshop").text
    assert 'href="/cloze"' in html
    assert "Make cloze cards from your sentences" in html

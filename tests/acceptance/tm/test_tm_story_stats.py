"""Feature 3: story stats on the workshop list."""

from datetime import datetime, timedelta, timezone

import pytest

from tm_helpers import page_text

T0 = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)


def words_text(n, word="слово"):
    return " ".join([word] * n) + "."


def add_story(session, lang, text, title="Story", attempts=0):
    from app.models import Story, TranslationAttempt

    story = Story(title=title, source_lang=lang, source_text=text)
    session.add(story)
    session.commit()
    for i in range(attempts):
        session.add(TranslationAttempt(story_id=story.id, text="Текст попытки.", created_at=T0 + timedelta(minutes=i)))
    session.commit()
    return story


# --- word_count -------------------------------------------------------------------------------


def test_f3_word_count_basic():
    from app.services import workshop

    assert workshop.word_count("Мама мыла раму") == 3
    assert workshop.word_count("Привет, мир!") == 2
    assert workshop.word_count("I took the night train to Kazan.") == 7
    assert workshop.word_count("Один\nдва\n\nтри\tчетыре") == 4


def test_f3_word_count_empty():
    from app.services import workshop

    assert workshop.word_count("") == 0
    assert workshop.word_count("   \n\t ") == 0
    assert workshop.word_count("... !? , ;") == 0


def test_f3_word_count_stress_marks():
    from app.services import workshop

    assert workshop.word_count("вокза́л") == 1
    assert workshop.word_count("Я жду на вокза́ле, а он идёт в магази́н.") == 9
    assert workshop.word_count("Молоде́ц!") == 1


def test_f3_word_count_hyphen_and_apostrophe():
    from app.services import workshop

    assert workshop.word_count("Он не пришёл из-за дождя") == 5
    assert workshop.word_count("кто-нибудь") == 1
    assert workshop.word_count("I don't know") == 3


def test_f3_word_count_lone_dashes_and_punctuation():
    from app.services import workshop

    assert workshop.word_count("Мама — дома") == 2
    assert workshop.word_count("Мама - дома") == 2
    assert workshop.word_count("Мама – дома — папа") == 3
    assert workshop.word_count("— Привет! — сказал он.") == 3


def test_f3_word_count_digits():
    from app.services import workshop

    assert workshop.word_count("В 2024 году было 365 дней") == 6
    assert workshop.word_count("100500") == 1


# --- reading_minutes --------------------------------------------------------------------------


def test_f3_reading_minutes_by_language():
    from app.services import workshop

    assert workshop.reading_minutes(180, "en") == 1
    assert workshop.reading_minutes(180, "ru") == 2
    assert workshop.reading_minutes(120, "ru") == 1
    assert workshop.reading_minutes(360, "en") == 2
    assert workshop.reading_minutes(360, "ru") == 3


def test_f3_reading_minutes_rounds_up():
    from app.services import workshop

    assert workshop.reading_minutes(1, "en") == 1
    assert workshop.reading_minutes(181, "en") == 2
    assert workshop.reading_minutes(121, "ru") == 2
    assert workshop.reading_minutes(241, "ru") == 3
    assert isinstance(workshop.reading_minutes(214, "en"), int)


def test_f3_reading_minutes_zero_words():
    from app.services import workshop

    assert workshop.reading_minutes(0, "en") == 0
    assert workshop.reading_minutes(0, "ru") == 0


# --- list_stories -----------------------------------------------------------------------------


def row_for(session, story):
    from app.services import workshop

    return next(r for r in workshop.list_stories(session) if r.story.id == story.id)


def test_f3_list_stories_words_and_minutes(session):
    en = add_story(session, "en", words_text(200, "word"), title="English")
    ru = add_story(session, "ru", words_text(130), title="Русский")
    en_row, ru_row = row_for(session, en), row_for(session, ru)
    assert (en_row.words, en_row.reading_minutes) == (200, 2)
    assert (ru_row.words, ru_row.reading_minutes) == (130, 2)
    short_ru = add_story(session, "ru", words_text(110), title="Короткий")
    assert row_for(session, short_ru).reading_minutes == 1


def test_f3_list_stories_counts_stressed_words(session):
    story = add_story(session, "ru", "Мы идём на вокза́л и в магази́н.", title="Ударения")
    assert row_for(session, story).words == 7


def test_f3_attempts_keep_meaning(session):
    story = add_story(session, "en", words_text(10, "word"), attempts=3)
    other = add_story(session, "en", words_text(10, "word"), title="Other", attempts=0)
    assert row_for(session, story).attempts == 3
    assert row_for(session, story).words == 10
    assert row_for(session, other).attempts == 0


# --- page -------------------------------------------------------------------------------------


def test_f3_page_shows_stats_line(client, session):
    add_story(session, "en", words_text(214, "word"), title="Night train", attempts=3)
    text = page_text(client.get("/workshop").text)
    assert "214 words · 2 min read · 3 attempts" in text


def test_f3_page_russian_story_uses_russian_speed(client, session):
    add_story(session, "ru", words_text(130), title="Поезд", attempts=2)
    text = page_text(client.get("/workshop").text)
    assert "130 words · 2 min read · 2 attempts" in text


def test_f3_singular_attempt(client, session):
    add_story(session, "en", words_text(50, "word"), title="One try", attempts=1)
    text = page_text(client.get("/workshop").text)
    assert "50 words · 1 min read · 1 attempt" in text
    assert "1 attempts" not in text


def test_f3_zero_attempts_plural(client, session):
    add_story(session, "en", words_text(50, "word"), title="Fresh", attempts=0)
    text = page_text(client.get("/workshop").text)
    assert "50 words · 1 min read · 0 attempts" in text

"""Feature 1: cloze cards."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from tm_helpers import element_with_attr, page_text, review_front_html, strip_stress

T0 = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)


def add_story(session, source_lang="en", title="Story", text="Source text."):
    from app.models import Story

    story = Story(title=title, source_lang=source_lang, source_text=text)
    session.add(story)
    session.commit()
    return story


def add_attempt(session, story, text, corrected=None, minutes=0):
    from app.models import TranslationAttempt

    attempt = TranslationAttempt(story_id=story.id, text=text, corrected_text=corrected, created_at=T0 + timedelta(minutes=minutes))
    session.add(attempt)
    session.commit()
    return attempt


def texts(session):
    from app.services import cloze

    return [s.text for s in cloze.sentences(session)]


# --- sentences --------------------------------------------------------------------------------


def test_f1_sentences_split_and_keep_punctuation(session):
    story = add_story(session)
    add_attempt(session, story, "Я иду домой. Куда ты идёшь?  Это очень хорошо!\nОдин и тот же день… Конец")
    assert texts(session) == ["Я иду домой.", "Куда ты идёшь?", "Это очень хорошо!", "Один и тот же день…"]


def test_f1_sentences_final_without_punctuation_kept(session):
    story = add_story(session)
    add_attempt(session, story, "Я иду домой. Мы любим читать книги")
    assert texts(session) == ["Я иду домой.", "Мы любим читать книги"]


def test_f1_sentences_no_split_inside_number(session):
    story = add_story(session)
    add_attempt(session, story, "Билет стоит 3.5 тысячи рублей. Мы едем завтра утром.")
    assert texts(session) == ["Билет стоит 3.5 тысячи рублей.", "Мы едем завтра утром."]


def test_f1_sentences_skip_short(session):
    story = add_story(session)
    add_attempt(session, story, "Да. Я иду. Нет, не хочу! Мы идём домой.")
    assert texts(session) == ["Нет, не хочу!", "Мы идём домой."]


def test_f1_sentences_drop_duplicates_keep_first(session):
    story = add_story(session)
    add_attempt(session, story, "Мы идём домой. Я люблю чай. Мы идём домой.")
    assert texts(session) == ["Мы идём домой.", "Я люблю чай."]


def test_f1_sentences_duplicates_across_stories(session):
    from app.services import cloze

    one, two = add_story(session, title="One"), add_story(session, title="Two")
    add_attempt(session, one, "Мы идём домой.", minutes=0)
    add_attempt(session, two, "Мы идём домой.", minutes=10)
    result = cloze.sentences(session)
    assert [s.text for s in result] == ["Мы идём домой."]


def test_f1_prefers_corrected_text(session):
    story = add_story(session)
    add_attempt(session, story, "Я идти домой вчера.", corrected="Я шёл домой вчера.")
    assert texts(session) == ["Я шёл домой вчера."]


def test_f1_uses_raw_text_without_correction(session):
    story = add_story(session)
    add_attempt(session, story, "Я иду на вокзал.", corrected=None)
    assert texts(session) == ["Я иду на вокзал."]


def test_f1_latest_attempt_only(session):
    story = add_story(session)
    add_attempt(session, story, "Старая версия текста здесь.", minutes=0)
    add_attempt(session, story, "Новая версия текста здесь.", minutes=5)
    assert texts(session) == ["Новая версия текста здесь."]


def test_f1_ru_source_excluded(session):
    ru = add_story(session, source_lang="ru", title="Рассказ")
    add_attempt(session, ru, "This is an English sentence here.")
    en = add_story(session, source_lang="en", title="Tale")
    add_attempt(session, en, "Это русское предложение здесь.")
    assert texts(session) == ["Это русское предложение здесь."]


def test_f1_sentences_source_ids_and_order(session):
    from app.services import cloze

    one, two = add_story(session, title="One"), add_story(session, title="Two")
    a1 = add_attempt(session, one, "Первое предложение здесь. Второе предложение там.", minutes=0)
    a2 = add_attempt(session, two, "Третье предложение тут.", minutes=30)
    result = cloze.sentences(session)
    assert [s.text for s in result] == ["Третье предложение тут.", "Первое предложение здесь.", "Второе предложение там."]
    assert (result[0].story_id, result[0].attempt_id) == (two.id, a2.id)
    assert (result[1].story_id, result[1].attempt_id) == (one.id, a1.id)
    assert (result[2].story_id, result[2].attempt_id) == (one.id, a1.id)
    assert cloze.ClozeSource("x", 1, 2).attempt_id == 2


def test_f1_sentences_empty(session):
    from app.services import cloze

    assert cloze.sentences(session) == []


# --- make_cloze -------------------------------------------------------------------------------


def test_f1_make_cloze_basic():
    from app.services import cloze

    assert cloze.make_cloze("Я иду на вокзал.", "вокзал") == ("Я иду на ____.", "вокзал")


def test_f1_make_cloze_stress_in_sentence():
    from app.services import cloze

    sentence = "Я жду на вокза́ле, а он спит."
    blanked, answer = cloze.make_cloze(sentence, "вокзале")
    assert blanked == "Я жду на ____, а он спит."
    assert answer == "вокза́ле"


def test_f1_make_cloze_stress_in_word():
    from app.services import cloze

    blanked, answer = cloze.make_cloze("Я жду на вокзале.", "вокза́ле")
    assert blanked == "Я жду на ____."
    assert answer == "вокзале"


def test_f1_make_cloze_yo_and_ye():
    from app.services import cloze

    assert cloze.make_cloze("Он пришёл вчера.", "пришел") == ("Он ____ вчера.", "пришёл")
    assert cloze.make_cloze("Все пришли вечером.", "всё") == ("____ пришли вечером.", "Все")


def test_f1_make_cloze_case_kept_in_answer():
    from app.services import cloze

    assert cloze.make_cloze("Москва большая.", "москва") == ("____ большая.", "Москва")


def test_f1_make_cloze_whole_words_only():
    from app.services import cloze

    blanked, answer = cloze.make_cloze("Я открыл окно, он пришёл.", "он")
    assert blanked == "Я открыл окно, ____ пришёл."
    assert answer == "он"
    with pytest.raises(ValueError):
        cloze.make_cloze("Я открыл окно.", "он")


def test_f1_make_cloze_adjacent_punctuation_kept():
    from app.services import cloze

    assert cloze.make_cloze("Что «хлеб», сказал он?", "хлеб") == ("Что «____», сказал он?", "хлеб")
    assert cloze.make_cloze("Мы идём домой!", "домой") == ("Мы идём ____!", "домой")


def test_f1_make_cloze_first_occurrence_only():
    from app.services import cloze

    blanked, answer = cloze.make_cloze("Я люблю чай, и ты любишь чай.", "чай")
    assert blanked == "Я люблю ____, и ты любишь чай."
    assert answer == "чай"


def test_f1_make_cloze_missing_word_raises():
    from app.services import cloze

    with pytest.raises(ValueError):
        cloze.make_cloze("Я иду домой.", "школа")


# --- create_cloze_card ------------------------------------------------------------------------


def test_f1_kind_registered():
    from app.services import cards

    assert "cloze" in cards.KINDS
    assert cards.KIND_LABELS["cloze"] == "Cloze"


def test_f1_create_cloze_card_fields(session):
    from app.models import CardState, Direction, Module
    from app.services import cloze

    story = add_story(session)
    sentence = "Я жду на вокза́ле."
    card = cloze.create_cloze_card(session, sentence, "вокзале", "station", story_id=story.id)
    assert card.id is not None
    assert card.kind == "cloze"
    assert card.ru == "вокзале"
    assert card.ru_stressed == "вокза́ле"
    assert card.example_ru == sentence
    assert card.en == "station"
    assert card.source_module == Module.story
    assert card.source_ref_id == story.id
    states = session.exec(select(CardState).where(CardState.card_id == card.id)).all()
    assert [s.direction for s in states] == [Direction.recognition]


def test_f1_create_cloze_card_without_story(session):
    from app.models import Module
    from app.services import cloze

    card = cloze.create_cloze_card(session, "Мы идём домой.", "домой", "home")
    assert card.source_module == Module.story
    assert card.source_ref_id is None


def test_f1_create_requires_meaning_and_word(session):
    from app.models import Card
    from app.services import cloze

    with pytest.raises(ValueError):
        cloze.create_cloze_card(session, "Мы идём домой.", "домой", "")
    with pytest.raises(ValueError):
        cloze.create_cloze_card(session, "Мы идём домой.", "школа", "school")
    assert session.exec(select(Card)).all() == []


def test_f1_word_card_does_not_block(session):
    from app.services import cards, cloze

    cards.create_card(session, ru="домой", en="homeward")
    card = cloze.create_cloze_card(session, "Мы идём домой.", "домой", "home")
    assert card.kind == "cloze"


def test_f1_same_cloze_twice_rejected(session):
    from app.models import Card
    from app.services import cloze

    cloze.create_cloze_card(session, "Мы идём домой.", "домой", "home")
    with pytest.raises(ValueError):
        cloze.create_cloze_card(session, "Мы идём домой.", "домой", "home")
    assert len(session.exec(select(Card)).all()) == 1
    # another word of the same sentence, and the same word in another sentence, are fine
    cloze.create_cloze_card(session, "Мы идём домой.", "идём", "go")
    cloze.create_cloze_card(session, "Они бегут домой.", "домой", "home")
    assert len(session.exec(select(Card)).all()) == 3


def test_f1_never_unlocked_for_production(client, session):
    from app.models import CardState, Direction
    from app.services import cloze

    card = cloze.create_cloze_card(session, "Мы идём домой.", "домой", "home")
    cs = session.exec(select(CardState).where(CardState.card_id == card.id)).one()
    now = datetime.now(timezone.utc)
    cs.state = 2
    cs.stability = 40.0
    cs.difficulty = 5.0
    cs.step = None
    cs.reps = 5
    cs.last_review = now - timedelta(days=40)
    cs.due = now - timedelta(days=1)
    session.add(cs)
    session.commit()
    response = client.post(f"/review/{cs.id}", data={"rating": "3"}, follow_redirects=False)
    assert response.status_code == 303
    session.expire_all()
    directions = [s.direction for s in session.exec(select(CardState).where(CardState.card_id == card.id)).all()]
    assert directions == [Direction.recognition]


# --- review -----------------------------------------------------------------------------------


def review_html(client, session, sentence="Я жду на вокза́ле сегодня.", word="вокзале", en="station"):
    from app.services import cloze

    cloze.create_cloze_card(session, sentence, word, en)
    response = client.get("/review")
    assert response.status_code == 200
    return response.text


def test_f1_review_front_hides_answer(client, session):
    html = review_html(client, session)
    front = review_front_html(html)
    assert "вокзале" not in front
    assert "вокза́ле" not in front
    assert "вокзал" not in strip_stress(front).lower()
    cloze_el = element_with_attr(front, "data-cloze")
    assert cloze_el is not None
    assert "____" in cloze_el[0]
    assert "вокзал" not in strip_stress(cloze_el[0] + cloze_el[1]).lower()
    assert "Я жду на ____ сегодня." in " ".join(cloze_el[0].split())


def test_f1_review_front_shows_blanked_sentence(client, session):
    html = review_html(client, session, sentence="Мы идём домой сегодня.", word="домой", en="home")
    front = review_front_html(html)
    el = element_with_attr(front, "data-cloze")
    assert el is not None
    assert el[0] == "Мы идём ____ сегодня."
    assert "home" not in front


def test_f1_review_back_has_sentence_and_meaning(client, session):
    html = review_html(client, session, sentence="Мы идём домой сегодня.", word="домой", en="homeward bound")
    back = html[html.index("<button"):]
    text = page_text(back)
    assert "Мы идём домой сегодня." in text
    assert "homeward bound" in text


# --- pages ------------------------------------------------------------------------------------


def test_f1_page_lists_sentences(client, session):
    story = add_story(session)
    add_attempt(session, story, "Я иду на вокзал. Мы едем в Москву завтра.")
    response = client.get("/cloze")
    assert response.status_code == 200
    text = page_text(response.text)
    assert "Я иду на вокзал." in text
    assert "Мы едем в Москву завтра." in text
    for name in ("sentence", "story_id", "word", "en"):
        assert f'name="{name}"' in response.text


def test_f1_page_post_creates_card_and_redirects(client, session):
    from app.models import Card

    story = add_story(session)
    response = client.post(
        "/cloze",
        data={"sentence": "Я иду на вокзал.", "word": "вокзал", "en": "station", "story_id": str(story.id)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    session.expire_all()
    card = session.exec(select(Card).where(Card.kind == "cloze")).one()
    assert response.headers["location"].endswith(f"/cloze?made={card.id}")
    assert card.source_ref_id == story.id
    assert client.get(f"/cloze?made={card.id}").status_code == 200


def test_f1_page_post_without_story_id(client, session):
    from app.models import Card

    response = client.post("/cloze", data={"sentence": "Мы идём домой.", "word": "домой", "en": "home"}, follow_redirects=False)
    assert response.status_code == 303
    session.expire_all()
    assert session.exec(select(Card).where(Card.kind == "cloze")).one().source_ref_id is None


def test_f1_page_post_errors_return_400(client, session):
    from app.models import Card

    bad = {"sentence": "Мы идём домой.", "word": "школа", "en": "school"}
    response = client.post("/cloze", data=bad, follow_redirects=False)
    assert response.status_code == 400
    assert response.text.strip()
    assert client.post("/cloze", data={"sentence": "Мы идём домой.", "word": "домой", "en": ""}).status_code == 400
    ok = {"sentence": "Мы идём домой.", "word": "домой", "en": "home"}
    assert client.post("/cloze", data=ok, follow_redirects=False).status_code == 303
    assert client.post("/cloze", data=ok, follow_redirects=False).status_code == 400
    session.expire_all()
    assert len(session.exec(select(Card)).all()) == 1


def test_f1_workshop_links_to_cloze(client, session):
    add_story(session)
    assert 'href="/cloze"' in client.get("/workshop").text

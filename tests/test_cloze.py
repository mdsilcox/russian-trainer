import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

import pytest
from fsrs import State
from sqlmodel import select

from app.models import Card, CardState, Module, Story, TranslationAttempt
from app.services import cards as card_service
from app.services import cloze, srs

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def add_story(session, title="Поезд", lang="en"):
    story = Story(title=title, source_lang=lang, source_text="text")
    session.add(story)
    session.commit()
    return story


def add_attempt(session, story, text, corrected=None, minutes=0):
    attempt = TranslationAttempt(
        story_id=story.id, text=text, corrected_text=corrected, created_at=T0 + timedelta(minutes=minutes)
    )
    session.add(attempt)
    session.commit()
    return attempt


def texts(session):
    return [s.text for s in cloze.sentences(session)]


# ---- sentence splitting ----


def test_split_on_all_sentence_marks(session):
    story = add_story(session)
    add_attempt(session, story, "Я живу в Москве. Где ты живёшь? Мы идём домой! Я думаю о тебе… Потом мы спим")
    assert texts(session) == [
        "Я живу в Москве.",
        "Где ты живёшь?",
        "Мы идём домой!",
        "Я думаю о тебе…",
        "Потом мы спим",
    ]


def test_question_exclamation_pair_ends_at_the_last_mark(session):
    story = add_story(session)
    add_attempt(session, story, "Что ты сказал?! Я не знаю что.")
    assert texts(session) == ["Что ты сказал?!", "Я не знаю что."]


def test_ellipsis_dots_and_dots_inside_words(session):
    story = add_story(session)
    add_attempt(session, story, "Я не знаю... Но это так. Он купил 3.5 килограмма яблок.")
    assert texts(session) == ["Я не знаю...", "Но это так.", "Он купил 3.5 килограмма яблок."]


def test_newlines_count_as_whitespace(session):
    story = add_story(session)
    add_attempt(session, story, "Я иду домой.\nОна ждёт меня там.\n\nМы пьём чай\n")
    assert texts(session) == ["Я иду домой.", "Она ждёт меня там.", "Мы пьём чай"]


def test_short_sentences_skipped_and_dash_is_not_a_word(session):
    story = add_story(session)
    add_attempt(session, story, "Да. Я иду. Я иду домой. Он - да. Он - нет, а я - да.")
    assert texts(session) == ["Я иду домой.", "Он - нет, а я - да."]


def test_duplicates_dropped_across_stories_keeping_first(session):
    first, second = add_story(session, "Первая"), add_story(session, "Вторая")
    a1 = add_attempt(session, first, "Мы идём домой. Мы идём домой.", minutes=5)
    add_attempt(session, second, "Мы идём домой. Она ждёт меня.", minutes=1)
    result = cloze.sentences(session)
    assert [(s.text, s.story_id) for s in result] == [
        ("Мы идём домой.", first.id),
        ("Она ждёт меня.", second.id),
    ]
    assert result[0].attempt_id == a1.id


def test_newest_attempt_first_and_text_order_within(session):
    old, new = add_story(session, "Старая"), add_story(session, "Новая")
    add_attempt(session, new, "Он любит чай. Она любит кофе.", minutes=10)
    add_attempt(session, old, "Мы читаем книгу.", minutes=1)
    assert texts(session) == ["Он любит чай.", "Она любит кофе.", "Мы читаем книгу."]


def test_tie_on_created_at_prefers_higher_id(session):
    first, second = add_story(session, "A"), add_story(session, "B")
    add_attempt(session, first, "Это первая история.", minutes=3)
    add_attempt(session, second, "Это вторая история.", minutes=3)
    assert texts(session) == ["Это вторая история.", "Это первая история."]


def test_corrected_text_preferred(session):
    story = add_story(session)
    add_attempt(session, story, "Я живу в Москва.", corrected="Я живу в Москве.")
    assert texts(session) == ["Я живу в Москве."]


def test_empty_corrected_text_falls_back_to_text(session):
    story = add_story(session)
    add_attempt(session, story, "Я живу в Москве.", corrected="")
    assert texts(session) == ["Я живу в Москве."]


def test_only_latest_attempt_per_story(session):
    story = add_story(session)
    add_attempt(session, story, "Старая попытка была плохой.", minutes=1)
    latest = add_attempt(session, story, "Новая попытка была лучше.", minutes=2)
    result = cloze.sentences(session)
    assert [(s.text, s.attempt_id) for s in result] == [("Новая попытка была лучше.", latest.id)]


def test_russian_source_stories_excluded(session):
    add_attempt(session, add_story(session, "Русская", lang="ru"), "Это русская история.")
    assert cloze.sentences(session) == []


# ---- make_cloze ----


@pytest.mark.parametrize(
    "sentence, word, expected",
    [
        ("Я живу в Москве́.", "москве", ("Я живу в ____.", "Москве́")),
        ("Ёлка стоит у ёлки.", "елки", ("Ёлка стоит у ____.", "ёлки")),
        ("Он пошёл домой, а я нет.", "Домой", ("Он пошёл ____, а я нет.", "домой")),
        ("Мы мыли пол.", "мы", ("____ мыли пол.", "Мы")),
        ("Где вокза́л?", "вокза'л", ("Где ____?", "вокза́л")),
        ("Где вокзал?", "вокза́л", ("Где ____?", "вокзал")),
        ("Я пошёл, потому что устал.", "потому что", ("Я пошёл, ____ устал.", "потому что")),
        ("Я пошёл, потому\nчто устал.", "ПОТОМУ ЧТО", ("Я пошёл, ____ устал.", "потому\nчто")),
        ("Он сказал: «Привет».", "привет", ("Он сказал: «____».", "Привет")),
    ],
)
def test_make_cloze(sentence, word, expected):
    assert cloze.make_cloze(sentence, word) == expected


def test_make_cloze_blanks_only_first_occurrence():
    assert cloze.make_cloze("Мы мыли пол, и мы устали.", "мы")[0] == "____ мыли пол, и мы устали."


def test_stress_mark_after_last_letter_belongs_to_answer():
    blanked, answer = cloze.make_cloze("Это моё́ дело.", "моё")
    assert answer == "моё́" and blanked == "Это ____ дело."


def test_whole_words_only():
    with pytest.raises(ValueError):
        cloze.make_cloze("Я иду домой.", "до")
    with pytest.raises(ValueError):
        cloze.make_cloze("Я иду домой.", "мой")
    # a partial match is skipped and a later whole word is found
    assert cloze.make_cloze("Домой я иду, а он идёт до дома.", "до")[0] == "Домой я иду, а он идёт ____ дома."


def test_hyphenated_words_are_one_word():
    sentence = "Из-за дождя мы остались дома из принципа."
    assert cloze.make_cloze(sentence, "из") == ("Из-за дождя мы остались дома ____ принципа.", "из")
    assert cloze.make_cloze(sentence, "из-за") == ("____ дождя мы остались дома из принципа.", "Из-за")
    with pytest.raises(ValueError):
        cloze.make_cloze("Кто-то пришёл домой.", "кто")
    with pytest.raises(ValueError):
        cloze.make_cloze("Кто-то пришёл домой.", "то")


def test_spaced_dash_does_not_join():
    assert cloze.make_cloze("Москва - большой город.", "москва")[0] == "____ - большой город."
    assert cloze.make_cloze("Москва - большой город.", "большой")[0] == "Москва - ____ город."


def test_not_found_and_blank_raise_value_error():
    with pytest.raises(ValueError, match="not in this sentence"):
        cloze.make_cloze("Я живу в Москве.", "Питер")
    for blank in ("", "   ", None):
        with pytest.raises(ValueError):
            cloze.make_cloze("Я живу в Москве.", blank)


# ---- create_cloze_card ----


def test_create_cloze_card_fields(session):
    story = add_story(session)
    card = cloze.create_cloze_card(session, "Я живу в Москве́.", "москве", " in Moscow ", story_id=story.id)
    assert card.kind == "cloze"
    assert card.ru == "Москве" and card.ru_stressed == "Москве́"
    assert card.example_ru == "Я живу в Москве́."
    assert card.en == "in Moscow"
    assert card.source_module == Module.story and card.source_ref_id == story.id
    state = session.exec(select(CardState).where(CardState.card_id == card.id)).one()
    assert state.direction == srs.Direction.recognition


def test_create_cloze_card_without_story(session):
    card = cloze.create_cloze_card(session, "Мы идём домой.", "домой", "home")
    assert card.source_ref_id is None


def test_duplicate_cloze_card_refused_but_other_word_or_sentence_allowed(session):
    cloze.create_cloze_card(session, "Мы идём домой после работы.", "домой", "home")
    with pytest.raises(ValueError, match="already"):
        cloze.create_cloze_card(session, "Мы идём домой после работы.", "Домой", "home")
    with pytest.raises(ValueError):
        cloze.create_cloze_card(session, "Мы идём домо́й после работы.", "ДОМОЙ", "x")
    cloze.create_cloze_card(session, "Мы идём домой после работы.", "работы", "work")
    cloze.create_cloze_card(session, "Он тоже идёт домой.", "домой", "home")
    assert len(session.exec(select(Card).where(Card.kind == "cloze")).all()) == 3


def test_regular_card_does_not_block_cloze(session):
    card_service.create_card(session, ru="домой", en="home (direction)")
    card = cloze.create_cloze_card(session, "Мы идём домой.", "домой", "home")
    assert card.kind == "cloze"


def test_create_cloze_card_validates_before_creating(session):
    for args in [("Мы идём домой.", "домой", "  "), ("Мы идём домой.", "школа", "school"), ("Мы идём домой.", "", "home")]:
        with pytest.raises(ValueError):
            cloze.create_cloze_card(session, *args)
    assert session.exec(select(Card)).all() == []


# ---- scheduling ----


def test_cloze_card_never_unlocks_production(session):
    card = cloze.create_cloze_card(session, "Мы идём домой.", "домой", "home")
    cs = session.exec(select(CardState).where(CardState.card_id == card.id)).one()
    cs.state, cs.stability = int(State.Review), 10.0
    assert srs.maybe_unlock_production(session, cs) is None
    assert len(session.exec(select(CardState).where(CardState.card_id == card.id)).all()) == 1


def test_word_card_still_unlocks_production(session):
    card = card_service.create_card(session, ru="ехать", en="to go")
    cs = session.exec(select(CardState).where(CardState.card_id == card.id)).one()
    cs.state, cs.stability = int(State.Review), 10.0
    assert srs.maybe_unlock_production(session, cs) is not None


# ---- routes ----


def test_cloze_page_empty_state(client):
    page = client.get("/cloze").text
    assert "Cloze cards · Russian Trainer" in page
    assert 'href="/workshop/new"' in page


def test_cloze_page_lists_sentences(client, session):
    story = add_story(session, "Мой день")
    add_attempt(session, story, "Я живу в Москве. Это очень красивый город.")
    page = client.get("/cloze").text
    assert "Мой день" in page
    assert page.count('name="word"') == 2 and page.count('name="en"') == 2
    assert 'data-word="Москве"' in page
    assert f'name="story_id" value="{story.id}"' in page


def test_post_success_redirects_and_creates_card(client, session):
    story = add_story(session)
    response = client.post(
        "/cloze",
        data={"sentence": "Я живу в Москве.", "word": "москве", "en": "Moscow", "story_id": str(story.id)},
        follow_redirects=False,
    )
    card = session.exec(select(Card)).one()
    assert response.status_code == 303
    assert response.headers["location"] == f"/cloze?made={card.id}"
    assert card.kind == "cloze" and card.source_ref_id == story.id
    page = client.get(response.headers["location"]).text
    assert "Я живу в ____." in page and f"/cards/{card.id}" in page


def test_post_with_empty_story_id(client, session):
    response = client.post(
        "/cloze", data={"sentence": "Мы идём домой.", "word": "домой", "en": "home", "story_id": ""},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert session.exec(select(Card)).one().source_ref_id is None


def test_post_error_returns_400_with_message_and_typed_values(client, session):
    story = add_story(session)
    add_attempt(session, story, "Я живу в Москве. Это очень красивый город.")
    response = client.post(
        "/cloze",
        data={"sentence": "Я живу в Москве.", "word": "Питер", "en": "Petersburg", "story_id": str(story.id)},
    )
    assert response.status_code == 400
    assert "not in this sentence" in response.text
    assert 'value="Питер"' in response.text and 'value="Petersburg"' in response.text
    assert session.exec(select(Card)).all() == []


def test_post_error_for_unlisted_sentence_shows_banner(client):
    response = client.post("/cloze", data={"sentence": "Мы идём домой.", "word": "x", "en": "y"})
    assert response.status_code == 400 and "not in this sentence" in response.text


def test_post_missing_fields_is_400_not_422(client):
    assert client.post("/cloze", data={}).status_code == 400


def test_sentence_with_card_is_marked(client, session):
    story = add_story(session)
    add_attempt(session, story, "Я живу в Москве.")
    assert "has a card" not in client.get("/cloze").text
    cloze.create_cloze_card(session, "Я живу в Москве.", "Москве", "Moscow", story.id)
    assert "has a card" in client.get("/cloze").text


# ---- review screen ----


class Parts(HTMLParser):
    """Collects the markup inside the first element with a given class (front/back) and data-cloze text."""

    def __init__(self):
        super().__init__()
        self.depth = {}
        self.chunks = {"front": [], "back": []}
        self.cloze_text = None
        self._in_cloze = False
        self._stack = []

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        classes = (attrs_d.get("class") or "").split()
        if tag in ("br", "img", "input", "link", "meta"):
            return
        self._stack.append((tag, [c for c in ("front", "back") if c in classes]))
        for _, marks in self._stack:
            for mark in marks:
                self.chunks[mark].append(self.get_starttag_text())
        if "data-cloze" in attrs_d:
            self._in_cloze, self.cloze_text = True, ""

    def handle_endtag(self, tag):
        if tag == "p" and self._in_cloze:
            self._in_cloze = False
        if self._stack and self._stack[-1][0] == tag:
            self._stack.pop()

    def handle_data(self, data):
        if self._in_cloze:
            self.cloze_text += data
        for _, marks in self._stack:
            for mark in marks:
                self.chunks[mark].append(data)


def front_of(page):
    parts = Parts()
    parts.feed(page)
    return "".join(parts.chunks["front"]), parts


def test_review_front_hides_the_answer(client, session):
    cloze.create_cloze_card(session, "Я живу в Москве́ уже давно.", "москве", "in Moscow")
    page = client.get("/review").text
    front, parts = front_of(page)
    assert parts.cloze_text == "Я живу в ____ уже давно."
    assert "Cloze" in front
    assert "Москв" not in front and "москв" not in front
    assert "in Moscow" not in front
    # nothing outside .back may carry the answer (page title, scripts, attributes)
    outside_back = re.sub(r'<div class="back[^"]*" hidden>.*?</div>\s*</article>', "", page, flags=re.S)
    outside_back = re.sub(r'<div class="back rv-rate" hidden>.*?</form>\s*</div>', "", outside_back, flags=re.S)
    assert "Москв" not in outside_back and "москв" not in outside_back
    assert "in Moscow" not in outside_back


def test_review_back_shows_sentence_highlight_and_meaning(client, session):
    cloze.create_cloze_card(session, "Я живу в Москве́ уже давно.", "москве", "in Moscow")
    page = client.get("/review").text
    assert "<mark>Москве́</mark>" in page
    assert 'data-speak="Я живу в Москве́ уже давно."' in page
    assert "in Moscow" in page
    assert "rv-example" not in page  # the example blockquote is not repeated
    assert "English → Russian" not in page


def test_review_non_cloze_card_unchanged(client, session):
    card_service.create_card(session, ru="вокзал", ru_stressed="вокза'л", en="railway station", example_ru="Где вокза'л?")
    page = client.get("/review").text
    assert "data-cloze" not in page and "rv-example" in page and "cloze.css" not in page
    assert 'data-speak="вокза́л"' in page


def test_review_cloze_falls_back_to_blank_when_word_missing(client, session):
    card = cloze.create_cloze_card(session, "Мы идём домой.", "домой", "home")
    card.example_ru = "Совсем другое предложение."
    session.add(card)
    session.commit()
    _, parts = front_of(client.get("/review").text)
    assert parts.cloze_text == "____"

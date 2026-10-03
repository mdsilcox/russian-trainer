from datetime import timedelta

from fsrs import State
from sqlmodel import select

from app.models import CardState, Direction
from app.services import cards as card_service

from tests.test_review import NOW


def test_recognition_card_has_speak_controls(client, session):
    card_service.create_card(session, ru="вокзал", ru_stressed="вокза'л", en="railway station",
                             example_ru="Где вокза'л?")
    page = client.get("/review").text
    assert '/static/speak.js' in page and '/static/speak.css' in page
    # Stress marks stay in the attribute; speak.js strips them before speaking.
    assert 'data-speak="вокза\u0301л"' in page
    assert 'data-speak="Где вокза\u0301л?"' in page
    assert 'data-speak-hotkey="s"' in page
    assert "data-speak-speed" in page and "data-listen-first-toggle" in page


def test_listen_first_markup_on_recognition_word_only(client, session):
    card_service.create_card(session, ru="поезд", en="train")
    page = client.get("/review").text
    word = page.split('class="rv-word fit"')[1].split(">")[0]
    assert "data-listen-first" in word and 'data-speak="поезд"' in word


def test_production_card_speaks_the_answer_not_the_prompt(client, session):
    card = card_service.create_card(session, ru="ехать", en="to go (by vehicle)")
    recognition = session.exec(select(CardState).where(CardState.card_id == card.id)).one()
    recognition.due, recognition.state = NOW + timedelta(days=30), int(State.Review)
    session.add(CardState(card_id=card.id, direction=Direction.production))
    session.commit()
    page = client.get("/review").text
    assert "English → Russian" in page
    answer = page.split('class="rv-trans is-ru fit"')[1].split(">")[0]
    assert 'data-speak="ехать"' in answer and 'data-speak-hotkey="s"' in answer
    assert "data-listen-first" not in page.split("<article")[1].split("</article>")[0]


def test_empty_queue_has_no_speak_controls(client):
    page = client.get("/review").text
    assert "data-speak=" not in page

from datetime import datetime, timedelta, timezone

from fsrs import State
from sqlmodel import select

from app.models import CardState, Direction, Module, ReviewLog, Story
from app.routes.review import source_label
from app.services import cards as card_service
from app.services import srs

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def test_empty_queue_shows_done(client):
    assert "All done" in client.get("/review").text


def test_review_page_shows_new_card_with_stress_and_intervals(client, session):
    card_service.create_card(session, ru="вокзал", ru_stressed="вокза'л", en="railway station",
                             example_ru="Где вокза'л?")
    page = client.get("/review").text
    assert "вокза́л" in page
    assert "railway station" in page  # on the hidden back side
    assert 'data-hotkey="Space"' in page
    for label in ("Again", "Hard", "Good", "Easy"):
        assert label in page


def test_rating_records_review_and_advances(client, session):
    card = card_service.create_card(session, ru="поезд", en="train")
    cs = session.exec(select(CardState).where(CardState.card_id == card.id)).one()
    response = client.post(f"/review/{cs.id}", data={"rating": 3, "duration_ms": 4100}, follow_redirects=False)
    assert response.status_code == 303
    log = session.exec(select(ReviewLog)).one()
    assert log.rating == 3 and log.duration_ms == 4100
    assert client.post(f"/review/{cs.id}", data={"rating": 7}).status_code == 422


def test_production_card_unlocks_once_recognition_is_stable(session):
    card = card_service.create_card(session, ru="ехать", en="to go (by vehicle)")
    cs = session.exec(select(CardState).where(CardState.card_id == card.id)).one()
    cs.state, cs.stability = int(State.Review), 2.0
    assert srs.maybe_unlock_production(session, cs) is None
    cs.stability = 6.0
    production = srs.maybe_unlock_production(session, cs)
    assert production.direction == Direction.production and production.state == srs.NEW
    assert srs.maybe_unlock_production(session, cs) is None  # only once


def test_production_card_review_page(client, session):
    card = card_service.create_card(session, ru="ехать", en="to go (by vehicle)")
    session.exec(select(CardState).where(CardState.card_id == card.id)).one().due = NOW + timedelta(days=30)
    session.exec(select(CardState).where(CardState.card_id == card.id)).one().state = int(State.Review)
    session.add(CardState(card_id=card.id, direction=Direction.production))
    session.commit()
    page = client.get("/review").text
    assert "English → Russian" in page and 'id="typed"' in page


def test_source_label(session):
    story = Story(title="Поезд", source_lang="ru", source_text="...")
    session.add(story)
    session.commit()
    card = card_service.create_card(session, ru="купе", en="compartment", source_module=Module.story,
                                    source_ref_id=story.id)
    assert source_label(session, card) == "from your story ‘Поезд’"


def test_format_interval():
    assert srs.format_interval(timedelta(minutes=1)) == "1m"
    assert srs.format_interval(timedelta(minutes=10)) == "10m"
    assert srs.format_interval(timedelta(hours=5)) == "5h"
    assert srs.format_interval(timedelta(days=3)) == "3d"
    assert srs.format_interval(timedelta(days=90)) == "3mo"
    assert srs.format_interval(timedelta(days=500)) == "1.4y"


def test_waiting_message_when_learning_card_due_soon(client, session):
    card = card_service.create_card(session, ru="метро", en="metro")
    cs = session.exec(select(CardState).where(CardState.card_id == card.id)).one()
    client.post(f"/review/{cs.id}", data={"rating": 3})
    page = client.get("/review").text
    assert "Next card in 10 min" in page


def test_review_page_has_vine_container_and_script(client, session):
    card_service.create_card(session, ru="дом", en="house")
    page = client.get("/review").text
    assert "data-rv-vine" in page and 'class="rv-vine-nodes"' in page
    assert "/static/review.js" in page


def test_done_page_has_hidden_branch_summary(client):
    page = client.get("/review").text
    assert "data-rv-branch" in page and "Your branch today" in page


def test_review_js_records_ratings_in_session_storage(client):
    js = client.get("/static/review.js").text
    assert "rv-vine" in js and "sessionStorage" in js

from fsrs import Rating
from sqlmodel import select

from app.models import Card, CardState, Category, Mistake, Module
from app.routes import workshop as workshop_routes
from app.services import cards as card_service
from app.services import feedback as fb
from app.services import mistakes, srs, workshop
from app.services.claude import ClaudeClient
from tests.test_claude import FakeAnthropic, fake_response
from tests.test_feedback import RUSSIAN


def issue(wrong, right, category, severity="error", sub="", explanation="Rule."):
    return fb.Issue(wrong=wrong, right=right, category=category, subcategory=sub, explanation=explanation, severity=severity)


def make_feedback(**overrides) -> fb.Feedback:
    data = dict(
        summary="ok",
        corrected_text="Я поехал на ночном поезде в Казань. Купе было маленькое, но тёплое. Мы заказали чай.",
        issues=[
            issue("ночной поезд", "ночном поезде", "case", sub="prepositional after на"),
            issue("маленький", "маленькое", "agreement"),
            issue("взяли чай", "заказали чай", "word_choice", explanation="In a café you заказывать."),
            issue("тёплое", "тёплое", "idiom", severity="style"),
        ],
        rephrasings=[],
        vocab=[fb.VocabItem(ru="проводни́к", en="train attendant", example_ru="Проводни́к принёс чай.",
                            example_en="The attendant brought tea.", why="Trains")],
        translation_notes=[],
    )
    return fb.Feedback(**(data | overrides))


def setup_story(session):
    story = workshop.create_story(session, "Train", "en", "I took the night train.", RUSSIAN + " Мы взяли чай.")
    return story, workshop.attempts_for(session, story.id)[0]


def test_sentence_containing():
    text = "Я поехал на ночном поезде. Купе было маленькое! Мы заказали чай."
    assert mistakes.sentence_containing(text, "маленькое") == "Купе было маленькое!"
    assert mistakes.sentence_containing(text, "нет") is None


def test_route_logs_errors_and_unnatural_only(session):
    story, attempt = setup_story(session)
    result = mistakes.route_story_feedback(session, story, attempt, make_feedback())
    assert [m.category for m in result.mistakes] == [Category.case, Category.agreement, Category.word_choice]
    assert {m.category for m in result.drill_mistakes} == {Category.case, Category.agreement}
    assert all(m.ref_id == attempt.id and m.module == Module.story for m in result.mistakes)


def test_vocab_mistake_becomes_card_with_own_sentence(session):
    story, attempt = setup_story(session)
    result = mistakes.route_story_feedback(session, story, attempt, make_feedback())
    word_card = next(c for c in result.new_cards if c.ru == "заказали чай")
    assert word_card.example_ru == "Мы заказали чай."
    assert word_card.en.startswith("Not “взяли чай”")
    assert word_card.source_module == Module.story and word_card.source_ref_id == attempt.id
    assert "mistake" in word_card.tags
    mistake = session.exec(select(Mistake).where(Mistake.category == Category.word_choice)).one()
    assert mistake.card_id == word_card.id
    # The card is schedulable straight away.
    assert session.exec(select(CardState).where(CardState.card_id == word_card.id)).one().state == srs.NEW


def test_feedback_vocab_becomes_card(session):
    story, attempt = setup_story(session)
    result = mistakes.route_story_feedback(session, story, attempt, make_feedback())
    vocab_card = next(c for c in result.new_cards if c.ru == "проводник")
    assert vocab_card.ru_stressed == "проводни́к" and vocab_card.en == "train attendant"


def test_existing_card_is_reused_not_duplicated(session):
    existing = card_service.create_card(session, ru="заказали чай", en="ordered tea")
    story, attempt = setup_story(session)
    result = mistakes.route_story_feedback(session, story, attempt, make_feedback())
    assert existing.id in [c.id for c in result.linked_cards]
    assert len(session.exec(select(Card).where(Card.ru == "заказали чай")).all()) == 1


def test_rerun_replaces_mistakes_without_duplicating_cards(session):
    story, attempt = setup_story(session)
    mistakes.route_story_feedback(session, story, attempt, make_feedback())
    cards_before = len(session.exec(select(Card)).all())
    mistakes.route_story_feedback(session, story, attempt, make_feedback())
    assert len(session.exec(select(Mistake)).all()) == 3
    assert len(session.exec(select(Card)).all()) == cards_before


def test_auto_card_cap(session):
    story, attempt = setup_story(session)
    many = [issue(f"слово{i}", f"другое{i}", "word_choice") for i in range(12)]
    result = mistakes.route_story_feedback(session, story, attempt, make_feedback(issues=many, vocab=[]))
    assert len(result.new_cards) == mistakes.MAX_AUTO_CARDS
    assert len(result.mistakes) == 12


def test_discard_auto_card_only_if_unreviewed(session):
    story, attempt = setup_story(session)
    result = mistakes.route_story_feedback(session, story, attempt, make_feedback())
    first, second = result.new_cards[0], result.new_cards[1]
    first_id = first.id
    cs = session.exec(select(CardState).where(CardState.card_id == second.id)).one()
    srs.review(session, cs, Rating.Good)

    assert mistakes.discard_auto_card(session, first_id)
    assert not mistakes.discard_auto_card(session, second.id)  # already studied
    manual = card_service.create_card(session, ru="метро", en="metro")
    assert not mistakes.discard_auto_card(session, manual.id)  # not an auto-card
    session.expunge_all()
    assert session.get(Card, first_id) is None


def test_feedback_route_routes_mistakes_and_panel_shows_cards(client, session, monkeypatch):
    story, attempt = setup_story(session)
    fake = FakeAnthropic(fake_response(parsed=make_feedback()))
    monkeypatch.setattr(workshop_routes, "ClaudeClient", lambda s: ClaudeClient(s, client=fake))

    panel = client.post(f"/workshop/{story.id}/attempts/{attempt.id}/feedback", headers={"HX-Request": "true"}).text
    assert "Added 2 cards to your deck" in panel
    assert "2 grammar mistakes saved for drills: Agreement, Case endings." in panel

    card = session.exec(select(Card).where(Card.ru == "проводник")).one()
    removed = client.post(f"/workshop/cards/{card.id}/discard", headers={"HX-Request": "true"})
    assert "Removed" in removed.text
    assert "Added 1 card to your deck" in client.get(f"/workshop/{story.id}").text
    assert client.post(f"/workshop/cards/{card.id}/discard").status_code == 409

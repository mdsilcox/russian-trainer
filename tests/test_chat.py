import pytest
from sqlmodel import select

from app.models import Card, Conversation, Message, Module
from app.routes import scenarios as routes
from app.services import cards as card_service
from app.services import roleplay, scenarios
from app.services.claude import ClaudeError
from app.services.feedback import Issue
from app.services.roleplay import Debrief, DebriefPhrase, Hint, TurnReview


class FakeClient:
    """Stands in for ClaudeClient; shared by every request in a test."""

    def __init__(self):
        self.chunks = ["Куда́ ", "е́дем?"]
        self.review = TurnReview(
            issues=[Issue(wrong="в Большой театре", right="в Большо́й теа́тр", category="case",
                          subcategory="accusative for direction", explanation="Use the accusative after в for direction.",
                          severity="error")],
            better="Мне нужно в Большо́й теа́тр.", goals_met=[1])
        self.hint = Hint(ru="Ско́лько сто́ит?", en="How much is it?", tip="сто́ит is 'costs'")
        self.debrief = Debrief(
            summary="You handled the address well.",
            phrases=[
                DebriefPhrase(ru="Сда́чи не на́до", en="Keep the change", example_ru="Сда́чи не на́до, спаси́бо.",
                              example_en="Keep the change, thanks.", why="Common when paying a driver."),
                DebriefPhrase(ru="Прие́хали", en="We have arrived", example_ru="Мы прие́хали.", example_en="We have arrived.",
                              why="Said at the destination."),
            ],
            next_level_tip="Try level 3 and answer without the hint.")
        self.structured_calls = 0
        self.error = None

    def stream_text(self, task, system, messages, max_tokens=4000):
        if self.error:
            raise self.error
        yield from self.chunks

    def ask_structured(self, task, system, prompt, model, max_tokens=16000):
        if self.error:
            raise self.error
        self.structured_calls += 1
        return {TurnReview: self.review, Hint: self.hint, Debrief: self.debrief}[model]


@pytest.fixture
def fake(monkeypatch):
    f = FakeClient()
    monkeypatch.setattr(routes, "ClaudeClient", lambda session: f)
    return f


@pytest.fixture
def conv(client, session):
    scenarios.seed(session)
    r = client.post("/scenarios/taxi/start", data={"level": 2}, follow_redirects=False)
    return int(r.headers["location"].rsplit("/", 1)[1])


def turn(client, cid, text="Я хочу в Большой театре."):
    return client.post(f"/scenarios/c/{cid}/turn", data={"text": text})


def test_start_creates_conversation_at_level_with_opening_line(client, session, conv):
    c = session.get(Conversation, conv)
    assert c.level == 2
    [opening] = session.exec(select(Message).where(Message.conversation_id == conv)).all()
    assert opening.role == "partner"
    page = client.get(f"/scenarios/c/{conv}")
    assert page.status_code == 200
    assert "Taxi or Yandex Go" in page.text and "taxi driver" in page.text and "Everyday" in page.text
    assert "data-speak" in page.text and 'id="composer"' in page.text and "Tell the driver the address" in page.text
    assert "Ско́лько" in page.text or "Куда́" in page.text
    assert client.get("/scenarios/c/9999").status_code == 404


def test_turn_saves_line_and_rejects_empty(client, session, conv):
    assert turn(client, conv, "  ").status_code == 422
    r = turn(client, conv)
    assert r.status_code == 200
    assert session.get(Message, r.json()["id"]).content == "Я хочу в Большой театре."


def test_reply_streams_chunks_and_saves_reply(client, session, conv, fake):
    turn(client, conv)
    r = client.post(f"/scenarios/c/{conv}/reply")
    assert r.status_code == 200 and r.text == "Куда́ е́дем?"
    session.expire_all()
    assert roleplay.messages(session, session.get(Conversation, conv))[-1].content == "Куда́ е́дем?"


def test_reply_needs_a_learner_turn_and_reports_errors_in_stream(client, session, conv, fake):
    assert client.post(f"/scenarios/c/{conv}/reply").status_code == 409
    turn(client, conv)
    fake.error = ClaudeError("Claude is busy")
    r = client.post(f"/scenarios/c/{conv}/reply")
    assert r.status_code == 200 and r.text == routes.STREAM_ERROR + "Claude is busy"


def test_review_returns_corrections_goal_ticks_and_is_stored(client, session, conv, fake):
    mid = turn(client, conv).json()["id"]
    r = client.post(f"/scenarios/c/{conv}/review/{mid}")
    data = r.json()
    assert r.status_code == 200 and data["goals_met"] == [1]
    assert "ch-wrong" in data["html"] and "в Большой театре" in data["html"] and "More natural" in data["html"]
    # computed once: a second call must not ask Claude again
    fake.error = ClaudeError("should not be called")
    assert client.post(f"/scenarios/c/{conv}/review/{mid}").json()["goals_met"] == [1]
    page = client.get(f"/scenarios/c/{conv}").text
    assert "ch-wrong" in page and "Use the accusative" in page and 'class="done"' in page


def test_review_error_and_unknown_line(client, session, conv, fake):
    mid = turn(client, conv).json()["id"]
    fake.error = ClaudeError("offline")
    r = client.post(f"/scenarios/c/{conv}/review/{mid}")
    assert r.status_code == 502 and r.json() == {"error": "offline"}
    assert client.post(f"/scenarios/c/{conv}/review/99999").status_code == 404
    opening = roleplay.messages(session, session.get(Conversation, conv))[0]
    assert client.post(f"/scenarios/c/{conv}/review/{opening.id}").status_code == 404


def test_hint(client, conv, fake):
    r = client.post(f"/scenarios/c/{conv}/hint")
    assert r.json() == {"ru": "Ско́лько сто́ит?", "en": "How much is it?", "tip": "сто́ит is 'costs'"}
    fake.error = ClaudeError("offline")
    assert client.post(f"/scenarios/c/{conv}/hint").status_code == 502


def test_end_then_no_more_turns(client, session, conv, fake):
    r = client.post(f"/scenarios/c/{conv}/end", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/scenarios/c/{conv}"
    assert session.get(Conversation, conv).ended_at is not None
    page = client.get(f"/scenarios/c/{conv}").text
    assert "Conversation ended" in page and 'id="composer"' not in page and "/scenarios/taxi" in page
    assert turn(client, conv).status_code == 409
    assert client.post(f"/scenarios/c/{conv}/reply").status_code == 409
    assert client.post(f"/scenarios/c/{conv}/hint").status_code == 409


def test_detail_links_to_unfinished_conversation(client, session, conv):
    assert f"/scenarios/c/{conv}" in client.get("/scenarios/taxi").text
    client.post(f"/scenarios/c/{conv}/end")
    assert "unfinished conversation" not in client.get("/scenarios/taxi").text


def ended_with_review(client, cid):
    mid = turn(client, cid).json()["id"]
    client.post(f"/scenarios/c/{cid}/review/{mid}")
    client.post(f"/scenarios/c/{cid}/end")


def test_ended_page_loads_debrief_via_a_separate_request(client, conv, fake):
    ended_with_review(client, conv)
    page = client.get(f"/scenarios/c/{conv}").text
    assert f'hx-post="/scenarios/c/{conv}/debrief"' in page and 'hx-trigger="load"' in page
    assert fake.structured_calls == 1  # only the turn review so far, the page itself never calls Claude


def test_debrief_panel_content(client, conv, fake):
    ended_with_review(client, conv)
    html = client.post(f"/scenarios/c/{conv}/debrief").text
    assert "You handled the address well." in html
    assert html.index("Tell the driver the address") < html.index("Ask how long the trip will take")  # both listed
    assert 'class="done"><span class="ch-tick" aria-hidden="true"></span>Tell the driver the address' in html  # index 1 is met
    assert "Confirm that this is your car<span" in html and "(not done)" in html
    assert "accusative for direction" in html and "/grammar" in html and "в Большой театре" in html
    assert "Grammar slips from this chat will show up in your drills." in html and 'href="/drills"' in html
    assert html.count('type="checkbox"') == 2 and html.count("checked") == 2
    assert "Try level 3 and answer" in html
    # cached: a second call does not ask Claude again, and the page now renders it inline
    calls = fake.structured_calls
    client.post(f"/scenarios/c/{conv}/debrief")
    assert fake.structured_calls == calls
    assert "You handled the address well." in client.get(f"/scenarios/c/{conv}").text


def test_debrief_error_offers_retry_and_needs_an_ended_chat(client, conv, fake):
    assert client.post(f"/scenarios/c/{conv}/debrief").status_code == 409
    client.post(f"/scenarios/c/{conv}/end")
    fake.error = ClaudeError("Claude is busy")
    html = client.post(f"/scenarios/c/{conv}/debrief").text
    assert "Claude is busy" in html and "Try again" in html


def test_replay_links_by_level(client, session, conv, fake):
    client.post(f"/scenarios/c/{conv}/end")
    html = client.post(f"/scenarios/c/{conv}/debrief").text  # level 2
    assert "Again at this level" in html and "Try level 3" in html
    assert html.count('action="/scenarios/taxi/start"') == 2
    top = client.post("/scenarios/taxi/start", data={"level": 3}, follow_redirects=False).headers["location"]
    cid = int(top.rsplit("/", 1)[1])
    client.post(f"/scenarios/c/{cid}/end")
    html = client.post(f"/scenarios/c/{cid}/debrief").text
    assert "Again at this level" in html and "Try level 4" not in html and html.count('action="/scenarios/taxi/start"') == 1


def test_phrases_become_cards_and_duplicates_are_skipped(client, session, conv, fake):
    client.post(f"/scenarios/c/{conv}/end")
    client.post(f"/scenarios/c/{conv}/debrief")
    card_service.create_card(session, ru="Приехали", en="We have arrived")
    r = client.post(f"/scenarios/c/{conv}/debrief/cards", data={"i": [0, 1]})
    assert "Added 1 card." in r.text and "1 already in your deck" in r.text
    [card] = session.exec(select(Card).where(Card.source_module == Module.scenario)).all()
    assert card.ru == "Сдачи не надо" and card.en == "Keep the change" and card.tags == "scenario taxi"
    assert card.source_ref_id == conv and card.example_en == "Keep the change, thanks."
    assert "Nothing new to add" in client.post(f"/scenarios/c/{conv}/debrief/cards", data={"i": [0]}).text
    assert "Tick at least one" in client.post(f"/scenarios/c/{conv}/debrief/cards").text
    assert client.post("/scenarios/c/99999/debrief/cards").status_code == 404


def test_listen_first_markup_in_chat(client, conv):
    page = client.get(f"/scenarios/c/{conv}").text
    assert "data-listen-first-toggle" in page and "data-speak-speed" in page
    assert '<p class="ch-text" lang="ru" data-speak data-listen-first>' in page
    assert page.count("data-listen-first>") == 1  # only the partner bubble's text element, not the learner's or a wrapper

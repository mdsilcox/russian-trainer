import pytest
from sqlmodel import select

from app.models import Card, Module
from app.routes import starter as routes
from app.services import cards as card_service
from app.services import starter as svc
from app.services.claude import HAIKU, ClaudeClient, ClaudeError
from tests.test_claude import FakeAnthropic, fake_response


@pytest.fixture(autouse=True)
def pending_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "pending_path", lambda name="starter": tmp_path / f"{name}_pending.json")
    monkeypatch.setattr(svc, "ENRICH_SLEEP", 0)
    return tmp_path


def item(ru, en, **kw):
    base = dict(ru=ru, ru_stressed=ru, en=en, pos="noun", gender=None, aspect=None, aspect_partner=None,
                example_ru=f"{ru}!", example_en=f"{en}!", notes=None)
    return svc.StarterItem(**(base | kw))


class SequentialFake(FakeAnthropic):
    def __init__(self, responses):
        super().__init__(None)
        self.responses = list(responses)

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def use_fake(monkeypatch, *parsed):
    fake = SequentialFake([fake_response(model=HAIKU, parsed=p) for p in parsed])
    monkeypatch.setattr(routes, "ClaudeClient", lambda session: ClaudeClient(session, client=fake))
    return fake


def enrichment(ru, en="meaning"):
    return card_service.CardEnrichment(
        ru_stressed=ru, en=en, pos="noun", gender="m", aspect=None, aspect_partner=None,
        example_ru="Пример.", example_en="Example.", notes=None,
    )


def test_parse_paste_separators_and_dedupe():
    items, dropped = svc.parse_paste("вокзал - station\nАптека — pharmacy\nмолоко\tmilk\nхлеб; bread\nВОКЗАЛ\n\nпривет")
    assert [(i["ru"], i["en"]) for i in items] == [
        ("вокзал", "station"), ("Аптека", "pharmacy"), ("молоко", "milk"), ("хлеб", "bread"), ("привет", ""),
    ]
    assert dropped == 1


def test_hyphenated_word_is_not_split():
    items, _ = svc.parse_paste("кто-то - someone")
    assert items == [{"ru": "кто-то", "en": "someone"}]


def test_generate_review_and_add_flow(client, session, monkeypatch, pending_dir):
    card_service.create_card(session, ru="здравствуйте", en="hello")
    use_fake(monkeypatch, svc.TopicBatch(items=[
        item("здравствуйте", "hello"), item("спасибо", "thanks"), item("СПАСИБО", "dup"),
    ]))

    r = client.post("/import/starter/generate", data={"topic": "greetings"}, follow_redirects=False)
    assert r.status_code == 303 and (pending_dir / "starter_pending.json").exists()

    page = client.get("/import/starter/review").text
    assert "Greetings" in page and "already in deck" in page
    assert page.count('name="sel"') == 2  # in-batch duplicate dropped
    assert page.count("checked") == 1  # existing card is unchecked

    client.post("/import/starter/add", data={"sel": ["greetings:0", "greetings:1"]})
    session.expunge_all()
    cards = session.exec(select(Card).order_by(Card.id)).all()
    assert [c.ru for c in cards] == ["здравствуйте", "спасибо"]  # duplicate skipped even if ticked
    assert cards[1].source_module == Module.starter and cards[1].tags == "starter greetings"
    assert not (pending_dir / "starter_pending.json").exists()


def test_regenerate_replaces_one_topic(client, monkeypatch):
    use_fake(monkeypatch, svc.TopicBatch(items=[item("привет", "hi")]), svc.TopicBatch(items=[item("пока", "bye")]))
    client.post("/import/starter/generate", data={"topic": ["greetings"]})
    client.post("/import/starter/regenerate/greetings")
    page = client.get("/import/starter/review").text
    assert "пока" in page and "привет" not in page


def test_generate_error_is_shown(client, monkeypatch):
    class Boom:
        def __init__(self, session):
            raise ClaudeError("Rate limited by the API.")

    monkeypatch.setattr(routes, "ClaudeClient", Boom)
    page = client.post("/import/starter/generate", data={"topic": "food"}).text
    assert "Rate limited by the API." in page


def test_partial_generation_keeps_finished_topics(client, monkeypatch):
    fake = use_fake(monkeypatch, svc.TopicBatch(items=[item("привет", "hi")]))
    from app.services.claude import ClaudeTruncated

    original = fake._parse

    def parse(**kwargs):
        if fake.responses:
            return original(**kwargs)
        raise ClaudeTruncated("The response was cut off.")

    fake.beta.messages.parse = parse
    page = client.post("/import/starter/generate", data={"topic": ["greetings", "food"]}).text
    assert "привет" in page and "cut off" in page


def test_index_disables_generation_without_key(client, monkeypatch):
    from app.config import get_config

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_config.cache_clear()
    try:
        page = client.get("/import").text
    finally:
        get_config.cache_clear()
    assert "ANTHROPIC_API_KEY" in page and "disabled" in page


def test_paste_flow_with_enrichment(client, session, monkeypatch):
    card_service.create_card(session, ru="аптека", en="pharmacy")
    use_fake(monkeypatch, enrichment("вокза́л", "railway station"))

    r = client.post("/import/paste", data={"text": "аптека - pharmacy\nвокзал\nхлеб - bread\nхлеб", "enrich": "on"},
                    follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/import/paste/review").text
    assert "already in deck" in page and "railway station" in page and "1 repeated line" in page

    client.post("/import/paste/add", data={"sel": ["i:1", "i:2"], "en_i:1": "railway station", "en_i:2": "bread"})
    session.expunge_all()
    added = session.exec(select(Card).where(Card.source_module == Module.manual, Card.tags == "import")).all()
    assert {c.ru for c in added} == {"вокзал", "хлеб"}
    assert next(c for c in added if c.ru == "вокзал").example_ru == "Пример."


def test_paste_without_enrich_skips_rows_lacking_english(client, session):
    client.post("/import/paste", data={"text": "вокзал\nхлеб - bread"})
    client.post("/import/paste/add", data={"sel": ["i:0", "i:1"], "en_i:0": "", "en_i:1": "bread"})
    session.expunge_all()
    assert [c.ru for c in session.exec(select(Card)).all()] == ["хлеб"]


def test_enrich_cap_and_error_stop(monkeypatch):
    calls = []
    monkeypatch.setattr(svc.card_service, "enrich", lambda client, ru, en="": calls.append(ru) or enrichment(ru))
    items = [{"ru": f"слово{i}", "en": ""} for i in range(svc.ENRICH_CAP + 5)]
    msg = svc.enrich_items(None, items, sleep=0)
    assert len(calls) == svc.ENRICH_CAP and "first 60" in msg
    assert items[-1]["en"] == ""

    def fail(client, ru, en=""):
        raise ClaudeError("boom")

    monkeypatch.setattr(svc.card_service, "enrich", fail)
    assert "boom" in svc.enrich_items(None, [{"ru": "а", "en": ""}], sleep=0)

import pytest
from sqlmodel import select

from app.models import Card, Module, Setting
from app.routes import starter as routes
from app.services import cards as card_service
from app.services import frequency as freq
from app.services import starter
from app.services.claude import HAIKU, ClaudeClient, ClaudeError
from tests.test_starter import SequentialFake, fake_response


@pytest.fixture(autouse=True)
def pending_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(starter, "pending_path", lambda name="starter": tmp_path / f"{name}_pending.json")
    return tmp_path


def fitem(ru, en, forms=(), **kw):
    base = dict(ru=ru, ru_stressed=ru, en=en, pos="noun", gender=None, aspect=None, aspect_partner=None,
                example_ru=f"{ru}!", example_en=f"{en}!", notes=None,
                forms=[card_service.FormSuggestion(ru=r, en=e, note=n) for r, e, n in forms])
    return freq.FrequencyItem(**(base | kw))


def use_fake(monkeypatch, *batches):
    fake = SequentialFake([fake_response(model=HAIKU, parsed=freq.FrequencyBatch(items=list(b))) for b in batches])
    monkeypatch.setattr(routes, "ClaudeClient", lambda session: ClaudeClient(session, client=fake))
    return fake


def prompt_of(fake, i=0):
    return fake.calls[i]["messages"][0]["content"]


def test_rank_starts_at_one_and_advances_by_batch_size(client, session, monkeypatch):
    assert freq.next_rank(session) == 1
    fake = use_fake(monkeypatch, [fitem("дом", "house")], [fitem("город", "city")])
    client.post("/import/frequency/generate")
    session.expunge_all()
    assert freq.next_rank(session) == 1 + freq.BATCH_SIZE
    assert "ranks 1 to 25" in prompt_of(fake)
    client.post("/import/frequency/add", data={"sel": ["i:0"]})
    client.post("/import/frequency/generate")
    assert "ranks 26 to 50" in prompt_of(fake, 1)
    session.expunge_all()
    assert session.get(Setting, freq.RANK_KEY).value == 51


def test_known_words_are_excluded_in_prompt_and_after(client, session, monkeypatch):
    card_service.create_card(session, ru="дом", en="house")
    card_service.create_card(session, ru="Ещё", en="more")
    card_service.create_card(session, ru="из Москвы", en="from Moscow", kind="form")
    fake = use_fake(monkeypatch, [fitem("дом", "house"), fitem("город", "city"), fitem("ГОРОД", "city again"),
                                  fitem("еще", "still")])
    client.post("/import/frequency/generate")
    prompt = prompt_of(fake)
    assert "дом" in prompt and "еще" in prompt and "из москвы" not in prompt  # normalised, words only
    pending = starter.load_pending(freq.PENDING)
    assert [i["ru"] for i in pending["items"]] == ["город"]
    assert pending["skipped"] == 3


def test_stage_review_and_accept_with_forms(client, session, monkeypatch, pending_dir):
    use_fake(monkeypatch, [
        fitem("Москва", "Moscow", forms=[("в Москве́", "in Moscow", "prepositional after в"),
                                          ("из Москвы́", "from Moscow", "genitive after из")]),
        fitem("город", "city"),
    ])
    r = client.post("/import/frequency/generate", follow_redirects=False)
    assert r.status_code == 303 and (pending_dir / "frequency_pending.json").exists()
    assert session.exec(select(Card)).all() == []  # nothing reaches the deck yet

    page = client.get("/import/frequency/review").text
    assert "в Москве́" in page and page.count('name="form"') == 2

    client.post("/import/frequency/add", data={"sel": ["i:0", "i:1"], "form": ["i:0:1"]})
    session.expunge_all()
    cards = {c.ru: c for c in session.exec(select(Card)).all()}
    assert set(cards) == {"Москва", "город", "из Москвы"}
    assert cards["Москва"].tags == "frequency" and cards["Москва"].source_module == Module.starter
    assert cards["из Москвы"].kind == "form" and "frequency" in cards["из Москвы"].tags
    assert "Москва" in cards["из Москвы"].notes
    assert not (pending_dir / "frequency_pending.json").exists()


def test_error_is_friendly_and_does_not_advance(client, session, monkeypatch):
    class Boom:
        def __init__(self, session):
            raise ClaudeError("Rate limited by the API.")

    monkeypatch.setattr(routes, "ClaudeClient", Boom)
    page = client.post("/import/frequency/generate").text
    assert "Rate limited by the API." in page
    assert freq.next_rank(session) == 1


def test_pending_batch_blocks_a_second_generation(client, session, monkeypatch):
    fake = use_fake(monkeypatch, [fitem("дом", "house")])
    client.post("/import/frequency/generate")
    r = client.post("/import/frequency/generate", follow_redirects=False)
    assert r.headers["location"].endswith("/import/frequency/review") and len(fake.calls) == 1
    assert "waiting for review" in client.get("/import").text


def test_discard_rewinds_rank(client, session, monkeypatch, pending_dir):
    use_fake(monkeypatch, [fitem("дом", "house")])
    client.post("/import/frequency/generate")
    client.post("/import/frequency/discard")
    session.expunge_all()
    assert freq.next_rank(session) == 1
    assert not (pending_dir / "frequency_pending.json").exists()


def test_import_page_has_frequency_section_and_loading_text(client):
    page = client.get("/import").text
    assert "Frequency deck: the most common Russian words you don" in page
    assert "20 to 40 seconds" in page


def test_unticked_words_are_remembered_as_known(client, session, monkeypatch):
    fake = use_fake(monkeypatch, [fitem("быть", "to be"), fitem("город", "city")],
                    [fitem("быть", "to be"), fitem("дом", "house")])
    client.post("/import/frequency/generate")
    assert "won&#39;t come back" in client.get("/import/frequency/review").text or "come back" in client.get("/import/frequency/review").text
    client.post("/import/frequency/add", data={"sel": ["i:1"]})
    session.expunge_all()
    assert freq.remembered_known(session) == ["быть"]
    client.post("/import/frequency/generate")
    assert "быть" in prompt_of(fake, 1)
    assert [i["ru"] for i in starter.load_pending(freq.PENDING)["items"]] == ["дом"]  # filtered after too


def test_discarding_a_batch_marks_nothing_known(client, session, monkeypatch):
    use_fake(monkeypatch, [fitem("быть", "to be")])
    client.post("/import/frequency/generate")
    client.post("/import/frequency/discard")
    session.expunge_all()
    assert freq.remembered_known(session) == []

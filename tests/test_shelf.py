from datetime import date, datetime, timezone

import pytest
from sqlmodel import select

from app.models import Card, InputLog, Module
from app.routes import shelf as shelf_routes
from app.services import cards as card_svc
from app.services import shelf as svc
from app.services.claude import HAIKU, ClaudeClient
from tests.test_claude import FakeAnthropic, fake_response

# A Wednesday noon in UTC; the local date can differ by a day near midnight, so tests build
# `now` from a local date instead of relying on this one.
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def log_on(session, day: date, minutes: int, kind: str = "reading"):
    session.add(InputLog(date=day, minutes=minutes, kind=kind, title="x"))
    session.commit()


# --- Shelf data ---------------------------------------------------------------------

def test_shelf_data_integrity():
    items = svc.items()
    assert 20 <= len(items) <= 30
    assert len({i.slug for i in items}) == len(items)
    levels = {lv.name for lv in svc.LEVELS}
    for i in items:
        assert i.why and i.title and i.title_en and i.minutes_hint > 0
        assert i.level in levels
        assert i.kind in {"book", "graded reader", "film", "series", "YouTube", "podcast"}
        assert i.log_kind in svc.KINDS
        assert i.link is None or i.link.startswith("https://")
    assert [i.slug for _, group in svc.by_level() for i in group].count("kukhnya") == 1
    assert sum(len(g) for _, g in svc.by_level()) == len(items)


def test_adult_items_flagged_as_in_research():
    adult = {i.slug for i in svc.items() if i.adult}
    assert adult == {"metod", "obychnaya-zhenshchina", "chiki", "slovo-patsana"}


def test_log_kind_follows_format():
    assert svc.get("slow-russian").log_kind == "listening"
    assert svc.get("ironiya-sudby").log_kind == "watching"
    assert svc.get("nosov-mishkina-kasha").log_kind == "reading"
    assert svc.get("nope") is None


# --- Logging and totals ---------------------------------------------------------------

def test_log_minutes_defaults_title_from_shelf_item(session):
    entry = svc.log_minutes(session, 20, "listening", shelf_slug="raketa", now=NOW)
    assert entry.title == svc.get("raketa").title and entry.shelf_slug == "raketa"
    free = svc.log_minutes(session, 5, "reading", "  A menu ", now=NOW)
    assert free.title == "A menu" and free.shelf_slug is None


@pytest.mark.parametrize("minutes,kind", [(0, "reading"), (-5, "reading"), (601, "reading"), (10, "dancing")])
def test_log_minutes_rejects_bad_input(session, minutes, kind):
    with pytest.raises(ValueError):
        svc.log_minutes(session, minutes, kind)
    assert session.exec(select(InputLog)).all() == []


def test_log_minutes_rejects_unknown_shelf_item(session):
    with pytest.raises(ValueError):
        svc.log_minutes(session, 10, "reading", shelf_slug="nope")


def test_week_and_30_day_totals(session):
    from app.services import stats

    today = stats.local_date(NOW)
    monday = date.fromordinal(today.toordinal() - today.weekday())
    sunday_before = date.fromordinal(monday.toordinal() - 1)
    log_on(session, today, 20)
    log_on(session, monday, 15, "listening")
    log_on(session, sunday_before, 40, "watching")  # last week, but within 30 days
    log_on(session, date.fromordinal(today.toordinal() - 29), 7)  # the 30th day counts
    log_on(session, date.fromordinal(today.toordinal() - 30), 100)  # too old
    assert svc.this_week(session, NOW) == 35
    assert svc.input_minutes(session, 30, NOW) == 82
    assert svc.input_minutes(session, 1, NOW) == 20


def test_totals_empty(session):
    assert svc.this_week(session, NOW) == 0 and svc.input_minutes(session, 30, NOW) == 0


# --- Routes -----------------------------------------------------------------------------

def test_shelf_page_renders_ladder(client):
    page = client.get("/shelf").text
    for level in svc.LEVELS:
        assert level.name in page
    assert "Input this week" in page and "Mine a sentence" in page
    assert 'lang="ru"' in page and "Полка" in page
    assert page.count('rel="noopener"') == sum(1 for i in svc.items() if i.link)
    assert page.count(">18+<") == 4
    assert 'href="/shelf"' in page  # nav


def test_log_via_htmx_updates_total(client, session):
    response = client.post("/shelf/log", data={"minutes": "25", "kind": "listening", "slug": "slow-russian"},
                           headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert "Logged 25 min" in response.text
    assert 'id="input-total"' in response.text and 'hx-swap-oob="true"' in response.text
    assert '<span class="sh-total-num">25</span>' in response.text
    client.post("/shelf/log", data={"minutes": "10", "kind": "reading", "title": "Menu"})
    assert '<span class="sh-total-num">35</span>' in client.get("/shelf").text
    rows = session.exec(select(InputLog).order_by(InputLog.id)).all()
    assert [(r.minutes, r.kind, r.shelf_slug, r.title) for r in rows][1] == (10, "reading", None, "Menu")


@pytest.mark.parametrize("minutes", ["0", "-3", "abc", "", "2.5", "9999"])
def test_log_rejects_invalid_minutes(client, session, minutes):
    response = client.post("/shelf/log", data={"minutes": minutes, "kind": "reading"})
    assert response.status_code == 422
    assert "Minutes must be a whole number" in response.text
    assert session.exec(select(InputLog)).all() == []


def test_log_rejects_bad_kind(client, session):
    assert client.post("/shelf/log", data={"minutes": "5", "kind": "sleeping"}).status_code == 422
    assert session.exec(select(InputLog)).all() == []


# --- Sentence mining ---------------------------------------------------------------------

def enrichment(**over):
    data = dict(
        ru_stressed="дое́хать", en="to get to, to reach (by transport)", pos="verb", gender=None, aspect="pf",
        aspect_partner="добира́ться", example_ru="Как дое́хать до метро́?", example_en="How do I get to the metro?",
        notes="Takes до + genitive.",
    )
    data.update(over)
    return card_svc.CardEnrichment(**data)


def use_enrichment(monkeypatch, parsed):
    fake = FakeAnthropic(fake_response(model=HAIKU, parsed=parsed))
    monkeypatch.setattr(shelf_routes, "ClaudeClient", lambda session: ClaudeClient(session, client=fake))
    return fake


def test_mine_enrich_word_passes_line_as_context(client, monkeypatch):
    line = "Скажите, как доехать до Красной площади?"
    fake = use_enrichment(monkeypatch, enrichment(example_ru="Скажи́те, как дое́хать до Кра́сной пло́щади?",
                                                  example_en="Tell me, how do I get to Red Square?"))
    page = client.post("/shelf/mine/enrich", data={"line": line, "word": "доехать", "source": "easy-russian"}).text
    assert "Check the card" in page
    assert line in fake.calls[0]["messages"][0]["content"]
    assert "Скажи́те, как дое́хать до Кра́сной пло́щади?" in page and "Tell me, how do I get to Red Square?" in page
    assert "Source: Easy Russian." in page
    assert "mined easy-russian" in page
    assert "Takes до + genitive." in page


def test_mine_preview_does_not_mark_stress_verified(client, monkeypatch):
    use_enrichment(monkeypatch, enrichment())
    page = client.post("/shelf/mine/enrich", data={"line": "Как доехать до метро?", "word": "доехать"}).text
    assert 'name="stress_verified"' in page and 'name="stress_verified" checked' not in page


def test_mine_enrich_whole_line_keeps_claude_example(client, monkeypatch):
    fake = use_enrichment(monkeypatch, enrichment(ru_stressed="Как дое́хать до метро́?", en="How do I get to the metro?"))
    page = client.post("/shelf/mine/enrich", data={"line": "Как доехать до метро?", "source_text": "a friend"}).text
    assert "Source: a friend." in page and "mined" in page
    assert "met this word" not in fake.calls[0]["messages"][0]["content"]
    assert "Как дое́хать до метро́?" in page


def test_mine_enrich_errors(client, monkeypatch):
    assert "Paste the Russian line" in client.post("/shelf/mine/enrich", data={"line": "  "}).text
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from app.config import get_config
    get_config.cache_clear()
    try:
        page = client.post("/shelf/mine/enrich", data={"line": "Привет"}).text
    finally:
        get_config.cache_clear()
    assert "ANTHROPIC_API_KEY" in page


def save_data(**over):
    data = {"ru": "доехать", "ru_stressed": "дое'хать", "en": "to get to", "example_ru": "Как доехать до метро?",
            "tags": "easy-russian", "notes": "Source: Easy Russian."}
    return data | over


def test_mine_save_creates_media_card(client, session):
    page = client.post("/shelf/mine/save", data=save_data()).text
    assert "Card added" in page
    card = session.exec(select(Card)).one()
    assert card.source_module == Module.media
    assert card.ru_stressed == "дое́хать"
    assert card.example_ru == "Как доехать до метро?"
    assert set(card.tags.split()) == {"mined", "easy-russian"}
    assert card.notes == "Source: Easy Russian."


def test_mine_save_skips_duplicate(client, session):
    card_svc.create_card(session, ru="Доехать", en="to reach")
    page = client.post("/shelf/mine/save", data=save_data()).text
    assert "already in your deck" in page
    assert len(session.exec(select(Card)).all()) == 1


def test_mine_save_requires_english(client, session):
    response = client.post("/shelf/mine/save", data=save_data(en=""))
    assert response.status_code == 422 and "English meaning is required" in response.text
    assert session.exec(select(Card)).all() == []


# --- Dashboard ------------------------------------------------------------------------

def test_dashboard_input_tile(client, session):
    from app.services import stats

    today = stats.local_date()
    log_on(session, today, 30)
    log_on(session, date.fromordinal(today.toordinal() - 20), 12)
    page = client.get("/dashboard").text
    assert "<h2>Input" in page and 'href="/shelf"' in page
    assert "12 min in the last 30 days" not in page  # the 30-day figure includes today's minutes
    assert "42 min in the last 30 days" in page
    week = svc.this_week(session)
    assert f'data-count="{week}"' in page

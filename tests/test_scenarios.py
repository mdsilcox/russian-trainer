import re

from sqlmodel import select

from app.models import Conversation, Scenario
from app.services import scenarios

ACUTE = "́"
VOWELS = "аеёиоуыэюяАЕЁИОУЫЭЮЯ"
WORD = re.compile(r"[А-Яа-яЁё́]+")


def stress_problems(text: str) -> list[str]:
    """Words of 2+ syllables need one acute on a non-ё vowel; one-syllable words and ё words get none."""
    problems = []
    for part in WORD.findall(text):
        vowels = [c for c in part if c in VOWELS]
        marks = part.count(ACUTE)
        if "ё" in part.lower():
            if marks:
                problems.append(f"mark on ё word: {part}")
        elif len(vowels) >= 2 and marks != 1:
            problems.append(f"needs exactly one stress mark: {part}")
        elif len(vowels) == 1 and marks:
            problems.append(f"mark on one-syllable word: {part}")
        if re.search(f"[^{VOWELS}]{ACUTE}", part):
            problems.append(f"mark not on a vowel: {part}")
    return problems


def test_stress_checker_catches_errors():
    assert stress_problems("Здра́вствуйте") == []
    assert stress_problems("Здравствуйте")
    assert stress_problems("Спаси́бо") == []
    assert stress_problems("не́т")
    assert stress_problems("счёт") == []


def test_seed_is_idempotent_and_complete(session):
    scenarios.seed(session)
    scenarios.seed(session)
    rows = session.exec(select(Scenario)).all()
    assert len(rows) == len(scenarios.SCENARIOS) >= 14
    assert len({r.slug for r in rows}) == len(rows)


def test_seed_updates_existing_and_keeps_scenarios_with_conversations(session):
    scenarios.seed(session)
    row = session.exec(select(Scenario).where(Scenario.slug == "taxi")).one()
    row.title, row.goals_json = "Old title", ["x"]
    session.add(row)
    session.add(Scenario(slug="legacy", title="Legacy", setting="s", partner_role="r"))
    session.commit()
    legacy = session.exec(select(Scenario).where(Scenario.slug == "legacy")).one()
    session.add(Conversation(scenario_id=legacy.id))
    session.commit()

    scenarios.seed(session)
    session.expire_all()
    row = session.exec(select(Scenario).where(Scenario.slug == "taxi")).one()
    assert row.title == "Taxi or Yandex Go" and len(row.goals_json) >= 3
    assert session.exec(select(Scenario).where(Scenario.slug == "legacy")).first() is not None


def test_scenario_content_shape(session):
    scenarios.seed(session)
    for s in session.exec(select(Scenario)).all():
        assert 3 <= len(s.goals_json) <= 5, s.slug
        assert 6 <= len(s.vocab_json) <= 10, s.slug
        assert s.opening_ru.strip() and s.persona.strip() and s.group and s.setting and s.partner_role, s.slug
        assert s.level in (1, 2, 3), s.slug
        for v in s.vocab_json:
            assert v["ru"].strip() and v["en"].strip(), s.slug


def test_russian_is_stressed_and_english_has_no_em_dash(session):
    scenarios.seed(session)
    for s in session.exec(select(Scenario)).all():
        russian = [s.opening_ru] + [v["ru"] for v in s.vocab_json]
        for text in russian:
            assert stress_problems(text) == [], (s.slug, text, stress_problems(text))
            assert "'" not in text and "—" not in text
        english = [s.title, s.setting, s.partner_role, s.persona, s.group, *s.goals_json, *(v["en"] for v in s.vocab_json)]
        assert not any("—" in t for t in english), s.slug


def test_list_and_detail_pages_render(client, session):
    scenarios.seed(session)
    html = client.get("/scenarios").text
    for group in ("Getting around", "Food and drink", "Staying", "Shopping", "People", "Problems"):
        assert group in html
    assert "Taxi or Yandex Go" in html and "Slow and clear" in html and "Natural speed" in html
    assert 'action="/scenarios/taxi/start"' in html

    page = client.get("/scenarios/taxi")
    assert page.status_code == 200
    assert 'lang="ru"' in page.text and "Tell the driver the address" in page.text
    assert client.get("/scenarios/nope").status_code == 404


def test_start_accepts_levels_one_to_three_only(client, session):
    scenarios.seed(session)
    for level in (1, 2, 3):
        r = client.post("/scenarios/taxi/start", data={"level": level}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/scenarios/c/")
    for bad in ("0", "4", "x", ""):
        assert client.post("/scenarios/taxi/start", data={"level": bad}).status_code == 422
    assert client.post("/scenarios/taxi/start").status_code == 422
    assert client.post("/scenarios/nope/start", data={"level": 1}).status_code == 404

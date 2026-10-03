import pytest
from sqlmodel import Session, select

from app.models import Setting
from app.services import srs, today
from app.services import study_settings as ss

VALID = {
    "daily_new_cards": "10",
    "desired_retention": "0.85",
    "split_srs": "10",
    "split_drill_or_story": "8",
    "split_scenario": "7",
}


def form(**over):
    return {**VALID, **over}


# ---- load ----

def test_load_defaults(session):
    for key in ("daily_new_cards", "desired_retention", "session_split"):
        row = session.get(Setting, key)
        if row is not None:
            session.delete(row)
    session.commit()
    s = ss.load(session)
    assert s.daily_new_cards == srs.DEFAULT_NEW_PER_DAY == 15
    assert s.desired_retention == srs.DEFAULT_RETENTION == 0.9
    assert s.session_split == today.DEFAULT_SPLIT


def test_load_stored_values_cast(session):
    # migrate() seeds these keys, so overwrite the rows rather than adding new ones.
    session.merge(Setting(key="daily_new_cards", value=20))
    session.merge(Setting(key="desired_retention", value=0.8))
    session.merge(Setting(key="session_split", value={"srs": 5, "drill_or_story": 6}))
    session.commit()
    s = ss.load(session)
    assert s.daily_new_cards == 20 and isinstance(s.daily_new_cards, int)
    assert s.desired_retention == 0.8 and isinstance(s.desired_retention, float)
    assert s.session_split == {"srs": 5, "drill_or_story": 6, "scenario": 7}


# ---- parse: valid ----

def test_parse_valid_basic():
    s, errors = ss.parse(VALID)
    assert errors == {}
    assert s == ss.StudySettings(10, 0.85, {"srs": 10, "drill_or_story": 8, "scenario": 7})


@pytest.mark.parametrize("raw,expected", [
    ("0.85", 0.85), ("85", 0.85), ("85%", 0.85), ("85 %", 0.85), (" 85% ", 0.85), ("0,85", 0.85),
    ("0.70", 0.7), ("70", 0.7), ("70%", 0.7), ("0.97", 0.97), ("97", 0.97), ("97%", 0.97), ("0.9", 0.9),
])
def test_parse_retention_valid(raw, expected):
    s, errors = ss.parse(form(desired_retention=raw))
    assert errors == {}
    assert s.desired_retention == expected


@pytest.mark.parametrize("raw", ["", "  ", "1", "0.69", "98", "0.975", "abc", "0.0", "-0.8", "69%", "1.5", "%", "8 5"])
def test_parse_retention_invalid(raw):
    s, errors = ss.parse(form(desired_retention=raw))
    assert s is None
    assert list(errors) == ["desired_retention"]
    assert "0.70" in errors["desired_retention"]


@pytest.mark.parametrize("raw,expected", [("0", 0), ("100", 100), ("  12  ", 12), ("007", 7)])
def test_parse_daily_valid(raw, expected):
    s, errors = ss.parse(form(daily_new_cards=raw))
    assert errors == {}
    assert s.daily_new_cards == expected


@pytest.mark.parametrize("raw", ["", " ", "10.5", "abc", "-1", "101", "1e2", "+5", "1 0"])
def test_parse_daily_invalid(raw):
    s, errors = ss.parse(form(daily_new_cards=raw))
    assert s is None
    assert errors == {"daily_new_cards": "Enter a whole number from 0 to 100."}


def test_parse_missing_fields():
    s, errors = ss.parse({})
    assert s is None
    assert set(errors) == {"daily_new_cards", "desired_retention", "split_srs", "split_drill_or_story", "split_scenario"}


def test_parse_split_bounds_and_totals():
    s, errors = ss.parse(form(split_srs="2", split_drill_or_story="2", split_scenario="1"))
    assert errors == {} and sum(s.session_split.values()) == 5
    s, errors = ss.parse(form(split_srs="60", split_drill_or_story="30", split_scenario="30"))
    assert errors == {} and sum(s.session_split.values()) == 120


def test_parse_split_total_errors():
    s, errors = ss.parse(form(split_srs="2", split_drill_or_story="2", split_scenario="0"))
    assert s is None
    assert errors == {"session_split": "The three blocks must add up to between 5 and 120 minutes (now 4)."}
    s, errors = ss.parse(form(split_srs="60", split_drill_or_story="60", split_scenario="10"))
    assert errors == {"session_split": "The three blocks must add up to between 5 and 120 minutes (now 130)."}


@pytest.mark.parametrize("raw", ["", "61", "-1", "5.5", "x"])
def test_parse_split_field_invalid_skips_total(raw):
    s, errors = ss.parse(form(split_srs=raw))
    assert s is None
    assert list(errors) == ["split_srs"]
    assert "0 to 60" in errors["split_srs"]


# ---- save ----

def test_save_round_trip_and_consumers(session):
    original = ss.StudySettings(7, 0.8, {"srs": 12, "drill_or_story": 3, "scenario": 4})
    ss.save(session, original)
    assert ss.load(session) == original
    assert today.session_split(session) == original.session_split
    assert srs.make_scheduler(session).desired_retention == 0.8
    assert session.get(Setting, "daily_new_cards").value == 7


def test_save_overwrites_and_does_not_alias(session):
    ss.save(session, ss.StudySettings(7, 0.8, {"srs": 12, "drill_or_story": 3, "scenario": 4}))
    new = ss.StudySettings(9, 0.95, {"srs": 1, "drill_or_story": 2, "scenario": 3})
    ss.save(session, new)
    new.session_split["srs"] = 50
    session.expire_all()
    loaded = ss.load(session)
    assert loaded.session_split == {"srs": 1, "drill_or_story": 2, "scenario": 3}
    assert loaded.daily_new_cards == 9 and loaded.desired_retention == 0.95
    assert len(session.exec(select(Setting).where(Setting.key == "session_split")).all()) == 1


# ---- routes ----

def test_get_form_filled_with_defaults(client):
    r = client.get("/settings/study")
    assert r.status_code == 200
    assert "Study settings · Russian Trainer" in r.text
    assert 'name="daily_new_cards" value="15"' in r.text
    assert 'name="desired_retention" value="0.9"' in r.text
    assert 'name="split_srs" value="10"' in r.text
    assert 'name="split_drill_or_story" value="8"' in r.text
    assert 'name="split_scenario" value="7"' in r.text
    assert 'action="/settings/study"' in r.text and 'href="/settings"' in r.text
    assert "<legend>" in r.text
    assert "aria-invalid" not in r.text


def test_post_valid_saves_and_redirects(client, engine):
    r = client.post("/settings/study", data=form(desired_retention="80%", daily_new_cards="5"), follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/settings?saved=study"
    with Session(engine) as s:
        assert ss.load(s) == ss.StudySettings(5, 0.8, {"srs": 10, "drill_or_story": 8, "scenario": 7})
    page = client.get("/settings?saved=study")
    assert "Study settings saved." in page.text
    assert "Study settings saved." not in client.get("/settings").text
    assert 'name="daily_new_cards" value="5"' in client.get("/settings/study").text


def test_post_invalid_400_echoes_and_saves_nothing(client, engine):
    with Session(engine) as s:
        before = ss.load(s)
    r = client.post("/settings/study", data=form(daily_new_cards="10.5", desired_retention="abc", split_srs="60",
                                                 split_drill_or_story="60", split_scenario="10"))
    assert r.status_code == 400
    assert 'value="10.5"' in r.text and 'value="abc"' in r.text
    assert 'aria-invalid="true"' in r.text
    assert 'id="daily_new_cards-error"' in r.text
    assert 'aria-describedby="daily_new_cards-hint daily_new_cards-error"' in r.text
    assert "Enter a whole number from 0 to 100." in r.text
    assert "Enter a value from 0.70 to 0.97" in r.text
    assert "must add up to between 5 and 120 minutes (now 130)" in r.text
    with Session(engine) as s:
        assert ss.load(s) == before


def test_post_bad_total_shown_in_split_group(client, engine):
    with Session(engine) as s:
        before = ss.load(s)
    r = client.post("/settings/study", data=form(split_srs="60", split_drill_or_story="60", split_scenario="10"))
    assert r.status_code == 400
    assert "must add up to between 5 and 120 minutes (now 130)" in r.text
    assert 'id="session_split-error"' in r.text
    with Session(engine) as s:
        assert ss.load(s) == before


def test_post_missing_fields_is_400_not_422(client):
    r = client.post("/settings/study", data={"daily_new_cards": "5"})
    assert r.status_code == 400
    assert 'value="5"' in r.text
    assert client.post("/settings/study").status_code == 400


def test_settings_page_links_to_editor(client):
    r = client.get("/settings")
    assert r.status_code == 200
    assert 'href="/settings/study"' in r.text
    assert "Edit study settings" in r.text

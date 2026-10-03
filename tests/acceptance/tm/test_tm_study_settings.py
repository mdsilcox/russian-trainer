"""Feature 4: study settings editor."""

import re

import pytest
from sqlmodel import Session, select

GOOD = {
    "daily_new_cards": "20",
    "desired_retention": "0.85",
    "split_srs": "12",
    "split_drill_or_story": "9",
    "split_scenario": "6",
}


def form(**overrides):
    return {**GOOD, **overrides}


def stored(engine, key):
    from app.models import Setting

    with Session(engine) as s:
        row = s.get(Setting, key)
        return None if row is None else row.value


def save_values(session, daily=33, retention=0.8, split=None):
    from app.services import study_settings

    split = split or {"srs": 13, "drill_or_story": 14, "scenario": 15}
    study_settings.save(session, study_settings.StudySettings(daily, retention, split))


def has_value(html, name, value):
    return bool(
        re.search(rf'<input[^>]*name="{name}"[^>]*value="{re.escape(value)}"', html)
        or re.search(rf'<input[^>]*value="{re.escape(value)}"[^>]*name="{name}"', html)
    )


# --- load / save ------------------------------------------------------------------------------


def test_f4_load_defaults_when_missing(session):
    from app.models import Setting
    from app.services import srs, study_settings, today

    for key in ("daily_new_cards", "desired_retention", "session_split"):
        row = session.get(Setting, key)
        if row is not None:
            session.delete(row)
    session.commit()
    s = study_settings.load(session)
    assert s.daily_new_cards == srs.DEFAULT_NEW_PER_DAY
    assert s.desired_retention == pytest.approx(srs.DEFAULT_RETENTION)
    assert s.session_split == today.DEFAULT_SPLIT


def test_f4_save_stores_typed_values(session, engine):
    save_values(session, daily=33, retention=0.8, split={"srs": 13, "drill_or_story": 14, "scenario": 15})
    daily = stored(engine, "daily_new_cards")
    retention = stored(engine, "desired_retention")
    split = stored(engine, "session_split")
    assert daily == 33 and type(daily) is int
    assert retention == pytest.approx(0.8) and type(retention) is float
    assert split == {"srs": 13, "drill_or_story": 14, "scenario": 15}
    assert all(type(v) is int for v in split.values())


def test_f4_save_reaches_scheduler_and_today(session, engine):
    from app.services import srs, today

    save_values(session, retention=0.83, split={"srs": 11, "drill_or_story": 4, "scenario": 20})
    with Session(engine) as fresh:
        assert srs.make_scheduler(fresh).desired_retention == pytest.approx(0.83)
        assert today.session_split(fresh) == {"srs": 11, "drill_or_story": 4, "scenario": 20}
        assert fresh.get(__import__("app.models", fromlist=["Setting"]).Setting, "daily_new_cards").value == 33


def test_f4_load_round_trip(session):
    from app.services import study_settings

    save_values(session, daily=0, retention=0.97, split={"srs": 0, "drill_or_story": 5, "scenario": 0})
    s = study_settings.load(session)
    assert s.daily_new_cards == 0
    assert s.desired_retention == pytest.approx(0.97)
    assert s.session_split == {"srs": 0, "drill_or_story": 5, "scenario": 0}


def test_f4_save_overwrites_previous(session, engine):
    save_values(session, daily=10)
    save_values(session, daily=50, retention=0.9)
    assert stored(engine, "daily_new_cards") == 50
    assert stored(engine, "desired_retention") == pytest.approx(0.9)


# --- parse ------------------------------------------------------------------------------------


def test_f4_parse_valid():
    from app.services import study_settings

    settings, errors = study_settings.parse(GOOD)
    assert errors == {}
    assert isinstance(settings, study_settings.StudySettings)
    assert settings.daily_new_cards == 20 and type(settings.daily_new_cards) is int
    assert settings.desired_retention == pytest.approx(0.85)
    assert settings.session_split == {"srs": 12, "drill_or_story": 9, "scenario": 6}


def test_f4_parse_ignores_whitespace():
    from app.services import study_settings

    settings, errors = study_settings.parse(
        form(daily_new_cards=" 20 ", desired_retention="  85% ", split_srs=" 12", split_drill_or_story="9 ", split_scenario=" 6 ")
    )
    assert errors == {}
    assert settings.daily_new_cards == 20
    assert settings.desired_retention == pytest.approx(0.85)
    assert settings.session_split == {"srs": 12, "drill_or_story": 9, "scenario": 6}


@pytest.mark.parametrize("raw", ["0.85", "85", "85%", " 85% ", "0.850"])
def test_f4_retention_formats(raw):
    from app.services import study_settings

    settings, errors = study_settings.parse(form(desired_retention=raw))
    assert errors == {}, raw
    assert settings.desired_retention == pytest.approx(0.85)


def test_f4_retention_formats_other_values():
    from app.services import study_settings

    for raw, expected in (("0.9", 0.9), ("90", 0.9), ("90%", 0.9), ("70", 0.7), ("0.7", 0.7), ("0.97", 0.97), ("97%", 0.97)):
        settings, errors = study_settings.parse(form(desired_retention=raw))
        assert errors == {}, raw
        assert settings.desired_retention == pytest.approx(expected), raw


@pytest.mark.parametrize("raw", ["0.98", "98", "98%", "0.69", "69", "69%", "0.5", "abc", "1.5", "0"])
def test_f4_retention_bounds(raw):
    from app.services import study_settings

    settings, errors = study_settings.parse(form(desired_retention=raw))
    assert settings is None, raw
    assert "desired_retention" in errors, raw
    assert errors["desired_retention"].strip()


@pytest.mark.parametrize("raw", ["0", "1", "15", "100", " 7 "])
def test_f4_daily_new_cards_valid(raw):
    from app.services import study_settings

    settings, errors = study_settings.parse(form(daily_new_cards=raw))
    assert errors == {}
    assert settings.daily_new_cards == int(raw)


@pytest.mark.parametrize("raw", ["101", "-1", "5.5", "abc", "1e2", "1,5"])
def test_f4_daily_new_cards_invalid(raw):
    from app.services import study_settings

    settings, errors = study_settings.parse(form(daily_new_cards=raw))
    assert settings is None, raw
    assert "daily_new_cards" in errors, raw


def test_f4_split_field_bounds():
    from app.services import study_settings

    for field in ("split_srs", "split_drill_or_story", "split_scenario"):
        settings, errors = study_settings.parse(form(**{field: "61"}))
        assert settings is None and field in errors, field
        settings, errors = study_settings.parse(form(**{field: "-1"}))
        assert settings is None and field in errors, field
        settings, errors = study_settings.parse(form(**{field: "x"}))
        assert settings is None and field in errors, field
    settings, errors = study_settings.parse(form(split_srs="60", split_drill_or_story="30", split_scenario="30"))
    assert errors == {}
    assert settings.session_split["srs"] == 60


def test_f4_split_total_bounds():
    from app.services import study_settings

    # total below 5
    settings, errors = study_settings.parse(form(split_srs="2", split_drill_or_story="2", split_scenario="0"))
    assert settings is None and "session_split" in errors
    # total above 120
    settings, errors = study_settings.parse(form(split_srs="60", split_drill_or_story="60", split_scenario="60"))
    assert settings is None and "session_split" in errors
    # limits are inclusive
    settings, errors = study_settings.parse(form(split_srs="5", split_drill_or_story="0", split_scenario="0"))
    assert errors == {} and settings.session_split == {"srs": 5, "drill_or_story": 0, "scenario": 0}
    settings, errors = study_settings.parse(form(split_srs="40", split_drill_or_story="40", split_scenario="40"))
    assert errors == {} and sum(settings.session_split.values()) == 120


def test_f4_parse_reports_every_invalid_field():
    from app.services import study_settings

    settings, errors = study_settings.parse(form(daily_new_cards="500", desired_retention="2", split_srs="99"))
    assert settings is None
    assert {"daily_new_cards", "desired_retention", "split_srs"} <= set(errors)
    assert "split_drill_or_story" not in errors and "split_scenario" not in errors


# --- pages ------------------------------------------------------------------------------------


def test_f4_settings_links_to_editor(client):
    assert 'href="/settings/study"' in client.get("/settings").text


def test_f4_form_filled_with_current_values(client, session):
    save_values(session, daily=33, retention=0.8, split={"srs": 13, "drill_or_story": 14, "scenario": 15})
    response = client.get("/settings/study")
    assert response.status_code == 200
    html = response.text
    assert has_value(html, "daily_new_cards", "33")
    assert has_value(html, "split_srs", "13")
    assert has_value(html, "split_drill_or_story", "14")
    assert has_value(html, "split_scenario", "15")
    assert 'name="desired_retention"' in html


def test_f4_post_valid_saves_and_redirects(client, engine):
    response = client.post("/settings/study", data=form(desired_retention="85%"), follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].endswith("/settings?saved=study")
    assert stored(engine, "daily_new_cards") == 20
    assert stored(engine, "desired_retention") == pytest.approx(0.85)
    assert stored(engine, "session_split") == {"srs": 12, "drill_or_story": 9, "scenario": 6}
    assert client.get("/settings?saved=study").status_code == 200


def test_f4_invalid_saves_nothing(client, session, engine):
    save_values(session, daily=33, retention=0.8, split={"srs": 13, "drill_or_story": 14, "scenario": 15})
    # daily_new_cards and the split are valid; only the retention is not.
    response = client.post(
        "/settings/study", data=form(daily_new_cards="50", desired_retention="0.99", split_srs="20"), follow_redirects=False
    )
    assert response.status_code == 400
    assert stored(engine, "daily_new_cards") == 33
    assert stored(engine, "desired_retention") == pytest.approx(0.8)
    assert stored(engine, "session_split") == {"srs": 13, "drill_or_story": 14, "scenario": 15}


def test_f4_invalid_form_rerendered_with_typed_values(client, session):
    save_values(session)
    response = client.post(
        "/settings/study", data=form(daily_new_cards="250", desired_retention="85%", split_srs="14"), follow_redirects=False
    )
    assert response.status_code == 400
    html = response.text
    assert has_value(html, "daily_new_cards", "250")
    assert has_value(html, "desired_retention", "85%")
    assert has_value(html, "split_srs", "14")
    assert has_value(html, "split_scenario", "6")


def test_f4_invalid_total_returns_400_and_saves_nothing(client, session, engine):
    save_values(session)
    response = client.post(
        "/settings/study", data=form(split_srs="60", split_drill_or_story="60", split_scenario="60"), follow_redirects=False
    )
    assert response.status_code == 400
    assert stored(engine, "daily_new_cards") == 33
    assert stored(engine, "session_split") == {"srs": 13, "drill_or_story": 14, "scenario": 15}

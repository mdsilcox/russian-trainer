import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.db import MIGRATIONS, migrate
from app.models import Card, CardState, Category, Direction, Mistake, Module, Setting

EXPECTED_TABLES = {
    "settings", "cards", "card_state", "review_log", "stories", "translation_attempts",
    "mistakes", "drill_sets", "drill_answers", "scenarios", "conversations", "messages",
    "sessions", "plan_months", "schema_version",
}


def test_all_tables_created(engine):
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())


def test_migrate_is_idempotent(engine):
    assert migrate(engine) == len(MIGRATIONS)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM schema_version")).scalar() == len(MIGRATIONS)


def test_settings_seeded(session):
    assert session.get(Setting, "trip_date").value == "2027-09-30"
    assert session.get(Setting, "session_split").value["srs"] == 10


def test_wal_and_foreign_keys(engine):
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_cyrillic_round_trip_and_mistake_link(session):
    card = Card(ru="вокзал", ru_stressed="вокза́л", en="railway station", source_module=Module.story)
    session.add(card)
    session.commit()
    session.add(CardState(card_id=card.id))
    session.add(Mistake(module=Module.story, category=Category.case, subcategory="prepositional after на",
                        wrong="на вокзал", right="на вокзале", card_id=card.id))
    session.commit()
    stored = session.get(Card, card.id)
    assert stored.ru_stressed == "вокза́л"


def test_one_state_per_card_direction(session):
    card = Card(ru="ехать", en="to go (by vehicle)")
    session.add(card)
    session.commit()
    session.add(CardState(card_id=card.id, direction=Direction.recognition))
    session.add(CardState(card_id=card.id, direction=Direction.recognition))
    with pytest.raises(IntegrityError):
        session.commit()

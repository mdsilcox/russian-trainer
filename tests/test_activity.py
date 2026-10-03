"""The activity log: sync from source rows, backfill on an old database, and the /activity page."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlmodel import Session as DbSession, select

from app.db import make_engine, migrate
from app.models import Activity, Conversation, InputLog, Message, Scenario, Session
from app.services import activity

DAY = date(2026, 10, 1)
NOON = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def test_orm_insert_and_update_keep_one_row_per_session(session):
    row = Session(date=DAY, started_at=NOON, minutes=0)
    session.add(row)
    session.commit()
    row.minutes, row.completed = 20, True
    session.add(row)
    session.commit()
    found = session.exec(select(Activity).where(Activity.kind == "session")).all()
    assert len(found) == 1 and found[0].minutes == 20 and found[0].detail["completed"] is True


def test_partner_messages_are_not_activity(session):
    scenario = Scenario(slug="t", title="T", setting="s", partner_role="p", persona="p", opening_ru="Привет")
    session.add(scenario)
    session.commit()
    conv = Conversation(scenario_id=scenario.id, level=1, goals_met_json=[])
    session.add(conv)
    session.commit()
    session.add(Message(conversation_id=conv.id, role="partner", content="Привет"))
    session.add(Message(conversation_id=conv.id, role="user", content="Здравствуйте"))
    session.commit()
    assert [a.kind for a in session.exec(select(Activity)).all()] == ["roleplay_turn"]


def test_activity_survives_source_deletion(session):
    row = InputLog(date=DAY, minutes=15, kind="reading")
    session.add(row)
    session.commit()
    session.delete(row)
    session.commit()
    assert len(session.exec(select(Activity)).all()) == 1


def test_backfill_tolerates_missing_source_tables_and_is_idempotent(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version VALUES (5)"))
    migrate(engine)
    with DbSession(engine) as s:
        s.execute(text("DELETE FROM activity"))
        s.add(InputLog(date=DAY, minutes=10, kind="listening"))
        s.commit()
        s.execute(text("DELETE FROM activity"))
        s.execute(text("DROP TABLE IF EXISTS messages"))
        s.commit()
        assert activity.backfill(s) == 1
        assert activity.backfill(s) == 0
    engine.dispose()


def test_activity_page_empty_and_filled(client, session):
    assert "data-activity-day" not in client.get("/activity").text
    today = datetime.now(timezone.utc).astimezone().date()
    session.add(InputLog(date=today, minutes=12.0, kind="watching"))
    session.commit()
    html = client.get("/activity").text
    assert f'data-activity-day="{today.isoformat()}"' in html
    assert "12 min of reading, listening or watching" in html

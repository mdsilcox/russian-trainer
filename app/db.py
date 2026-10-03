"""Engine, sessions and a minimal migration runner.

Migrations are plain functions in MIGRATIONS, applied in order and recorded
in schema_version. Migration 1 creates every table from app.models; later
ones should use explicit ALTER TABLE statements so existing data survives.
"""

import json
from collections.abc import Callable, Iterator

from sqlalchemy import Engine, event, text
from sqlmodel import Session, SQLModel, create_engine

from app import models
from app.config import ROOT, get_config

SEED_PATH = ROOT / "config" / "settings_seed.json"

_engine: Engine | None = None


def _set_pragmas(dbapi_conn, _record) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def make_engine(url: str) -> Engine:
    engine = create_engine(url, connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _set_pragmas)
    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        config = get_config()
        config.data_dir.mkdir(parents=True, exist_ok=True)
        _engine = make_engine(f"sqlite:///{config.db_path}")
    return _engine


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def _initial_schema(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)


def _seed_settings(engine: Engine) -> None:
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    with Session(engine) as session:
        for key, value in seed.items():
            if session.get(models.Setting, key) is None:
                session.add(models.Setting(key=key, value=value))
        session.commit()


def _add_api_usage(engine: Engine) -> None:
    models.ApiUsage.__table__.create(engine, checkfirst=True)


def _add_ai_backend(engine: Engine) -> None:
    """Record which backend served each call; default new installs to the subscription."""
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(api_usage)"))}
        if "backend" not in columns:
            conn.execute(text("ALTER TABLE api_usage ADD COLUMN backend VARCHAR NOT NULL DEFAULT 'api'"))
    with Session(engine) as session:
        if session.get(models.Setting, "ai_backend") is None:
            session.add(models.Setting(key="ai_backend", value="subscription"))
            session.commit()


def _add_mistake_self_correction(engine: Engine) -> None:
    """Self-correct-first feedback: remember whether the learner fixed a mistake themselves."""
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(mistakes)"))}
        if not columns:  # no mistakes table yet; nothing to alter
            return
        if "self_corrected" not in columns:
            conn.execute(text("ALTER TABLE mistakes ADD COLUMN self_corrected BOOLEAN"))
        if "fix_attempts" not in columns:
            conn.execute(text("ALTER TABLE mistakes ADD COLUMN fix_attempts INTEGER NOT NULL DEFAULT 0"))


def _add_medal_awards(engine: Engine) -> None:
    models.MedalAward.__table__.create(engine, checkfirst=True)


def _add_mistake_last_drilled(engine: Engine) -> None:
    """Weakness scoring: mastery needs correct drill answers on separate days."""
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(mistakes)"))}
        if columns and "last_drilled_on" not in columns:
            conn.execute(text("ALTER TABLE mistakes ADD COLUMN last_drilled_on DATE"))



def _add_drill_set_topic(engine: Engine) -> None:
    """Drill generator: sets know their topic, kind (focused/mixed), rule card and completion."""
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(drill_sets)"))}
        if not columns:
            return
        for name, ddl in [
            ("topic", "VARCHAR"),
            ("kind", "VARCHAR NOT NULL DEFAULT 'focused'"),
            ("intro_json", "JSON"),
            ("completed_at", "DATETIME"),
        ]:
            if name not in columns:
                conn.execute(text(f"ALTER TABLE drill_sets ADD COLUMN {name} {ddl}"))



def _add_mistake_topic(engine: Engine) -> None:
    """Drill mistakes record their exact weakness topic."""
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(mistakes)"))}
        if columns and "topic" not in columns:
            conn.execute(text("ALTER TABLE mistakes ADD COLUMN topic VARCHAR"))


def _add_card_kind(engine: Engine) -> None:
    """Card kinds (word/form/stress/chunk); existing multi-word cards become chunks once."""
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(cards)"))}
        if not columns:
            return
        if "kind" not in columns:
            conn.execute(text("ALTER TABLE cards ADD COLUMN kind VARCHAR NOT NULL DEFAULT 'word'"))
            conn.execute(text("UPDATE cards SET kind = 'chunk' WHERE instr(trim(ru), ' ') > 0"))



def _add_phase3_schema(engine: Engine) -> None:
    """Phase 3: scenario details, conversation level and goals, and the input log."""
    models.InputLog.__table__.create(engine, checkfirst=True)
    with engine.begin() as conn:
        for table, cols in {
            "scenarios": [("group", "VARCHAR NOT NULL DEFAULT ''"), ("persona", "VARCHAR NOT NULL DEFAULT ''"),
                          ("opening_ru", "VARCHAR NOT NULL DEFAULT ''"), ("vocab_json", "JSON"),
                          ("sort", "INTEGER NOT NULL DEFAULT 0")],
            "conversations": [("level", "INTEGER NOT NULL DEFAULT 1"), ("goals_met_json", "JSON")],
        }.items():
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if not existing:
                continue
            for name, ddl in cols:
                if name not in existing:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN "{name}" {ddl}'))



def _add_phase4_schema(engine: Engine) -> None:
    """Phase 4: the 12-month plan gets a title, boosted topics and a monthly check-in."""
    with engine.begin() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(plan_months)"))}
        if not existing:
            return
        for name, ddl in [("title", "VARCHAR NOT NULL DEFAULT ''"), ("topics_json", "JSON"), ("review_json", "JSON")]:
            if name not in existing:
                conn.execute(text(f"ALTER TABLE plan_months ADD COLUMN {name} {ddl}"))


MIGRATIONS: list[Callable[[Engine], None]] = [
    _initial_schema,
    _seed_settings,
    _add_api_usage,
    _add_ai_backend,
    _add_mistake_self_correction,
    _add_medal_awards,
    _add_mistake_last_drilled,
    _add_drill_set_topic,
    _add_mistake_topic,
    _add_card_kind,
    _add_phase3_schema,
    _add_phase4_schema,
]


def migrate(engine: Engine | None = None) -> int:
    """Apply pending migrations; returns the resulting schema version."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"))
        current = conn.execute(text("SELECT MAX(version) FROM schema_version")).scalar() or 0
    for version, migration in enumerate(MIGRATIONS, start=1):
        if version > current:
            migration(engine)
            with engine.begin() as conn:
                conn.execute(text("INSERT INTO schema_version (version) VALUES (:v)"), {"v": version})
            current = version
    return current

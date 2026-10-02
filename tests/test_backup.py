import sqlite3
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlmodel import Session

from app.db import make_engine, migrate
from app.models import Card
from app.routes import backup as backup_routes
from app.services import backup as svc


@pytest.fixture
def live_db(tmp_path):
    path = tmp_path / "data" / "russian.db"
    path.parent.mkdir()
    engine = make_engine(f"sqlite:///{path}")
    migrate(engine)
    with Session(engine) as s:
        s.add(Card(ru="привет", en="hello"))
        s.commit()
    yield path, engine
    engine.dispose()


def test_backup_now_copies_card(live_db, tmp_path):
    path, _ = live_db
    dest = svc.backup_now(path, tmp_path / "backups", now=datetime(2026, 3, 5, 9, 0))
    assert dest.name == "russian-2026-03-05.db"
    conn = sqlite3.connect(dest)
    assert conn.execute("SELECT ru FROM cards").fetchall() == [("привет",)]
    conn.close()


def test_backup_overwrites_same_day(live_db, tmp_path):
    path, engine = live_db
    bdir = tmp_path / "backups"
    now = datetime(2026, 3, 5)
    svc.backup_now(path, bdir, now)
    with Session(engine) as s:
        s.add(Card(ru="пока", en="bye"))
        s.commit()
    dest = svc.backup_now(path, bdir, now)
    conn = sqlite3.connect(dest)
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone() == (2,)
    conn.close()
    assert len(list(bdir.iterdir())) == 1


def test_prune_keeps_newest_14(tmp_path):
    bdir = tmp_path / "backups"
    bdir.mkdir()
    for day in range(1, 17):
        (bdir / f"russian-2026-01-{day:02d}.db").write_bytes(b"x")
    (bdir / "notes.txt").write_text("keep me")
    svc.prune_backups(bdir)
    names = sorted(p.name for p in bdir.iterdir())
    assert len(names) == 15
    assert "russian-2026-01-01.db" not in names
    assert "russian-2026-01-02.db" not in names
    assert "russian-2026-01-03.db" in names
    assert "notes.txt" in names
    assert svc.list_backups(bdir)[0].name == "russian-2026-01-16.db"


def test_ensure_daily_backup(live_db, tmp_path):
    path, _ = live_db
    bdir = tmp_path / "backups"
    now = datetime(2026, 3, 5)
    assert svc.ensure_daily_backup(path, bdir, now) is not None
    assert svc.ensure_daily_backup(path, bdir, now) is None  # already done today


def test_ensure_daily_backup_missing_db_and_errors(tmp_path):
    assert svc.ensure_daily_backup(tmp_path / "nope.db", tmp_path / "b") is None
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a database" * 100)
    assert svc.ensure_daily_backup(bad, tmp_path / "b2") is None  # logged, not raised


def test_run_startup_backup_uses_config(live_db, tmp_path, monkeypatch):
    path, _ = live_db
    cfg = SimpleNamespace(db_path=path, backup_dir=tmp_path / "backups")
    monkeypatch.setattr(svc, "get_config", lambda: cfg)
    assert svc.run_startup_backup() is not None
    assert len(svc.list_backups(cfg.backup_dir)) == 1


def _add_tricky_card(session):
    session.add(
        Card(
            ru="молоко",
            ru_stressed="молоко́",
            en="milk\twith tab",
            example_ru="Я пью молоко.",
            example_en="I drink milk.\nSecond line",
            tags="food basics",
        )
    )
    session.commit()


def test_export_csv(session):
    _add_tricky_card(session)
    text = svc.export_cards_csv(session)
    assert text.startswith("﻿ru,ru_stressed,en,")
    assert "молоко́" in text
    assert "food basics" in text
    assert text.rstrip().endswith("manual")


def test_export_anki(session):
    _add_tricky_card(session)
    text = svc.export_anki_tsv(session)
    lines = text.splitlines()
    assert lines[:3] == ["#separator:tab", "#html:true", "#tags column:3"]
    assert len(lines) == 4  # newline in the example did not split the record
    front, back, tags = lines[3].split("\t")
    assert front == "молоко́"
    assert "milk with tab" in back
    assert "I drink milk.<br>Second line" in back
    assert tags == "food basics"


def test_settings_page_and_downloads(client, session, live_db, tmp_path, monkeypatch):
    path, _ = live_db
    cfg = SimpleNamespace(db_path=path, backup_dir=tmp_path / "backups")
    monkeypatch.setattr(backup_routes, "get_config", lambda: cfg)
    _add_tricky_card(session)

    r = client.get("/settings")
    assert r.status_code == 200
    assert "Backup now" in r.text and "2027-09-30" in r.text

    r = client.post("/settings/backup", follow_redirects=False)
    assert r.status_code == 303
    assert len(svc.list_backups(cfg.backup_dir)) == 1
    assert "russian-" in client.get(r.headers["location"]).text

    for url in ("/settings/export/cards.csv", "/settings/export/anki.txt"):
        r = client.get(url)
        assert r.status_code == 200
        assert "attachment" in r.headers["content-disposition"]
        assert datetime.now().strftime("%Y-%m-%d") in r.headers["content-disposition"]
        assert "молоко" in r.content.decode("utf-8")

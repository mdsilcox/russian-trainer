"""Database backups (SQLite online backup API) and card exports.

Backups are named russian-YYYY-MM-DD.db (local date). A second backup on the
same day overwrites the first, so manual "Backup now" always captures the
latest state. Only the newest KEEP_BACKUPS daily files are kept.
"""

import csv
import io
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlmodel import Session, select

from app.config import get_config
from app.models import Card

log = logging.getLogger(__name__)

KEEP_BACKUPS = 14
BACKUP_RE = re.compile(r"^russian-\d{4}-\d{2}-\d{2}\.db$")

CSV_COLUMNS = [
    "ru", "ru_stressed", "en", "example_ru", "example_en",
    "pos", "gender", "aspect", "aspect_partner", "notes", "tags", "source",
]


@dataclass(frozen=True)
class BackupInfo:
    name: str
    size: int
    mtime: datetime


def backup_path(backup_dir: Path, day: date) -> Path:
    return backup_dir / f"russian-{day.isoformat()}.db"


def backup_now(db_path: Path, backup_dir: Path, now: datetime | None = None) -> Path:
    """Copy the live DB to today's backup file and prune old ones."""
    now = now or datetime.now()
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_path(backup_dir, now.date())
    tmp = dest.with_suffix(".db.tmp")
    tmp.unlink(missing_ok=True)
    src_conn = sqlite3.connect(db_path)
    dest_conn = sqlite3.connect(tmp)
    try:
        src_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        src_conn.close()
    tmp.replace(dest)
    prune_backups(backup_dir)
    return dest


def prune_backups(backup_dir: Path, keep: int = KEEP_BACKUPS) -> None:
    """Delete all but the newest `keep` daily backups (by date in the name)."""
    files = sorted(p for p in backup_dir.iterdir() if BACKUP_RE.match(p.name))
    for old in files[:-keep]:
        old.unlink(missing_ok=True)


def ensure_daily_backup(db_path: Path, backup_dir: Path, now: datetime | None = None) -> Path | None:
    """Back up once per day. Never raises: returns None if skipped or failed."""
    try:
        now = now or datetime.now()
        if not db_path.exists() or backup_path(backup_dir, now.date()).exists():
            return None
        return backup_now(db_path, backup_dir, now)
    except Exception:
        log.exception("Daily backup failed")
        return None


def run_startup_backup() -> Path | None:
    """ensure_daily_backup using the app config; call from the lifespan."""
    config = get_config()
    return ensure_daily_backup(config.db_path, config.backup_dir)


def list_backups(backup_dir: Path) -> list[BackupInfo]:
    """Backups newest first."""
    if not backup_dir.is_dir():
        return []
    infos = []
    for p in backup_dir.iterdir():
        if BACKUP_RE.match(p.name):
            st = p.stat()
            infos.append(BackupInfo(p.name, st.st_size, datetime.fromtimestamp(st.st_mtime)))
    return sorted(infos, key=lambda i: i.name, reverse=True)


def _cards(session: Session) -> list[Card]:
    return list(session.exec(select(Card).order_by(Card.id)))


def export_cards_csv(session: Session) -> str:
    """All cards as CSV, with a UTF-8 BOM so Excel shows Cyrillic."""
    out = io.StringIO()
    out.write("﻿")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    for c in _cards(session):
        writer.writerow(
            [
                c.ru, c.ru_stressed or "", c.en, c.example_ru or "", c.example_en or "",
                c.pos or "", c.gender or "", c.aspect or "", c.aspect_partner or "",
                c.notes or "", c.tags, c.source_module.value,
            ]
        )
    return out.getvalue()


def _anki_field(text: str | None) -> str:
    """One Anki field: HTML-escaped, newlines as <br>, no tabs."""
    text = (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("\t", " ").replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\n", "<br>")


def export_anki_tsv(session: Session) -> str:
    """Anki text import: front = Russian (stressed), back = English + example, then tags."""
    lines = ["#separator:tab", "#html:true", "#tags column:3"]
    for c in _cards(session):
        back = _anki_field(c.en)
        if c.example_ru:
            back += "<br><br>" + _anki_field(c.example_ru)
            if c.example_en:
                back += "<br>" + _anki_field(c.example_en)
        tags = " ".join(c.tags.split())
        lines.append("\t".join([_anki_field(c.ru_stressed or c.ru), back, tags]))
    return "\n".join(lines) + "\n"

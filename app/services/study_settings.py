"""Editing the study settings: daily new cards, desired retention and the session split."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlmodel import Session

from app.models import Setting
from app.services import srs, today

SPLIT_FIELDS = {
    "split_srs": "srs",
    "split_drill_or_story": "drill_or_story",
    "split_scenario": "scenario",
}
MAX_NEW_CARDS = 100
MAX_BLOCK_MINUTES = 60
MIN_TOTAL_MINUTES = 5
MAX_TOTAL_MINUTES = 120
MIN_RETENTION = Decimal("0.70")
MAX_RETENTION = Decimal("0.97")

_WHOLE = re.compile(r"[0-9]+")
_NUMBER = re.compile(r"[0-9]+(?:[.,][0-9]*)?|[.,][0-9]+")


@dataclass
class StudySettings:
    daily_new_cards: int
    desired_retention: float
    session_split: dict[str, int]  # keys: srs, drill_or_story, scenario


def load(session: Session) -> StudySettings:
    row = session.get(Setting, "daily_new_cards")
    try:
        daily = int(row.value) if row is not None else srs.DEFAULT_NEW_PER_DAY
    except (TypeError, ValueError):
        daily = srs.DEFAULT_NEW_PER_DAY
    row = session.get(Setting, "desired_retention")
    try:
        retention = float(row.value) if row is not None else srs.DEFAULT_RETENTION
    except (TypeError, ValueError):
        retention = srs.DEFAULT_RETENTION
    return StudySettings(daily, retention, today.session_split(session))


def _whole(raw: str | None, high: int) -> int | None:
    text = (raw or "").strip()
    if not _WHOLE.fullmatch(text):
        return None
    value = int(text)
    return value if value <= high else None


def _retention(raw: str | None) -> float | None:
    text = (raw or "").strip()
    percent = text.endswith("%")
    if percent:
        text = text[:-1].strip()
    if not _NUMBER.fullmatch(text):
        return None
    value = Decimal(text.replace(",", "."))
    if percent or value > 1:
        value = value / 100
    value = value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if not MIN_RETENTION <= value <= MAX_RETENTION:
        return None
    return float(value)


def parse(form: Mapping[str, str]) -> tuple[StudySettings | None, dict[str, str]]:
    errors: dict[str, str] = {}

    daily = _whole(form.get("daily_new_cards"), MAX_NEW_CARDS)
    if daily is None:
        errors["daily_new_cards"] = f"Enter a whole number from 0 to {MAX_NEW_CARDS}."

    retention = _retention(form.get("desired_retention"))
    if retention is None:
        errors["desired_retention"] = "Enter a value from 0.70 to 0.97, or a percentage from 70 to 97."

    split: dict[str, int] = {}
    for field, key in SPLIT_FIELDS.items():
        minutes = _whole(form.get(field), MAX_BLOCK_MINUTES)
        if minutes is None:
            errors[field] = f"Enter a whole number of minutes from 0 to {MAX_BLOCK_MINUTES}."
        else:
            split[key] = minutes
    if len(split) == len(SPLIT_FIELDS):
        total = sum(split.values())
        if not MIN_TOTAL_MINUTES <= total <= MAX_TOTAL_MINUTES:
            errors["session_split"] = (
                f"The three blocks must add up to between {MIN_TOTAL_MINUTES} and {MAX_TOTAL_MINUTES} "
                f"minutes (now {total})."
            )

    if errors:
        return None, errors
    return StudySettings(daily, retention, split), {}


def _upsert(session: Session, key: str, value) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
        session.add(row)


def save(session: Session, settings: StudySettings) -> None:
    _upsert(session, "daily_new_cards", int(settings.daily_new_cards))
    _upsert(session, "desired_retention", float(settings.desired_retention))
    _upsert(session, "session_split", {key: int(settings.session_split[key]) for key in today.DEFAULT_SPLIT})
    session.commit()

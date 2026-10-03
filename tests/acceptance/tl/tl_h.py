"""Helpers shared by the T-L hidden tests (stdlib only at import time)."""

import re
from datetime import date, datetime, timedelta, timezone

D = date(2026, 3, 10)  # a fixed "today" for service tests (a Tuesday)
STRESS = "\u0301"


def noon(day: date) -> datetime:
    from conftest import local_noon

    return local_noon(day)


def real_today() -> date:
    from app.services import stats

    return stats.local_date(datetime.now(timezone.utc))


def location_ok(response, expected: str) -> bool:
    from urllib.parse import urlparse

    u = urlparse(response.headers["location"])
    return u.netloc == "" and u.path == expected


def after(html: str, marker: str) -> str:
    """The page from the first tag carrying `marker` to the end ('' when absent)."""
    i = html.find(marker)
    return html[i:] if i >= 0 else ""


def enrichment(ru="привет", en="hello", **over) -> dict:
    base = {
        "ru_stressed": ru, "en": en, "pos": "noun", "gender": None, "aspect": None, "aspect_partner": None,
        "example_ru": f"Пример со словом {ru}.", "example_en": f"An example with {en}.", "notes": "a note",
        "forms": [], "stress_shift": None,
    }
    return base | over


def input_tag(html: str, name: str) -> str | None:
    """The form control named `name` (its tag, plus the content for a textarea), or None."""
    m = re.search(rf'<(input|textarea|select)[^>]*name="{re.escape(name)}"[^>]*>(?:[^<]*</textarea>)?', html, re.S)
    return m.group(0) if m else None


def make_card(session, ru="слово", en="word", **kw):
    from app.services import cards

    return cards.create_card(session, ru=ru, en=en, **kw)

"""Shared web helpers: the template environment and its filters."""

import re

from markupsafe import Markup, escape

from fastapi.templating import Jinja2Templates

from app.config import ROOT, get_config
from app.services.claude import ai_status
from app.services.grammar import link_for as grammar_link

templates = Jinja2Templates(directory=ROOT / "templates")


def ru(text: str | None) -> Markup:
    """Wrap Russian text so it gets lang="ru" and the Cyrillic font."""
    return Markup('<span lang="ru">{}</span>').format(escape(text or ""))


ACUTE = "́"
_STRESSED = re.compile("(.)" + ACUTE)


def _ink_word(word: str) -> Markup:
    out, pos = [], 0
    for m in _STRESSED.finditer(word):
        out.append(escape(word[pos:m.start()]))
        out.append(Markup('<span class="ink-acc">{}</span>').format(m.group(1)))
        pos = m.end()
    out.append(escape(word[pos:].replace(ACUTE, "")))
    html = Markup("").join(out)
    # Break only between words, never at the hyphen in по-ру́сски.
    return Markup('<span class="ink-w">{}</span>').format(html) if "-" in word else html


def ink_stress(text: str | None) -> Markup:
    """Handwritten Russian: script fonts lack the combining acute, so the browser borrows the
    stressed vowel from another font. Keep the bare vowel in the script and let CSS draw the tick."""
    return Markup(" ").join(_ink_word(w) for w in (text or "").split(" "))


def is_phrase(text: str | None) -> bool:
    return " " in (text or "").strip()


templates.env.filters["ru"] = ru
templates.env.filters["ink_stress"] = ink_stress
templates.env.tests["phrase"] = is_phrase
templates.env.globals["has_api_key"] = lambda: get_config().has_api_key
templates.env.globals["ai_enabled"] = lambda: ai_status()[0]
templates.env.globals["ai_off_reason"] = lambda: ai_status()[1]
templates.env.globals["grammar_link"] = grammar_link


# --- Navigation: one definition for the top menu and the Contents page ----------------------------

NAV_GROUPS = [
    {"key": "learn", "label": "Learn", "ru": "Учёба", "blurb": "New material, one topic at a time.", "items": [
        ("/learn", "Units", "This week's topic: lesson, practice, quiz and revisits."),
        ("/drills", "Drills", "Targeted grammar drills built from your own mistakes."),
        ("/grammar", "Grammar", "The reference: cases, numbers, motion, aspect, stress, pitfalls."),
    ]},
    {"key": "practise", "label": "Practise", "ru": "Пра́ктика", "blurb": "Use what you know: remember it, write it, say it, hear it.", "items": [
        ("/review", "Review", "Your flashcards, due today."),
        ("/workshop", "Writing", "Write or translate stories and correct them yourself first."),
        ("/scenarios", "Speaking", "Role-play conversations from the trip, at three speeds."),
        ("/shelf", "Reading and listening", "Books, shows and podcasts at your level; log the minutes."),
    ]},
    {"key": "progress", "label": "Progress", "ru": "Прогре́сс", "blurb": "Where you are and where you're heading.", "items": [
        ("/plan", "Plan", "Twelve months to Moscow, this month's units and your weekly rhythm."),
        ("/dashboard", "Dashboard", "Trends, forecast, practice heatmap and medals."),
    ]},
    {"key": "library", "label": "Library", "ru": "Библиоте́ка", "blurb": "Your cards, imports and settings.", "items": [
        ("/cards", "Cards", "Browse, add and edit your cards."),
        ("/import", "Import", "Starter deck, frequency deck and pasted word lists."),
        ("/settings", "Settings", "Voice, AI, backups and export."),
    ]},
]


def nav_active(path: str) -> str:
    """The key of the group holding the current page ("today" for the home page, "" for none)."""
    if path == "/":
        return "today"
    if path.startswith("/contents"):
        return "contents"
    for group in NAV_GROUPS:
        if any(path == href or path.startswith(href + "/") for href, _, _ in group["items"]):
            return group["key"]
    return ""


templates.env.globals["NAV_GROUPS"] = NAV_GROUPS
templates.env.globals["nav_active"] = nav_active

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

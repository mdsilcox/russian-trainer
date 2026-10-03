"""Small shared helpers for the T-M hidden tests (public models and HTML text only)."""

import html as html_lib
import re
import unicodedata
from datetime import datetime, time, timedelta, timezone
from html.parser import HTMLParser

STRESS = "́"


def strip_stress(text: str) -> str:
    return unicodedata.normalize("NFC", unicodedata.normalize("NFD", text).replace(STRESS, ""))


def page_text(markup: str) -> str:
    """Visible-ish text of a page: scripts/styles dropped, tags replaced by spaces, whitespace collapsed."""
    markup = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", markup)
    # Inline tags join text without a space (a word wrapped in <button> or <span> stays glued to
    # its punctuation); block-level and other tags separate text.
    inline = r"a|abbr|b|bdi|button|code|em|i|kbd|label|mark|q|s|small|span|strong|sub|sup|time|u"
    markup = re.sub(rf"(?i)</?(?:{inline})(?=[\s/>])[^>]*>", "", markup)
    text = re.sub(r"(?s)<[^>]+>", " ", markup)
    return " ".join(html_lib.unescape(text).split())


class _ElementText(HTMLParser):
    """Collects the text and attributes of the first element carrying a given attribute."""

    VOID = {"br", "img", "input", "hr", "meta", "link", "source", "wbr", "area", "base", "col", "embed"}

    def __init__(self, attr: str):
        super().__init__(convert_charrefs=True)
        self.attr = attr
        self.depth = 0
        self.found = False
        self.done = False
        self.text: list[str] = []
        self.raw_attrs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        if not self.found and any(k == self.attr for k, _ in attrs):
            self.found = True
            self.depth = 1 if tag not in self.VOID else 0
            self.raw_attrs.append(" ".join(f"{k}={v}" for k, v in attrs))
            if not self.depth:
                self.done = True
            return
        if self.found:
            self.raw_attrs.append(" ".join(f"{k}={v}" for k, v in attrs))
            if tag not in self.VOID:
                self.depth += 1

    def handle_endtag(self, tag):
        if self.found and not self.done and tag not in self.VOID:
            self.depth -= 1
            if self.depth <= 0:
                self.done = True

    def handle_data(self, data):
        if self.found and not self.done:
            self.text.append(data)


def element_with_attr(markup: str, attr: str):
    """(text, attribute-values) of the first element having `attr`, or None."""
    p = _ElementText(attr)
    p.feed(markup)
    if not p.found:
        return None
    return " ".join("".join(p.text).split()), " ".join(p.raw_attrs)


def review_front_html(markup: str) -> str:
    """The full HTML of the first element whose class list contains "front" (balanced to its close tag)."""
    starts = [0]
    for line in markup.split("\n"):
        starts.append(starts[-1] + len(line) + 1)

    def offset(pos):
        return starts[pos[0] - 1] + pos[1]

    class Finder(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.tag = None
            self.depth = 0
            self.start = None
            self.end = None

        def handle_starttag(self, tag, attrs):
            if self.end is not None:
                return
            if self.tag is None:
                classes = (dict(attrs).get("class") or "").split()
                if "front" in classes:
                    self.tag, self.depth, self.start = tag, 1, offset(self.getpos())
                return
            if tag == self.tag:
                self.depth += 1

        def handle_startendtag(self, tag, attrs):
            pass

        def handle_endtag(self, tag):
            if self.tag is not None and self.end is None and tag == self.tag:
                self.depth -= 1
                if self.depth == 0:
                    self.end = offset(self.getpos()) + len(f"</{tag}>")

    finder = Finder()
    finder.feed(markup)
    assert finder.start is not None and finder.end is not None, "no element with class front"
    return markup[finder.start:finder.end]


def day_at(day, hour=12, minute=0) -> datetime:
    """UTC datetime for a given local wall-clock time on `day`."""
    return datetime.combine(day, time(hour, minute)).astimezone().astimezone(timezone.utc)


def monday_of(day):
    return day - timedelta(days=day.weekday())

"""Shared web helpers: the template environment and its filters."""

from markupsafe import Markup, escape

from fastapi.templating import Jinja2Templates

from app.config import ROOT, get_config

templates = Jinja2Templates(directory=ROOT / "templates")


def ru(text: str | None) -> Markup:
    """Wrap Russian text so it gets lang="ru" and the Cyrillic font."""
    return Markup('<span lang="ru">{}</span>').format(escape(text or ""))


templates.env.filters["ru"] = ru
templates.env.globals["has_api_key"] = lambda: get_config().has_api_key

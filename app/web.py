"""Shared web helpers: the template environment and its filters."""

from markupsafe import Markup, escape

from fastapi.templating import Jinja2Templates

from app.config import ROOT, get_config
from app.services.claude import ai_status

templates = Jinja2Templates(directory=ROOT / "templates")


def ru(text: str | None) -> Markup:
    """Wrap Russian text so it gets lang="ru" and the Cyrillic font."""
    return Markup('<span lang="ru">{}</span>').format(escape(text or ""))


templates.env.filters["ru"] = ru
templates.env.globals["has_api_key"] = lambda: get_config().has_api_key
templates.env.globals["ai_enabled"] = lambda: ai_status()[0]
templates.env.globals["ai_off_reason"] = lambda: ai_status()[1]

from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session, select

from app.config import get_config
from app.db import get_session
from app.models import Setting
from app.services import backup as backup_service
from app.web import templates

router = APIRouter()

SETTING_LABELS = [
    ("trip_date", "Trip date"),
    ("daily_new_cards", "Daily new cards"),
    ("desired_retention", "Desired retention"),
    ("session_split", "Session split (minutes)"),
    ("api_budget_usd_month", "Monthly API budget (USD)"),
]


def _format_setting(value) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{k} {v}" for k, v in value.items())
    return str(value)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, backed_up: str = "", error: str = "", session: Session = Depends(get_session)):
    config = get_config()
    stored = {s.key: s.value for s in session.exec(select(Setting))}
    rows = [(label, _format_setting(stored[key])) for key, label in SETTING_LABELS if key in stored]
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "settings": rows,
            "backups": backup_service.list_backups(config.backup_dir),
            "backup_dir": config.backup_dir,
            "db_path": config.db_path,
            "keep": backup_service.KEEP_BACKUPS,
            "backed_up": backed_up,
            "error": error,
        },
    )


@router.post("/settings/backup")
def backup_now():
    config = get_config()
    try:
        path = backup_service.backup_now(config.db_path, config.backup_dir)
    except Exception:
        return RedirectResponse("/settings?error=1", status_code=303)
    return RedirectResponse(f"/settings?backed_up={path.name}", status_code=303)


def _download(body: str, media_type: str, filename: str) -> Response:
    return Response(
        body.encode("utf-8"),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/settings/export/cards.csv")
def export_csv(session: Session = Depends(get_session)):
    body = backup_service.export_cards_csv(session)
    return _download(body, "text/csv; charset=utf-8", f"russian-cards-{date.today().isoformat()}.csv")


@router.get("/settings/export/anki.txt")
def export_anki(session: Session = Depends(get_session)):
    body = backup_service.export_anki_tsv(session)
    return _download(body, "text/plain; charset=utf-8", f"russian-anki-{date.today().isoformat()}.txt")

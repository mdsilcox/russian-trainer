from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from app.db import get_session
from app.models import Module
from app.services import frequency as freq
from app.services import starter as svc
from app.services.claude import ClaudeClient, ClaudeError
from app.web import templates

router = APIRouter(prefix="/import")

PASTE = "import"  # pending-file name and card tag for the paste importer


def _redirect(url: str, **query) -> RedirectResponse:
    qs = urlencode({k: v for k, v in query.items() if v})
    return RedirectResponse(f"{url}?{qs}" if qs else url, status_code=303)


@router.get("", response_class=HTMLResponse)
def index(request: Request, added: int = 0, error: str = "", freq_error: str = "", session: Session = Depends(get_session)):
    starter = svc.load_pending().get("topics", {})
    return templates.TemplateResponse(
        request,
        "import/index.html",
        {
            "topics": svc.TOPICS,
            "total": sum(t.count for t in svc.TOPICS),
            "pending_starter": sum(len(v) for v in starter.values()),
            "pending_paste": len(svc.load_pending(PASTE).get("items", [])),
            "added": added,
            "error": error,
            "cap": svc.ENRICH_CAP,
            "freq_start": freq.next_rank(session),
            "freq_size": freq.BATCH_SIZE,
            "freq_pending": len(svc.load_pending(freq.PENDING).get("items", [])),
            "freq_error": freq_error,
        },
    )


# --- Starter deck -------------------------------------------------------------

@router.post("/starter/generate")
async def starter_generate(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    slugs = [s for s in form.getlist("topic") if s in svc.TOPICS_BY_SLUG]
    if not slugs:
        return _redirect("/import", error="Pick at least one topic.")
    pending = svc.load_pending()
    try:
        error = svc.generate_topics(ClaudeClient(session), slugs, pending)
    except ClaudeError as e:
        return _redirect("/import", error=str(e))
    svc.save_pending(pending)
    return _redirect("/import/starter/review", error=error)


@router.post("/starter/regenerate/{slug}")
def starter_regenerate(slug: str, session: Session = Depends(get_session)):
    if slug not in svc.TOPICS_BY_SLUG:
        return _redirect("/import/starter/review")
    pending = svc.load_pending()
    try:
        error = svc.generate_topics(ClaudeClient(session), [slug], pending)
    except ClaudeError as e:
        error = str(e)
    svc.save_pending(pending)
    return _redirect("/import/starter/review", error=error)


@router.get("/starter/review", response_class=HTMLResponse)
def starter_review(request: Request, error: str = "", session: Session = Depends(get_session)):
    topics = svc.load_pending().get("topics", {})
    seen: set[str] = set()
    groups = [
        (t, svc.review_rows(session, topics[t.slug], t.slug, seen))
        for t in svc.TOPICS
        if t.slug in topics
    ]
    return templates.TemplateResponse(request, "import/starter_review.html", {"groups": groups, "error": error})


@router.post("/starter/add")
async def starter_add(request: Request, session: Session = Depends(get_session)):
    topics = svc.load_pending().get("topics", {})
    chosen = (await request.form()).getlist("sel")
    items = []
    for key in chosen:
        slug, _, idx = str(key).partition(":")
        try:
            items.append((topics[slug][int(idx)], f"starter {slug}"))
        except (KeyError, ValueError, IndexError):
            continue
    added = svc.add_cards(session, items, Module.starter)
    svc.clear_pending()
    return _redirect("/import", added=added)


@router.post("/starter/discard")
def starter_discard():
    svc.clear_pending()
    return _redirect("/import")


# --- Frequency deck ------------------------------------------------------------

@router.post("/frequency/generate")
def frequency_generate(session: Session = Depends(get_session)):
    if svc.load_pending(freq.PENDING).get("items"):
        return _redirect("/import/frequency/review")  # finish the staged batch first
    try:
        freq.generate_batch(session, ClaudeClient(session))
    except ClaudeError as e:
        return _redirect("/import", freq_error=str(e))
    return _redirect("/import/frequency/review")


@router.get("/frequency/review", response_class=HTMLResponse)
def frequency_review(request: Request, session: Session = Depends(get_session)):
    pending = svc.load_pending(freq.PENDING)
    rows = svc.review_rows(session, pending.get("items", []), "i", set())
    return templates.TemplateResponse(
        request,
        "import/frequency_review.html",
        {
            "rows": rows,
            "start": pending.get("start"),
            "end": pending.get("end"),
            "skipped": pending.get("skipped", 0),
        },
    )


@router.post("/frequency/add")
async def frequency_add(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    pending = svc.load_pending(freq.PENDING)
    added = freq.add_batch(session, pending, [str(k) for k in form.getlist("sel")], {str(k) for k in form.getlist("form")})
    svc.clear_pending(freq.PENDING)
    return _redirect("/import", added=added)


@router.post("/frequency/discard")
def frequency_discard(session: Session = Depends(get_session)):
    freq.discard_batch(session)
    return _redirect("/import")


# --- Paste a list ---------------------------------------------------------------

@router.post("/paste")
async def paste_parse(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    items, dropped = svc.parse_paste(str(form.get("text", "")))
    if not items:
        return _redirect("/import", error="Nothing to import: paste one word or phrase per line.")
    error = ""
    if form.get("enrich") == "on":
        try:
            error = svc.enrich_items(ClaudeClient(session), items)
        except ClaudeError as e:
            error = str(e)
    svc.save_pending({"items": items, "dropped": dropped}, PASTE)
    return _redirect("/import/paste/review", error=error)


@router.get("/paste/review", response_class=HTMLResponse)
def paste_review(request: Request, error: str = "", session: Session = Depends(get_session)):
    pending = svc.load_pending(PASTE)
    rows = svc.review_rows(session, pending.get("items", []), "i", set())
    return templates.TemplateResponse(
        request,
        "import/paste_review.html",
        {"rows": rows, "dropped": pending.get("dropped", 0), "error": error},
    )


@router.post("/paste/add")
async def paste_add(request: Request, session: Session = Depends(get_session)):
    items = svc.load_pending(PASTE).get("items", [])
    form = await request.form()
    chosen = []
    for key in form.getlist("sel"):
        try:
            item = dict(items[int(str(key).partition(":")[2])])
        except (ValueError, IndexError):
            continue
        item["en"] = str(form.get(f"en_{key}", item.get("en", ""))).strip()
        chosen.append((item, PASTE))
    added = svc.add_cards(session, chosen, Module.manual)
    svc.clear_pending(PASTE)
    return _redirect("/import", added=added)


@router.post("/paste/discard")
def paste_discard():
    svc.clear_pending(PASTE)
    return _redirect("/import")

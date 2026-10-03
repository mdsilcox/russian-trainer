from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from app.config import ROOT, get_config
from app.db import get_engine, migrate
from app.routes import backup, cards, dashboard, drills, grammar, medals, review, scenarios, shelf, starter, today, workshop
from app.services.backup import run_startup_backup
from app.services.claude import load_backend
from app.services.plan import seed as seed_plan
from app.services.scenarios import seed as seed_scenarios


@asynccontextmanager
async def lifespan(_app: FastAPI):
    run_startup_backup()  # before migrating, so the backup holds the pre-migration state
    migrate()
    with Session(get_engine()) as session:
        seed_scenarios(session)
        seed_plan(session)
        load_backend(session)
    yield


app = FastAPI(title="Russian Trainer", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.middleware("http")
async def revalidate(request: Request, call_next):
    """Local app: always revalidate, so pages and CSS are never stale after an update."""
    response = await call_next(request)
    response.headers.setdefault("Cache-Control", "no-cache")
    return response


app.include_router(cards.router)
app.include_router(review.router)
app.include_router(starter.router)
app.include_router(dashboard.router)
app.include_router(backup.router)
app.include_router(workshop.router)
app.include_router(today.router)
app.include_router(grammar.router)
app.include_router(medals.router)
app.include_router(drills.router)
app.include_router(scenarios.router)
app.include_router(shelf.router)


def run() -> None:
    import uvicorn

    config = get_config()
    uvicorn.run("app.main:app", host=config.host, port=config.port, reload=True)

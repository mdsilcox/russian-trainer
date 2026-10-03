from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from app.config import ROOT, get_config
from app.db import get_engine, migrate
from app.routes import activity, backup, cards, cloze, contents, dashboard, drills, grammar, learn, lessons, medals, plan, review, scenarios, shelf, starter, study_settings, today, tts, workshop
from app.routes.learn_play import router as learn_play_router
from app.services.backup import run_startup_backup
from app.services.claude import load_backend
from app.services.plan import seed as seed_plan
from app.services.scenarios import seed as seed_scenarios
from app.services.units import seed_curriculum, start_prefetch_loop


@asynccontextmanager
async def lifespan(_app: FastAPI):
    run_startup_backup()  # before migrating, so the backup holds the pre-migration state
    migrate()
    with Session(get_engine()) as session:
        seed_scenarios(session)
        seed_plan(session)
        seed_curriculum(session)
        load_backend(session)
    start_prefetch_loop()  # prepare the current and next unit's content in the background
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
app.include_router(contents.router)
app.include_router(grammar.router)
app.include_router(medals.router)
app.include_router(drills.router)
app.include_router(scenarios.router)
app.include_router(shelf.router)
app.include_router(plan.router)
app.include_router(cloze.router)
app.include_router(study_settings.router)
app.include_router(activity.router)
app.include_router(lessons.router)
app.include_router(learn.router)
app.include_router(tts.router)
app.include_router(learn_play_router)


def run() -> None:
    import uvicorn

    config = get_config()
    uvicorn.run("app.main:app", host=config.host, port=config.port, reload=True)

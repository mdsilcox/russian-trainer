# Russian Trainer: project context

Personal, single-user, local web app taking an English-speaking B1 learner to conversational Russian before a family trip to Moscow on 2027-09-30. Read this before exploring the code; open only the files a task names.

## Stack and commands
- Python 3.11, FastAPI, SQLModel/SQLite (WAL), Jinja2 + HTMX, small vanilla JS. No frontend build.
- Run: `.venv/Scripts/app` (port 8000). Tests: `.venv/Scripts/python -m pytest -q` (Git Bash; about 370 tests, 15 s). All must pass.
- Throwaway copy for browser checks: set `RT_DATA_DIR` to a scratch folder holding a copy of `data/` and run `.venv/Scripts/python -m uvicorn app.main:app --port 8011`. Restart it after Python changes (no reload).
- Data: `data/russian.db` (gitignored), daily backups in `backups/`. Never touch the real database in tests or experiments.

## Layout
- `app/main.py`: app, lifespan (backup, migrate, load AI backend, seed scenarios), router registration.
- `app/models.py`: all tables. `app/db.py`: hand-rolled migrations, a `MIGRATIONS` list applied in order and recorded in `schema_version`. Add a migration only by appending an idempotent function guarded by `PRAGMA table_info`. In orchestrated phases, schema changes are made up front by the orchestrator, never by lanes.
- `app/web.py`: shared `templates` plus filters `ru` (lang span), `ink_stress`; globals `grammar_link(category, subcategory)`, `ai_enabled()`, `ai_off_reason()`.
- `app/routes/<area>.py` (thin) over `app/services/<area>.py` (logic, tested directly). Templates in `templates/<area>/`, CSS/JS in `static/<area>.css|js`.

## Services (what to call, not what to reread)
- `claude.py`: every Claude call. `ClaudeClient(session).ask_structured(Task.x, system, prompt, PydanticModel, max_tokens=...)` and `.stream_text(Task.x, system, messages)`. Backends: `subscription` (default, `claude -p`, Sonnet, live line streaming) and `api`. Errors: `ClaudeError` (message is safe to show), `ClaudeUnavailable`. Tasks: feedback, roleplay, roleplay_corrections, enrichment, drill_generation, drill_review, answer_check, deck_generation.
- `cards.py`: `create_card(session, kind=None, source_module=..., **fields)` (kinds: word, form, stress, chunk; multi-word becomes chunk), `find_duplicate(session, ru)`, `normalize`, `strip_stress`, `fix_latin_accents`, `apply_stress_marks` (apostrophe after the vowel becomes U+0301), `enrich(client, ru, en="", context="")` returns `CardEnrichment` (stress, meaning, pos, gender, aspect, example, notes, `forms`, `stress_shift`).
- `srs.py`: FSRS scheduling and the review queue. `stats.py`: dashboard numbers, `local_date(now)`, `category_label`.
- `mistakes.py`: the mistake router. `log_mistake(session, RouteResult(), module=, ref_id=, category=, subcategory=, wrong=, right=, explanation=, example_ru=, make_card=True, topic=None)`. Vocabulary categories become cards; grammar categories feed drills. `DRILL_CATEGORIES`, `LOGGED_SEVERITIES`.
- `feedback.py`: story feedback; `Issue` model reused by role-play. `grammar.py`: `link_for(category, subcategory)` to reference anchors. `grammar_content.py`: reference data.
- `weakness.py`: topic scores and mastery. `drills.py`: generator (rule card plus focused set, then mixed sets, reviewed by a second call). `drill_player.py`: answer checking and attempts.
- `roleplay.py`: `start`, `add_learner_turn`, `partner_stream` (generator; saves the reply when done), `review_turn` (corrections and goals), `corrections(msg)`, `hint`, `end`, `debrief` (cached). `scenarios.py`: seed data and `seed()`.
- `plan.py`: the 12-month plan and weekly rhythm. `seed(session, now)` (runs at startup; months from the `trip_date` setting), `months`, `current_month(session, now)`, `month_range(m)`, `progress(session, month)` -> `GoalProgress(text, metric, target, value, done, ratio)`, `expected_ratio(month, now)`, `save_review(session, month, rating, notes, now)`, `review_due(session, now)`; rhythm: `rhythm(session)`, `set_rhythm(session, kinds)`, `day_focus(session, now)` -> `DayFocus(weekday, kind, title, why, href, month_title, topics)`, `DAY_KINDS`, `WEEKDAYS`. `PlanMonth` fields: `month_idx, start_date, title, focus, goals_json [{metric, target, text}], topics_json, status (planned/current/done), review_json`. This month's topics also boost drill selection in `weakness.topic_scores` (`TopicScore.month_focus`).
- `units.py` (guided learning, P5): `seed_curriculum`, `units`, `units_for_month`, `current_unit(session, now)`, `progress(session, unit)`, `state(session, unit, now)` -> `UnitState(unit, status, mastery, steps: [StepState(key, title, why, status locked|available|done|skipped, href, kind, variant, score)], fast_track_offer)`, `get_lesson(session, unit, client=None)` -> `Lesson`, `get_items(session, unit, kind, variant=0, client=None)` -> `(title, items)`, `record_attempt(...)`, `finish_step(session, unit, kind, score, variant=0, now)` -> `FinishResult(kind, score, outcome, message)` (applies pass 80%, remediation under 60%, fast-track at 85%), `fast_track`, `revisits_due`, `today_step(session, now)` -> `TodayStep(unit, step, revisits, why)`, `story_prompt(unit)`. Route conventions are in its docstring. `unit_content.py`: generation and `seed_demo(session)` (hand-written content for `u01-where-you-are`; use it in tests and on the test copy). `exercises.py`: the item models (`ChoiceItem`, `FillItem`, `MatchItem`, `TransformItem`, `BuildItem`, `TranslateItem`, `ListenChoiceItem`, `DictationItem`; union `Item`, `ITEM_TYPES`, `parse_items`).
- `today.py`: daily plan. `shelf.py`: media ladder and input log. `frequency.py`, `starter.py`: staged deck builders (generate, review, then add). `medals.py`, `backup.py`, `workshop.py`.

## UI conventions (Khokhloma Night)
- Tokens in `static/app.css`: `--lacquer` page, `--raised` panels, `--gold`/`--gold-light`/`--gold-line`, `--cinnabar` for fills only (never small text; red text uses `--cinnabar-text`), `--cream`/`--cream-muted` text, `--radius: 0`. Fonts: Cormorant Garamond headings (`--serif`), Manrope body (`--sans`), Marck Script only for the word of the day.
- Page skeleton (copy `templates/drills/index.html`): `{% extends "base.html" %}`, title block "X · Russian Trainer", `{% block head %}` links the page's own CSS/JS, an eyebrow + `h1` with a Russian subtitle. Ornaments: `{% import "_ornaments.html" as orn %}` (`divider`, `sprig`, `berry`, `corners`).
- HTMX partials swap into a stable container; long Claude calls show a loading state (`hx-indicator`, disabled button, "about N seconds") and render `ClaudeError` inline with a retry.
- Motion lives in `static/motion.css|js` inside `prefers-reduced-motion: no-preference`. Speak control: `static/speak.js` (API at the top: `data-speak`, `data-listen-first`, `data-speak-speed`, `window.Speak`).
- Must work at 375px wide with no horizontal scroll. Russian text gets `lang="ru"`.

## Content rules
- No em dashes (—) in English UI text, prompts, comments or docs; use commas, colons or full stops. Russian keeps a dash only where grammar needs it.
- Russian stress: U+0301 after the stressed vowel on every word of 2+ syllables, never on ё or one-syllable words. Claude sometimes writes Latin á/é; pass its output through `fix_latin_accents`.
- Explanations to the learner are in English.
- English is American spelling everywhere (UI, prompts, comments, docs): practice (also the verb), color, center, theater, traveler. `claude.py` appends `SPELLING` to every system prompt.

## Tests
- Fixtures in `tests/conftest.py`: `session`, `client` (TestClient on a per-test database), `engine`.
- Never call real Claude in tests. Fakes: a class with `ask_structured(task, system, prompt, model, max_tokens=...)` returning queued Pydantic objects and `stream_text(...)` yielding chunks (see `tests/test_roleplay.py` FakeClient, `tests/test_drills.py`); monkeypatch `ClaudeClient` in the route module for route tests.
- Inject `now` into services; use `stats.local_date(now)` for days.

## Process
- Orchestrated phases are tracked on the Orchestra board (https://claude.ai/artifact/Eqis6DgyZMefwhzFM1KNta; project id `russian-trainer`, doc prefix `rt~`). The full plan: `.overture/plan.xml` (kept in sync with Overture; see the global instructions). Decisions: `docs/decisions.md`. Research: `docs/research.md`. Orchestration numbers: `docs/orchestration-metrics.md`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Update this file at each phase gate when architecture or conventions change.

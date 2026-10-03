# Decisions (Phase 0)

Answers from plan review, 2026-10-02. Machine-readable copy: `config/settings_seed.json` (loaded into the `settings` table on first run).

| Topic | Decision | Effect on the build |
|---|---|---|
| Trip | 2027-09-30, Moscow, with family | Countdown and the 12 monthly blocks are planned back from this date. Scenarios include family situations (a table for several people, tickets for several people, a family hotel room). |
| Weak areas | Case endings, verbs of motion, real-world phrases, stress placement | Tracked first as categories `case`, `motion_verb`, `idiom`, `stress`. Stress errors always create cards. Drills start with cases and verbs of motion. |
| Daily session | 25 min, balanced: 10 SRS / 8 drill or story / 7 scenario | Default plan on the Today page. |
| Vocab | No existing deck | P1.8 generates a travel starter deck (~150 cards) that you review before it's added. No Anki/CSV importer in the MVP. |
| Past stories | Import them | Story workshop gets a bulk import step (source + your translation), with optional batch feedback so old mistakes seed the deck and drills. |
| Cyrillic input | Phonetic layout (YaWERTY) | No on-screen keyboard needed. Answer checking ignores stress marks and treats ё/е as equal. |
| Explanations | English | Injected into every feedback prompt. |
| API budget | ~$10/month | Sonnet 5.5 for story feedback and role-play, Haiku 4.5 for card enrichment, drill generation and answer checks (mapping in `app/services/claude.py`). Usage and cost logged per call, with a warning at 80% of the budget. |
| Audio | Cloud TTS later | No browser TTS in the MVP. P3.4 adds a cloud TTS provider with its own key from an env var. |
| AI backend | Claude subscription via `claude -p` (added 2026-10-02) | Default backend, switchable to the API key in Settings. Calls count against plan limits, logged with cost 0; only API calls count toward the $10 budget. Personal use only. |

## Tutor (decided 2026-10-02)

| Topic | Decision | Effect on the build |
|---|---|---|
| Who | A friend in Russia, fluent in Russian and English, weekly lessons | She sets a weekly topic, word lists and tasks; lessons are the anchor of the week. |
| Channel | Telegram bot | No hosting: the app on the always-on machine long-polls a private bot (token from `TELEGRAM_BOT_TOKEN`, never stored). Only her Telegram account (allow-listed chat id) can talk to it. A hosted web portal stays an option later if editing long lists in chat gets clunky. |
| Language | Bot speaks Russian (she's fluent in both; it's also good immersion for the learner when reading her messages) | Bot replies and summaries in Russian, app screens in English. |
| Visibility | She can see everything | Weekly summary can include stories with feedback, mistakes and stats; still sent only to her chat. |
| Hosting | The app moves to a dedicated always-on machine (new hardware coming) | Run as a background service that starts on boot; backups copied off that machine; the learner uses it from other devices over the home network. |

## 2026-10-03: Phase 3 built as orchestrated lanes

Phase 3 runs as parallel lanes: the orchestrator (main agent) keeps the role-play engine (prompts and correction pipeline) and the review gate; Sonnet agents take scoped lanes. The orchestrator makes all schema changes up front (migration `_add_phase3_schema`) so lanes never edit `app/db.py` or `app/models.py` in parallel.

| Lane | Owner | Steps | Owns |
|---|---|---|---|
| Engine | Orchestrator | P3.2a | `app/services/roleplay.py`, `tests/test_roleplay.py` |
| A | Sonnet A | P3.1, then P3.2b and P3.3 | `app/services/scenarios.py`, `app/routes/scenarios.py`, `templates/scenarios/*`, `static/scenarios.*`, scenario tests |
| B | Sonnet B | P3.5 | `app/services/shelf.py`, `app/routes/shelf.py`, `templates/shelf/*`, `static/shelf.*`, dashboard input tile, nav link |
| C | Sonnet C | P3.4 | `static/speak.js`, `static/speak.css`, review-card integration |

Each lane step is accepted only after review: tests, diff, a click-through, scores 1-5 for correctness, spec fit, code quality and UX, must-fix issues returned to the same agent. Accepted when no must-fix remains and every score is at least 4.

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

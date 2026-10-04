# Orchestration metrics

How building with an orchestrator plus parallel Sonnet lanes compares with the main agent building alone. Measured on 2026-10-03.

## Phase 3 (orchestrated)

Go at 12:05:16Z, gate closed at 12:25:51Z: **20.6 min wall time**, 3,325 lines added across 40 files, 368 tests passing.

| Step | Owner | Rounds | Agent wall time | Agent tokens | Scores at acceptance (correctness / spec / quality / UX) | Defects caught in review |
|---|---|---|---|---|---|---|
| Shared schema, briefs | Orchestrator | n/a | n/a | n/a | n/a | n/a |
| P3.2a Role-play engine | Orchestrator | n/a | n/a | n/a | live-tested | rambling hint; Latin é in output |
| P3.1 Scenario library | Sonnet A | 1 | 5.1 min | 107k | 5 / 5 / 4 / 5 | none |
| P3.2b Chat UI | Sonnet A | 1 | 3.8 min | 43k | 5 / 5 / 4 / 4 | none (doubled accent traced to the engine) |
| P3.3 Debrief + listening | Sonnet A | 1 | 3.2 min | 36k | 5 / 5 / 4 / 5 | none |
| P3.4 Speak control | Sonnet C | 2 | 3.8 + 1.1 min | 97k | 4 / 5 / 4 / 4 | listen-first toggle didn't apply to the current card |
| P3.5 Media shelf | Sonnet B | 2 | 4.9 + 0.6 min | 130k | 4 / 5 / 4 / 4 (round 1: correctness 3) | mined cards pre-verified stress (must-fix); mined sentence lost when the word form differed |

- Agent tokens: **413k** (Sonnet). Orchestrator tokens: **121k** (Opus), measured as growth of the session's token counter, so it includes briefs, reviews, live tests and the engine.
- Agent time: 22.6 agent-minutes inside 20.6 wall minutes, alongside about 8 minutes of orchestrator engine work.
- Every agent hand-back said its UI was not tested in a browser. Every UI defect above was found by the orchestrator's live checks, not by agent tests.

## Baseline: solo build (P2.1 and P2.2)

The main agent built P2.1 and P2.2 directly: 772 lines in about 10.5 minutes including a live test, about **73 lines/min**.

## Comparison

| | Solo (estimated for Phase 3) | Orchestrated (measured) |
|---|---|---|
| Wall time | about 45-50 min at the solo pace (3,325 lines), more with browser checks | **20.6 min** (about 161 lines/min, 2.2x) |
| Opus tokens | roughly 2x the orchestrated figure (all code written and read by the main agent) | **121k** |
| Total tokens | lower | higher: each agent re-reads the codebase (about 413k Sonnet on top) |
| Defects shipped | depends on discipline; the same live checks would be needed | 7 caught before commit, 0 known shipped |

Caveats: the solo figures are an estimate from Phase 2's pace, not a controlled rerun. The token counters measure context growth, not billed tokens (each tool call re-sends cached context), so treat the ratios as indicative.

## Lessons

- **Speed:** parallel lanes roughly halve wall time when steps are independent; the dependent chain (scenarios, chat, debrief) still runs in sequence.
- **Cost:** total tokens go up (agents rediscover conventions), but most of them move to the cheaper model and the orchestrator's own context stays small, which also keeps it sharp for review.
- **Quality:** comes from the review loop with live checks, not from parallelism. Agents' own tests passed every time while real bugs remained; browser and live-model checks found them.
- **Coordination costs:** do schema changes up front (lanes must never share migrations), expect small shared-file edits (`app/main.py` got two lanes' lines without trouble), and one cross-lane test broke on migration order. Briefs and reviews were roughly a third of the orchestrator's tokens.
- **Where it pays less:** small or tightly coupled work (one step, shared files, prompt design). There the orchestrator should just build it.

## Phase 4 (orchestrated, agents onboarded through CLAUDE.md)

Go at 13:38:41Z, gate closed at 13:49:05Z: **10.4 min wall time**, 1,983 lines added, 416 tests passing. Tracked live on the Orchestra board.

| Step | Owner | Rounds | Agent wall time | Agent tokens | Scores at acceptance | Defects caught |
|---|---|---|---|---|---|---|
| Schema, briefs | Orchestrator | n/a | n/a | n/a | n/a | n/a |
| P4.2a Plan engine | Orchestrator | n/a | n/a | n/a | tested | none |
| P4.1 Dashboard v2 | Sonnet A | 1 | 5.9 min | 107k | 4 / 5 / 4 / 5 | day/days plural |
| P4.2b Plan page | Sonnet B | 2 | 2.7 + 1.3 min | 91k | 5 / 5 / 4 / 5 (round 1: correctness 3) | averaged pace hint hid lagging goals (must-fix); words broken mid-word; station links didn't open their month |
| P4.2c Today rhythm | Sonnet C | 1 | 3.0 min | 101k | 5 / 5 / 4 / 4 | none |

Orchestrator tokens: about 60k (plan, schema, engine, three briefs, reviews, board updates), down from 121k in Phase 3.

### Did the context file help?
- **Fresh agents' first step:** 97k tokens on average (107k, 84k, 101k) against 111k in Phase 3 (107k, 130k, 97k): about 13% lower, short of the 30-50% hoped for. Lane A also spent part of its budget on an unprompted browser check it learned about from CLAUDE.md, so the like-for-like saving is somewhat larger.
- **Quality side effect:** CLAUDE.md documents the throwaway test copy, and one agent used it to verify its own UI for the first time. Every hand-back still needs the orchestrator's live check (it found the pace bug, which tests passed).
- **Next lever:** most of a fresh agent's cost is reading the specific files it edits, which a context file can't remove. Reusing agents across steps (60% cheaper per follow-on step in Phase 3) and pasting exact interfaces into briefs remain the bigger savings. Pre-launch Haiku research for briefs is the next experiment.

### Phase 3 vs Phase 4
| | Phase 3 | Phase 4 |
|---|---|---|
| Lane steps | 6 (3 agent lanes, one with 3 chained steps) | 4 (3 parallel agent lanes) |
| Wall time | 20.6 min | 10.4 min |
| Lines per minute | 161 | 191 |
| Agent tokens | 413k | 299k |
| Orchestrator tokens | 121k | about 60k |
| Defects caught before commit | 7 | 4 |
| Rounds returned | 2 of 7 | 1 of 4 |

## Phase 5 (orchestrated, agents reused from Phase 4)

Contracts committed at 17:05Z, gate closed at 17:22:57Z (22.7 min from the phase's start at 17:00Z): 3,136 lines, 512 tests passing.

| Step | Owner | Rounds | Agent tokens for this step | Defects caught |
|---|---|---|---|---|
| Contracts, engine, generation, prefetch | Orchestrator | n/a | n/a | fast-track bypassed remediation (engine, found live) |
| P5.2 Exercise player | Sonnet A (reused) | 2 | 78k | one-try match wording; listening result hid the Russian; Russian uppercased |
| P5.3 Learn pages | Sonnet B (reused) | 2 | 61k | status pill hid remediation (must-fix); skipped steps offered "Mark as done" |
| P5.4 Listening + Today | Sonnet C (reused) | 1 | 21k | none |

**Reusing agents is the biggest lever measured so far.** The three follow-on steps cost 160k agent tokens in total, against about 300k for three fresh agents (Phase 4's first steps averaged 97k). The smallest step (Today and two templates) cost 21k, roughly a fifth of a fresh agent. The context file helped by about 13%; reuse helped by roughly half on bigger steps and up to 80% on small ones.

## Phase 6 (orchestrated, Lab features, the Lab's hidden tests as acceptance tests)

Approved 18:10Z, contracts committed 18:19:43Z, gate closed about 18:40Z (28 min from the start at 18:12Z): 16 features, 2,425 lines of app code plus 5,285 of tests (285 ported acceptance tests), 973 tests passing.

Tokens, measured afterwards from the session transcripts with `~/.claude/tools/phase_tokens.py` (fresh input plus output, 18:12 to 18:41Z): orchestrator (Opus) 240k, agents (Sonnet) 538k. This is the first phase with a measured orchestrator figure; the agent figure counts cache writes, so it is higher than the task notifications' 397k.

| Step | Owner | Rounds | Agent tokens | Defects caught |
|---|---|---|---|---|
| Contracts; merge the Lab pilot's T-M code (cloze, weekly summary, story stats, settings editor) | Orchestrator | n/a | n/a | 8 hunks needed hand-merging (line endings, the new Contents route) |
| Leeches | Sonnet A | 2 | 108k | Apply silently replaced the card's own notes (must-fix); missing stress mark on the page subtitle |
| Activity log, readers, timeline | Sonnet B | 1 | 130k | none in the app; acceptance-test harness issues fixed by the orchestrator (module-name clash across folders, fixture path) |
| Tutor lessons (7 features) | Sonnet C | 2 | 159k | next lesson's topic missing on Today; ISO dates; squeezed task input |
| Gate | Orchestrator | n/a | n/a | pre-existing: review named the wrong story for mistake cards (fixed with tests) |

**What changed this phase.**
- **Executable specs made lanes one-shot.** With the Lab's hidden tests ported in before launch, every lane came back green on its acceptance suite in its first run. Review rounds were only about UX and data safety, not about missing requirements.
- **Reusing existing code beat rebuilding.** The pilot's T-M code took about 10 minutes to merge and review, against roughly two lanes' worth of tokens (about 200k) to rebuild it.
- **New risks found:**
  - An agent ran `git stash` on the shared working tree. It was restored, but it could have lost the other lanes' work. Briefs now forbid it.
  - The board showed the lanes empty because the orchestrator had estimated start times that fell in the future. Board times are now read from the clock.

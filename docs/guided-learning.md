# Guided learning: design

Status: proposal for review (2026-10-03). Nothing here is built yet.

## Why

The monthly goals ("120 cards, 8 drill sets") measure activity, not learning. The learner learns best with **guided learning**: one clear topic, varied exercises that reinforce exactly that topic, and the topic coming back later for review, with the plan adapting to what needs more time. This design adds that layer on top of what exists (grammar reference, drill generator, cards, stories, role-play, speak control, weakness scores) rather than replacing it.

## Concepts

```
Curriculum ── levels A1 · A2 · B1 · B2 · C1   (tags, for the multi-user future)
  └─ Month block (the 12-month plan, unchanged as the big picture)
       └─ Unit: one topic, about a week          e.g. "Where to: в/на + accusative"
            └─ Steps: learn → practise → produce → check → revisit
```

- A **unit** has one topic (usually one weakness topic, the grammar-section key the app already uses, such as `/grammar/cases#location-direction`), a vocabulary theme (10-15 words that need the topic, e.g. places in the city), a can-do statement ("I can say where I'm going by metro, taxi or on foot"), a level and prerequisites.
- Months group about four units. October's "Cases in everyday speech" becomes: (1) Where you are: в/на + prepositional; (2) Where you're going: в/на + accusative; (3) Things you buy and see: accusative of objects; (4) Consolidation week: mixed practice and a role-play.

## The unit cycle

| Step | What the learner does | Built from |
|---|---|---|
| **Learn** | A short lesson: the rule in plain English, 4-6 examples with audio, a "notice it" moment (spot the pattern in a short text), and the unit's words added as cards | grammar reference content + a generated, reviewed lesson |
| **Practise (controlled)** | Multiple choice, fill-in-the-blank, matching, transformation ("rewrite with куда"), listening: hear a sentence and choose its meaning, dictation: hear and type | the drill generator, extended with new item types |
| **Produce (free)** | Build sentences from tiles, a short story using the unit's words and pattern (with self-correct-first feedback), a mini role-play designed so the goals need the topic | workshop, scenarios |
| **Check** | A 10-12 item mastery quiz mixing formats; pass at 80% | exercise player |
| **Revisit** | Short mixed review sets for the topic at growing intervals after passing: about 3, 7, 21 and 60 days | new topic scheduler |

### A unit week, through the weekly rhythm

The weekly rhythm stays the learner's to edit; the unit supplies the content for each kind of day:

| Day kind | In a unit week |
|---|---|
| grammar | Learn (first day of the unit) or controlled practice |
| writing | the unit's story prompt, using its words and pattern |
| interleaved | controlled practice mixed with revisits of older topics |
| roleplay | the unit's mini role-play |
| translation | translation and transformation items for the topic, plus stress |
| input | listening and dictation items, then something from the shelf |
| light | revisits due today, reviews |

The quiz unlocks once the controlled practice is done (normally around day 5-6). Reviews (cards) stay in block I every day.

## Adapting to the learner

**Topic mastery** (0-1 per topic) combines, with recency weighting:
- quiz score (strongest signal);
- first-try accuracy in the unit's exercises;
- mistakes in free production: stories and role-play map onto topics through the existing weakness scoring;
- revisit results, with decay when a topic hasn't been seen.

**States**: new → learning → passed (quiz ≥ 80%) → secure (two revisits passed) → back to learning if a revisit fails or production mistakes pile up.

**Adaptation rules**
- **Pre-test** (optional, 6 items) at the start of a unit: 85% or more offers to fast-track straight to the quiz, then revisits.
- **Remediation**: a quiz under 60% adds a remediation day: an alternative explanation (a different angle, more examples), extra controlled practice on exactly the missed item types, then a retest. Between 60 and 80%: one more practice day, then retest.
- **Revisits**: a failed revisit resets that topic's interval and flags it; three flagged topics in a month adds a consolidation unit.
- **Weak spots elsewhere**: the existing weakness scores keep pulling other weak topics into interleaved days and revisits, so a unit week never forgets the rest.
- **Pace**: the plan page compares units passed with units planned; if behind, it suggests merging a consolidation week; if ahead, it offers the next month's first unit early.

## Exercise types

One item shape for all types, so one player handles them: `{type, prompt, options?, answer, accepted[], audio_text?, topic, skill, explanation}`.

| Type | New? | Notes |
|---|---|---|
| fill-in-the-blank | exists (drills) | reuse |
| multiple choice | new | 3-4 options, distractors from typical errors (wrong case endings) |
| matching | new | pairs: form to meaning, question to answer |
| transformation | new | "rewrite as where-to", "make it plural" |
| listening comprehension | new | hear (speak control or cloud voice), choose the meaning |
| dictation | new | hear, type; checked like drills (stress and ё ignored) |
| sentence building | new | order word tiles; inflect one tile |
| translation EN → RU | new, short | one sentence, checked by the review call for acceptable variants |
| story, role-play, cards | exist | given unit-specific prompts, goals and words |

Items are generated per unit with the same two-pass approach as drills (generate, then independently re-solve and drop doubtful items), and **cached per unit**, so a unit's content is generated once and reused, which is also what makes a multi-user future affordable.

## Data model (sketch)

- `units`: id, level, month_idx, order, title, topics_json, vocab_theme, can_do, prereqs_json.
- `unit_content`: unit_id, kind (lesson, items, quiz, story_prompt, roleplay), body_json, generated_at, reviewed.
- `unit_progress`: unit_id, status, started_at, pretest_score, quiz_score, passed_at, mastery.
- `exercise_attempts`: unit_id, item_id, type, topic, skill, correct, attempt, at.
- `topic_reviews`: topic, step, due, last_result.

Every table is keyed so adding a `profile_id` later is one migration.

## Screens

- **/learn**: the current unit as a step checklist with progress, the lesson view, the exercise player (generalising the drill player), the quiz; and a unit map by month showing mastery.
- **Today**: the lead block becomes today's unit step ("Unit 2, day 3: listening and dictation"); revisits due appear as a small block.
- **/plan**: each month lists its units with status and mastery instead of only activity goals (activity goals stay as secondary context).

## Building it (Phase 5, as lanes)

| Lane | Owner | Steps |
|---|---|---|
| Engine | Orchestrator | schema; curriculum data for the first two months; lesson and item generation prompts with the review pass; mastery, states, revisit scheduler and adaptation rules |
| A | Sonnet | exercise player with the new item types (multiple choice, matching, transformation, sentence building, translation) and the quiz |
| B | Sonnet | /learn unit page, lesson view, unit map; /plan shows units and mastery |
| C | Sonnet | listening comprehension and dictation (cloud voices from the Voices phase); Today leads with the unit step and shows revisits |
| Gate | Orchestrator | a full unit walked through end to end, including a failed quiz leading to remediation |

Lanes A, B and C start once the engine's contracts (item shape, unit service API) are written; the engine's content work continues in parallel.

## Questions for the learner

1. One unit a week, about 25 minutes a day: the right size?
2. Pre-tests to fast-track known topics: yes, or always do the full unit?
3. Pass mark 80%, remediation under 60%: too strict or about right?
4. Should units replace the monthly activity goals on Today and the plan page, or sit beside them?

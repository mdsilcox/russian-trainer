# Vision: from a personal trainer to an app others can use

Status: brainstorm, parked for later (2026-10-03). Nothing here is planned or built.

## Why

A couple of people have shown interest in using the app. Opening it up means it must work for learners with different levels, goals and schedules, not one B1 learner preparing for a family trip to Moscow.

## What would have to change

| Area | Today | For other learners |
|---|---|---|
| **People** | one learner, one database | profiles, each person's data kept apart; later accounts and sign-in |
| **Starting point** | assumed B1 | a placement test giving a level per skill (grammar, vocabulary, listening, speaking), A1 to C1 |
| **Goals** | a trip date | goal templates (travel, family and heritage, an exam such as the TORFL, work, reading literature), with or without a target date, plus interests that shape scenarios and the shelf |
| **Difficulty** | levels picked by hand | measured per person and adjusted automatically: drill difficulty, role-play level, listening speed, new-card pace |
| **Curriculum** | units for one learner's year | units tagged by level with prerequisites, covering A1 to C1 (the guided-learning design is built for this) |
| **Content quality** | Claude-generated, two-pass review | the same, plus a native-speaker review loop for shared units (the tutor could anchor this) |
| **AI cost** | free through the owner's Claude subscription | the subscription route only works for its owner, so others need API billing or their own key; generated content (units, items, audio) shared and cached across learners keeps the cost per person low |
| **Hosting** | a local machine, then the always-on machine | fine for a few friends on a home network with sign-in; a public product needs proper hosting, privacy and backups per user |
| **Customization** | settings for rhythm, session split, voice | the same per profile, plus explanation language and feedback strictness |

## Staged path

1. **Household**: a few profiles on the always-on machine, with per-profile settings, goals and progress. Shared content cache. Cheap because personal choices are already settings rather than code.
2. **Levels and goals**: placement test, goal templates, adaptive difficulty, curriculum beyond B1.
3. **Hosted product**: only if it takes off: accounts, billing or bring-your-own-key, hosting, privacy.

## Habits to keep now

- Store any personal choice as a setting with today's value as the default.
- Tag new learning content with a level and topic.
- Key new tables so a `profile_id` column can be added in one migration.

from datetime import datetime, timedelta, timezone

import pytest

from app.models import ExerciseAttempt, Setting, Unit
from app.services import plan, unit_content, units
from app.services.claude import Task
from app.services.unit_content import GenItem, GenSet, ItemReview, ItemVerdict, Pair

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)  # a Wednesday in October 2026


@pytest.fixture
def seeded(session):
    row = session.get(Setting, "trip_date") or Setting(key="trip_date", value=None)
    row.value = "2027-09-30"
    session.add(row)
    session.commit()
    plan.seed(session, NOW)
    units.seed_curriculum(session)
    unit_content.seed_demo(session)
    return session


def u1(db):
    return db.get(Unit, "u01-where-you-are")


class FakeClient:
    def __init__(self, gen=None, review=None, lesson=None):
        self.gen, self.review, self.lesson, self.calls = gen, review, lesson, []

    def ask_structured(self, task, system, prompt, model, max_tokens=16000):
        self.calls.append((task, prompt))
        if model is GenSet:
            return self.gen
        if model is ItemReview:
            return self.review or ItemReview(items=[ItemVerdict(index=i, solved="", verdict="ok") for i in range(len(self.gen.items))])
        return self.lesson


def test_curriculum_seeds_two_months_and_current_unit(seeded):
    assert len(units.units_for_month(seeded, 1)) == 4 and len(units.units_for_month(seeded, 2)) == 4
    assert units.current_unit(seeded, NOW).id == "u01-where-you-are"
    units.seed_curriculum(seeded)  # idempotent
    assert len(units.units(seeded)) == 8


def test_demo_content_parses_for_every_set(seeded):
    u = u1(seeded)
    assert units.get_lesson(seeded, u).words
    for kind, variant, n in [("pretest", 0, 6), ("practice", 0, 8), ("practice", 1, 6), ("listening", 0, 4), ("quiz", 0, 10)]:
        assert len(units.get_items(seeded, u, kind, variant)[1]) == n


def test_steps_unlock_in_order(seeded):
    u = u1(seeded)
    status = lambda: {s.title: s.status for s in units.state(seeded, u, NOW).steps}  # noqa: E731
    assert status()["Practise 1"] == "locked" and status()["Quiz"] == "locked"
    units.finish_step(seeded, u, "learn", 1.0, now=NOW)
    assert status()["Practise 1"] == "available" and status()["Listen"] == "available" and status()["Practise 2"] == "locked"
    units.finish_step(seeded, u, "practice", 0.8, 0, NOW)
    assert status()["Write"] == "available" and status()["Speak"] == "available" and status()["Quiz"] == "locked"
    units.finish_step(seeded, u, "practice", 0.8, 1, NOW)
    assert status()["Quiz"] == "available"


def test_fast_track_offer_and_accept(seeded):
    u = u1(seeded)
    assert units.finish_step(seeded, u, "pretest", 0.9, now=NOW).outcome == "fast_track_offered"
    assert units.state(seeded, u, NOW).fast_track_offer
    units.fast_track(seeded, u, NOW)
    st = {s.title: s.status for s in units.state(seeded, u, NOW).steps}
    assert st["Quiz"] == "available" and st["Practise 1"] == "skipped" and st["Learn"] == "skipped"
    other = seeded.get(Unit, "u02-where-to")
    units.finish_step(seeded, other, "pretest", 0.5, now=NOW)
    with pytest.raises(ValueError):
        units.fast_track(seeded, other, NOW)


def test_quiz_outcomes_remediation_retry_and_pass(seeded):
    u = u1(seeded)
    for k, v in [("learn", 0), ("practice", 0), ("practice", 1)]:
        units.finish_step(seeded, u, k, 1.0, v, NOW)
    assert units.finish_step(seeded, u, "quiz", 0.5, 0, NOW).outcome == "remediation"
    avail = [s.title for s in units.state(seeded, u, NOW).steps if s.status == "available"]
    assert "Remediation" in avail and "Quiz" not in avail
    units.finish_step(seeded, u, "remediation", 0.8, 1, NOW)
    assert units.finish_step(seeded, u, "quiz", 0.7, 1, NOW).outcome == "retry_practice"
    titles = {s.title: s.status for s in units.state(seeded, u, NOW).steps}
    assert titles["Practise: one more set"] == "available" and titles["Quiz"] == "locked"
    units.finish_step(seeded, u, "practice", 0.9, 2, NOW)
    result = units.finish_step(seeded, u, "quiz", 0.85, 2, NOW)
    assert result.outcome == "passed" and units.progress(seeded, u).status == "passed"
    assert units.current_unit(seeded, NOW).id == "u02-where-to"


def test_revisits_ladder_secure_and_failure(seeded):
    u = u1(seeded)
    units.finish_step(seeded, u, "quiz", 0.9, 0, NOW)
    assert units.revisits_due(seeded, NOW) == []
    day3 = NOW + timedelta(days=3)
    assert [x.id for x in units.revisits_due(seeded, day3)] == [u.id]
    assert units.finish_step(seeded, u, "revisit", 0.8, 0, day3).outcome == "revisit_passed"
    assert units.revisits_due(seeded, day3) == []  # next in 7 days
    day10 = day3 + timedelta(days=7)
    units.finish_step(seeded, u, "revisit", 0.9, 1, day10)
    assert units.progress(seeded, u).status == "secure"
    day31 = day10 + timedelta(days=21)
    assert units.finish_step(seeded, u, "revisit", 0.4, 2, day31).outcome == "revisit_failed"
    assert units.progress(seeded, u).status == "passed"
    assert [x.id for x in units.revisits_due(seeded, day31 + timedelta(days=3))] == [u.id]


def test_mastery_blends_quiz_practice_and_revisits(seeded):
    u = u1(seeded)
    _, items = units.get_items(seeded, u, "practice", 0)
    for i, item in enumerate(items[:4]):
        units.record_attempt(seeded, u, "practice", 0, item, "x", correct=i < 2, now=NOW)
    units.finish_step(seeded, u, "quiz", 1.0, 0, NOW)
    assert units.mastery(seeded, u) == pytest.approx((0.5 * 1.0 + 0.3 * 0.5) / 0.8, abs=0.001)


def test_today_step_follows_the_rhythm(seeded):
    plan.set_rhythm(seeded, ["grammar"] * 7)
    ts = units.today_step(seeded, NOW)
    assert ts.unit.id == "u01-where-you-are" and ts.step.key == "learn"
    plan.set_rhythm(seeded, ["light"] * 7)
    assert units.today_step(seeded, NOW).step is None


# --- Generation (Claude faked) ------------------------------------------------------------------

def gen_set():
    return GenSet(title="Practice", items=[
        GenItem(type="choice", question_ru="Я е́ду ___.", options=["в Москву́", "в Москве́"], answer_index=0, explanation="direction"),
        GenItem(type="fill", prompt_ru="Мы идём в ___.", cue="парк", translation_en="We are going to the park.", answer="парк", explanation="acc"),
        GenItem(type="fill", prompt_ru="No blank here.", cue="x", answer="y", explanation="bad"),  # invalid: no ___
        GenItem(type="build", meaning_en="To the station.", tiles=["На", "вокза́л."], answer="На вокза́л.", explanation="na"),
        GenItem(type="build", meaning_en="Mismatch.", tiles=["На", "ры́нок."], answer="В парк.", explanation="bad"),  # invalid
        GenItem(type="match", pairs=[Pair(left="a", right="b"), Pair(left="c", right="d"), Pair(left="e", right="f")], explanation="m"),
        GenItem(type="translate", en="I'm going to the theatre.", answer="Я иду́ в теа́тр.", explanation="acc"),
        GenItem(type="transform", source_ru="Я в музе́е.", task="Say you're going there.", answer="Я иду́ в музе́й.", explanation="acc"),
        GenItem(type="dictation", audio_ru="Мы е́дем на вокза́л.", translation_en="We're going to the station.", explanation="na"),
    ])


def test_generate_items_validates_reviews_and_fixes(seeded):
    u = seeded.get(Unit, "u02-where-to")
    # The reviewer sees the 7 items left after validation: choice, fill, build, match, translate, transform, dictation.
    review = ItemReview(items=[
        ItemVerdict(index=0, solved="в Москве́", verdict="fix", answer="в Москве́"),  # repoints the choice
        ItemVerdict(index=1, solved="", verdict="drop"),
        ItemVerdict(index=2, solved="", verdict="ok"),
        ItemVerdict(index=3, solved="", verdict="ok"),
        ItemVerdict(index=4, solved="Я в теа́тр иду́.", verdict="fix", answer="Я иду́ в теа́тр.", accepted=["Я в теа́тр иду́."]),
        ItemVerdict(index=5, solved="", verdict="ok"),
        ItemVerdict(index=6, solved="", verdict="ok"),
    ])
    client = FakeClient(gen_set(), review)
    item_set = unit_content.generate_items(seeded, u, "practice", 0, client)
    types = [i.type for i in item_set.items]
    assert types == ["choice", "build", "match", "translate", "transform", "dictation"]  # 2 invalid, 1 dropped
    assert item_set.items[0].answer_index == 1
    assert item_set.items[3].accepted == ["Я в теа́тр иду́."]
    assert all(i.topic == u.topics_json[0] for i in item_set.items)
    assert [t for t, _ in client.calls] == [Task.drill_generation, Task.drill_review]


def test_generated_sets_are_cached_and_remediation_uses_mistakes(seeded):
    u = seeded.get(Unit, "u02-where-to")
    seeded.add(ExerciseAttempt(unit_id=u.id, kind="quiz", item_id="q1", item_type="fill", answer="в Москве", correct=False))
    seeded.commit()
    client = FakeClient(gen_set())
    units.get_items(seeded, u, "remediation", 1, client)
    assert "«в Москве»" in client.calls[0][1] and "variant 2" in client.calls[0][1]
    calls = len(client.calls)
    units.get_items(seeded, u, "remediation", 1, client)
    assert len(client.calls) == calls  # cached


def test_too_few_items_after_review_raises(seeded):
    from app.services.drills import NotEnoughItems
    u = seeded.get(Unit, "u02-where-to")
    review = ItemReview(items=[ItemVerdict(index=i, solved="", verdict="drop") for i in range(9)])
    with pytest.raises(NotEnoughItems):
        unit_content.generate_items(seeded, u, "quiz", 0, FakeClient(gen_set(), review))


def test_lesson_generation_fixes_latin_accents(seeded):
    u = seeded.get(Unit, "u02-where-to")
    lesson = units.Lesson(title="T", intro="i", rule_points=["r"], examples=[units.Example(ru="Я иду в музéй.", en="e")],
                          notice_ru="n", notice_task="t", words=[units.Example(ru="кафé", en="cafe")])
    out = unit_content.generate_lesson(seeded, u, FakeClient(lesson=lesson))
    assert out.examples[0].ru == "Я иду в музе́й." and out.words[0].ru == "кафе́"


def test_prefetch_prepares_only_missing_sets(seeded):
    u2 = seeded.get(Unit, "u02-where-to")
    calls = []
    lesson = units.Lesson(title="T", intro="i", rule_points=["r"], examples=[], notice_ru="n", notice_task="t", words=[])

    class Client(FakeClient):
        def ask_structured(self, task, system, prompt, model, max_tokens=16000):
            calls.append(model.__name__)
            return super().ask_structured(task, system, prompt, model, max_tokens)

    big = GenSet(title="Set", items=gen_set().items * 2)  # enough valid items for a quiz
    client = Client(big, None, lesson)
    assert units.prefetch(seeded, u1(seeded), client) == 0  # demo unit is fully cached
    made = units.prefetch_upcoming(seeded, NOW, client)  # current is u01 (cached), next is u02
    assert made == 6 and calls.count("Lesson") == 1
    assert units.prefetch(seeded, u2, client) == 0


def test_fast_tracked_unit_still_goes_through_remediation(seeded):
    u = u1(seeded)
    units.finish_step(seeded, u, "pretest", 1.0, now=NOW)
    units.fast_track(seeded, u, NOW)
    assert units.finish_step(seeded, u, "quiz", 0.3, 0, NOW).outcome == "remediation"
    st = {s.title: s.status for s in units.state(seeded, u, NOW).steps}
    assert st["Remediation"] == "available" and st["Quiz"] == "locked"
    units.finish_step(seeded, u, "remediation", 0.9, 1, NOW)
    assert {s.title: s.status for s in units.state(seeded, u, NOW).steps}["Quiz"] == "available"

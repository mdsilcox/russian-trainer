from datetime import datetime, timedelta, timezone

import pytest

from app.models import Category, DrillAnswer, Mistake, Module
from app.services import drills, weakness
from app.services.claude import Task
from app.services.drills import DrillItem, GeneratedSet, Review, ReviewedItem, RuleCard, Example

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
GEN_PL = "/grammar/cases#genitive-plural"


class FakeClient:
    """Returns queued responses per task and records the prompts it was sent."""

    def __init__(self, generated: GeneratedSet, review: Review | None = None):
        self.generated, self.review = generated, review
        self.calls: list[tuple[Task, str]] = []

    def ask_structured(self, task, system, prompt, model):
        self.calls.append((task, prompt))
        if task == Task.drill_generation:
            return self.generated
        n = len(self.generated.items)
        return self.review or Review(items=[ReviewedItem(index=i, solved="x", verdict="ok", answer="x", accepted=[], note="")
                                            for i in range(n)])


def item(answer="рубле́й", topic_index=0, prompt="Биле́т сто́ит пять ___.", fmt="numeral"):
    return DrillItem(format=fmt, prompt_ru=prompt, cue="5, рубль", translation_en="The ticket costs five roubles.",
                     answer=answer, accepted=[], rule="5+ takes genitive plural", topic_index=topic_index)


def card():
    return RuleCard(title="Genitive plural", rule="After 5+ and много, nouns take the genitive plural.",
                    examples=[Example(ru="пять рубле́й", en="five roubles")])


def add_mistake(db, sub="genitive plural", category=Category.case):
    m = Mistake(module=Module.story, category=category, subcategory=sub, wrong="рублей", right="рубля́",
                explanation="2-4 take genitive singular", created_at=NOW)
    db.add(m)
    db.commit()
    return m


def top_topic(db, topic=GEN_PL):
    return next(t for t in weakness.topic_scores(db, NOW) if t.topic == topic)


def test_focused_set_has_rule_card_seeds_and_reviewed_items(session):
    m = add_mistake(session)
    gen = GeneratedSet(rule_card=card(), items=[item(), item("книг", prompt="Здесь мно́го ___."), item(), item(), item(),
                                                item(prompt="no blank here"), item(prompt="two ___ blanks ___")])
    review = Review(items=[
        ReviewedItem(index=0, solved="рубле́й", verdict="ok", answer="рубле́й", accepted=[], note=""),
        ReviewedItem(index=1, solved="книг", verdict="fix", answer="книг", accepted=["книжек"], note="colloquial alt"),
        ReviewedItem(index=2, solved="?", verdict="drop", answer="", accepted=[], note="ambiguous"),
        ReviewedItem(index=3, solved="рубле́й", verdict="ok", answer="рубле́й", accepted=[], note=""),
        ReviewedItem(index=4, solved="рубле́й", verdict="ok", answer="рубле́й", accepted=[], note=""),
    ])
    client = FakeClient(gen, review)
    ds = drills.generate_focused(session, client, top_topic(session))

    assert [t for t, _ in client.calls] == [Task.drill_generation, Task.drill_review]
    prompt = client.calls[0][1]
    assert "FOCUSED" in prompt and "«рублей»" in prompt and "«рубля́»" in prompt
    assert "Review these 5 items" in client.calls[1][1]  # malformed blanks never reach review

    assert ds.kind == "focused" and ds.topic == GEN_PL and ds.completed_at is None
    assert ds.intro_json["title"] == "Genitive plural" and ds.intro_json["reference"] == GEN_PL
    assert len(ds.items_json) == 4
    assert ds.items_json[1]["accepted"] == ["книжек"]
    assert all(it["topic"] == GEN_PL and it["topic_label"] == "Genitive plural" for it in ds.items_json)
    assert ds.from_mistake_ids == [m.id]


def test_too_few_items_after_review_raises(session):
    gen = GeneratedSet(rule_card=card(), items=[item() for _ in range(5)])
    review = Review(items=[ReviewedItem(index=i, solved="", verdict="drop", answer="", accepted=[], note="")
                           for i in range(5)])
    with pytest.raises(drills.NotEnoughItems):
        drills.generate_focused(session, FakeClient(gen, review), top_topic(session))


def test_mixed_set_tags_and_interleaves_topics(session):
    topics = weakness.pick_topics(session, NOW, n=3)
    gen = GeneratedSet(rule_card=None, items=[item(topic_index=i % 3) for i in range(9)] + [item(topic_index=7)])
    ds = drills.generate_mixed(session, FakeClient(gen), topics, seed=1)
    assert ds.kind == "mixed" and ds.intro_json is None and ds.topic is None
    assert len(ds.items_json) == 9  # out-of-range topic_index dropped
    seq = [it["topic"] for it in ds.items_json]
    assert set(seq) == {t.topic for t in topics}
    assert all(a != b for a, b in zip(seq, seq[1:]))


def test_plan_moves_from_focused_to_mixed(session):
    kind, topics = drills.plan_next(session, NOW)
    assert kind == "focused" and topics[0].high_yield  # no history: start on a high-yield topic

    first = topics[0]
    ds = drills.generate_focused(session, FakeClient(GeneratedSet(rule_card=card(), items=[item()] * 5)), first)
    drills.complete_set(session, ds, NOW)
    kind, topics = drills.plan_next(session, NOW)
    assert kind == "focused" and topics[0].topic != first.topic  # one taught topic isn't enough to mix

    ds2 = drills.generate_focused(session, FakeClient(GeneratedSet(rule_card=card(), items=[item()] * 5)), topics[0])
    drills.complete_set(session, ds2, NOW)
    add_mistake(session)  # make a taught topic the weakest again
    for _ in range(3):
        add_mistake(session, sub="prepositional after в")
    kind, topics = drills.plan_next(session, NOW)
    assert drills.introduced_topics(session) == {first.topic, ds2.topic}
    if topics[0].topic in drills.introduced_topics(session):
        assert kind == "mixed" and len(topics) == 2


def test_next_set_reuses_the_open_set(session):
    ds = drills.generate_focused(session, FakeClient(GeneratedSet(rule_card=card(), items=[item()] * 5)), top_topic(session))

    class Boom:
        def ask_structured(self, *a):
            raise AssertionError("should not generate")

    assert drills.next_set(session, Boom(), NOW).id == ds.id


def test_mixed_successes_credit_each_items_topic(session):
    add_mistake(session, category=Category.aspect, sub="perfective for completed action")
    topics = [top_topic(session, "/grammar/aspect#aspect-choose"), top_topic(session)]
    gen = GeneratedSet(rule_card=None, items=[item(topic_index=0), item(topic_index=1), item(topic_index=0), item(topic_index=1)])
    ds = drills.generate_mixed(session, FakeClient(gen), topics, seed=0)
    for idx, it in enumerate(ds.items_json):
        if it["topic"] == "/grammar/aspect#aspect-choose":
            session.add(DrillAnswer(drill_set_id=ds.id, item_idx=idx, answer="x", correct=True, created_at=NOW))
    session.commit()
    s = {t.topic: t for t in weakness.topic_scores(session, NOW + timedelta(minutes=1))}
    assert s["/grammar/aspect#aspect-choose"].success_weight > 0.99
    assert s[GEN_PL].success_weight == 0

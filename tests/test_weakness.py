from datetime import datetime, timedelta, timezone

from app.models import Category, DrillAnswer, DrillSet, Mistake, Module
from app.services import weakness
from app.services.weakness import HIGH_YIELD_PRIOR, topic_scores

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
GEN_PL = "/grammar/cases#genitive-plural"
ASPECT = "/grammar/aspect#aspect-choose"


def add_mistake(db, category=Category.case, sub="genitive plural", days_ago=0, **kw):
    m = Mistake(module=Module.story, category=category, subcategory=sub, wrong="x", right="y",
                created_at=NOW - timedelta(days=days_ago), **kw)
    db.add(m)
    db.commit()
    return m


def add_success(db, category=Category.case, sub="genitive plural", days_ago=0, n=1):
    ds = DrillSet(category=category, subcategory=sub, items_json=[])
    db.add(ds)
    db.flush()
    for i in range(n):
        db.add(DrillAnswer(drill_set_id=ds.id, item_idx=i, answer="a", correct=True,
                           created_at=NOW - timedelta(days=days_ago)))
    db.commit()


def scores(db):
    return {t.topic: t for t in topic_scores(db, NOW)}


def test_no_history_starts_on_high_yield_topics(session):
    picked = weakness.pick_topics(session, NOW, n=20)
    assert picked and all(t.high_yield for t in picked)
    assert {t.score for t in picked} == {HIGH_YIELD_PRIOR}


def test_free_text_subcategories_share_a_topic(session):
    add_mistake(session, sub="genitive plural of masculine nouns")
    add_mistake(session, sub="gen. pl. of feminine nouns")
    t = scores(session)[GEN_PL]
    assert len(t.mistake_ids) == 2
    assert t.label == "Genitive plural"
    assert t.subcategories == ["gen. pl. of feminine nouns", "genitive plural of masculine nouns"]  # newest first


def test_recent_mistakes_weigh_more(session):
    add_mistake(session, category=Category.aspect, sub="perfective for completed action", days_ago=0)
    add_mistake(session, category=Category.aspect, sub="aspect pair formation", days_ago=28)
    s = scores(session)
    assert abs(s[ASPECT].mistake_weight - 1.0) < 1e-6
    assert abs(s["/grammar/aspect#aspect-pairs"].mistake_weight - 0.25) < 1e-6  # two half-lives


def test_high_yield_boost_outranks_equal_history(session):
    add_mistake(session, sub="genitive plural")
    add_mistake(session, category=Category.aspect, sub="perfective for completed action")
    ranked = [t.topic for t in topic_scores(session, NOW)]
    assert ranked.index(GEN_PL) < ranked.index(ASPECT)


def test_drill_successes_reduce_score_but_not_below_zero(session):
    add_mistake(session, category=Category.aspect, sub="perfective for completed action")
    add_success(session, category=Category.aspect, sub="choosing perfective", n=1)
    assert abs(scores(session)[ASPECT].score - 0.5) < 1e-6
    add_success(session, category=Category.aspect, sub="choosing perfective", n=5)
    assert scores(session)[ASPECT].score == 0
    assert ASPECT not in [t.topic for t in weakness.pick_topics(session, NOW, n=50)]


def test_old_successes_are_ignored(session):
    add_mistake(session, category=Category.aspect, sub="perfective for completed action")
    add_success(session, category=Category.aspect, sub="choosing perfective", days_ago=90, n=5)
    assert abs(scores(session)[ASPECT].score - 1.0) < 1e-6


def test_mastered_self_corrected_and_vocab_mistakes(session):
    add_mistake(session, category=Category.aspect, sub="perfective", mastered=True)
    assert ASPECT not in scores(session)
    add_mistake(session, category=Category.aspect, sub="perfective", self_corrected=True)
    assert abs(scores(session)[ASPECT].mistake_weight - weakness.SELF_CORRECTED_WEIGHT) < 1e-6
    add_mistake(session, category=Category.word_choice, sub="знать vs уметь")
    assert "/grammar/pitfalls#pitfall-know-can" not in scores(session)  # vocabulary goes to cards, not drills


def test_mastery_needs_separate_days_and_resets_on_a_miss(session):
    m = add_mistake(session)
    weakness.record_drill_answer(session, m, True, NOW)
    weakness.record_drill_answer(session, m, True, NOW + timedelta(hours=1))  # same day: no credit
    assert m.drilled_count == 1 and not m.mastered
    weakness.record_drill_answer(session, m, True, NOW + timedelta(days=1))
    weakness.record_drill_answer(session, m, False, NOW + timedelta(days=2))
    assert m.drilled_count == 0
    for day in (3, 4, 5):
        weakness.record_drill_answer(session, m, True, NOW + timedelta(days=day))
    assert m.mastered and m.drilled_count == 3
    assert not scores(session)[GEN_PL].mistake_ids


def test_preposition_topic_label(session):
    add_mistake(session, category=Category.preposition, sub="без + genitive")
    t = scores(session)["/grammar/cases#prep-bez"]
    assert t.label == "Preposition без" and not t.high_yield

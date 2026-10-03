from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from app.models import Category, DrillAnswer, DrillSet, Mistake, Module
from app.services import drill_player, drills, weakness
from app.services.claude import ClaudeError

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
GEN_PL = "/grammar/cases#genitive-plural"


def make_item(answer="рубле́й", accepted=(), topic=GEN_PL, label="Genitive plural", prompt="Биле́т сто́ит пять ___."):
    return {"format": "numeral", "prompt_ru": prompt, "cue": "рубль", "translation_en": "The ticket costs five roubles.",
            "answer": answer, "accepted": list(accepted), "rule": "5+ takes genitive plural", "topic": topic,
            "topic_label": label, "category": "case"}


def make_set(db, items=None, kind="focused", seeds=(), intro=True):
    ds = DrillSet(category=Category.case, subcategory="genitive plural", topic=GEN_PL, kind=kind,
                  items_json=items or [make_item(), make_item("книг", prompt="Здесь мно́го ___.")],
                  from_mistake_ids=list(seeds),
                  intro_json={"title": "Genitive plural", "rule": "After 5+ use the genitive plural.",
                              "examples": [{"ru": "пять рубле́й", "en": "five roubles"}]} if intro else None)
    db.add(ds)
    db.commit()
    db.refresh(ds)
    return ds


def seed_mistake(db):
    m = Mistake(module=Module.story, category=Category.case, subcategory="genitive plural", wrong="рублей", right="рубле́й",
                topic=GEN_PL, created_at=NOW)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


# --- checking -------------------------------------------------------------------


@pytest.mark.parametrize("answer", ["рублей", "рубле́й", "РУБЛЕЙ", "  рублей. ", "«рублей»", "рублéй", "рубле́й"])
def test_check_accepts_variants(answer):
    assert drill_player.check(make_item(), answer)


def test_check_yo_and_accepted_alternatives_and_spaces():
    item = make_item("всё", accepted=["все́ это"])
    assert drill_player.check(item, "все")
    assert drill_player.check(item, "ВСЕ  ЭТО!")
    assert not drill_player.check(item, "это")


@pytest.mark.parametrize("answer", ["", "   ", "...", "рубля"])
def test_check_rejects_empty_and_wrong(answer):
    assert not drill_player.check(make_item(), answer)


# --- attempts -------------------------------------------------------------------


def test_first_try_correct_credits_matching_seeds_only(session):
    match = seed_mistake(session)
    other = Mistake(module=Module.story, category=Category.aspect, subcategory="x", wrong="a", right="b", created_at=NOW)
    session.add(other)
    session.commit()
    ds = make_set(session, seeds=[match.id, other.id])
    r = drill_player.submit(session, ds, 0, "рублей", 1, NOW)
    assert r.correct and r.final and r.credited and r.sentence == "Биле́т сто́ит пять рубле́й."
    session.refresh(match), session.refresh(other)
    assert match.drilled_count == 1 and other.drilled_count == 0
    row = session.exec(select(DrillAnswer)).one()
    assert row.correct and row.item_idx == 0


def test_seed_topic_derived_from_category_when_mistake_has_none(session):
    m = Mistake(module=Module.story, category=Category.case, subcategory="genitive plural", wrong="a", right="b", created_at=NOW)
    session.add(m)
    session.commit()
    assert weakness.topic_for(m.category, m.subcategory) == GEN_PL
    ds = make_set(session, seeds=[m.id])
    drill_player.submit(session, ds, 0, "рублей", 1, NOW)
    session.refresh(m)
    assert m.drilled_count == 1


def test_first_try_wrong_is_not_final_and_stores_nothing(session):
    ds = make_set(session)
    r = drill_player.submit(session, ds, 0, "рубля", 1, NOW)
    assert not r.correct and not r.final and r.topic == GEN_PL and r.topic_label == "Genitive plural"
    assert session.exec(select(DrillAnswer)).all() == []
    assert session.exec(select(Mistake)).all() == []


def test_second_try_correct_has_no_mastery_credit(session):
    m = seed_mistake(session)
    ds = make_set(session, seeds=[m.id])
    drill_player.submit(session, ds, 0, "рубля", 1, NOW)
    r = drill_player.submit(session, ds, 0, "рублей", 2, NOW)
    assert r.correct and r.final and not r.credited
    session.refresh(m)
    assert m.drilled_count == 0
    assert session.exec(select(DrillAnswer)).one().correct
    assert session.exec(select(Mistake).where(Mistake.module == Module.drill)).all() == []


def test_second_try_wrong_logs_mistake_and_resets_mastery(session):
    m = seed_mistake(session)
    m.drilled_count = 2
    session.add(m)
    session.commit()
    ds = make_set(session, seeds=[m.id])
    r = drill_player.submit(session, ds, 0, "рубля", 2, NOW)
    assert not r.correct and r.final and r.answer == "рубле́й" and r.rule == "5+ takes genitive plural"
    assert not session.exec(select(DrillAnswer)).one().correct
    logged = session.exec(select(Mistake).where(Mistake.module == Module.drill)).one()
    assert (logged.ref_id, logged.category, logged.subcategory) == (ds.id, Category.case, "Genitive plural")
    assert (logged.wrong, logged.right, logged.topic, logged.card_id) == ("рубля", "рубле́й", GEN_PL, None)
    assert logged.explanation == "5+ takes genitive plural"
    session.refresh(m)
    assert m.drilled_count == 0


def test_empty_answer_is_never_an_attempt(session):
    ds = make_set(session)
    for attempt in (1, 2):
        r = drill_player.submit(session, ds, 0, "  ", attempt, NOW)
        assert r.empty and not r.final and not r.correct
    assert session.exec(select(DrillAnswer)).all() == []
    assert session.exec(select(Mistake)).all() == []


def test_resubmitting_a_final_item_changes_nothing(session):
    m = seed_mistake(session)
    ds = make_set(session, seeds=[m.id])
    drill_player.submit(session, ds, 0, "рублей", 1, NOW)
    r = drill_player.submit(session, ds, 0, "рублей", 1, NOW + timedelta(days=1))
    assert r.final and r.correct
    assert len(session.exec(select(DrillAnswer)).all()) == 1
    session.refresh(m)
    assert m.drilled_count == 1


def test_bad_index(session):
    with pytest.raises(IndexError):
        drill_player.submit(session, make_set(session), 5, "x", 1, NOW)


# --- progress -------------------------------------------------------------------


def test_progress_and_completion(session):
    ds = make_set(session)
    p = drill_player.progress(session, ds)
    assert (p.total, p.answered, p.correct, p.next_idx, p.done) == (2, 0, 0, 0, False)
    drill_player.submit(session, ds, 0, "рублей", 1, NOW)
    p = drill_player.progress(session, ds)
    assert (p.answered, p.correct, p.next_idx) == (1, 1, 1)
    assert ds.completed_at is None and drills.open_set(session).id == ds.id
    drill_player.submit(session, ds, 1, "нет", 2, NOW)
    p = drill_player.progress(session, ds)
    assert (p.answered, p.correct, p.next_idx, p.done) == (2, 1, None, True)
    session.refresh(ds)
    assert ds.completed_at is not None and drills.open_set(session) is None


# --- routes ---------------------------------------------------------------------


def test_page_with_nothing_to_drill(client, monkeypatch):
    monkeypatch.setattr(drills, "plan_next", lambda session, now=None: ("none", []))
    page = client.get("/drills")
    assert page.status_code == 200
    assert "Nothing to drill yet" in page.text and "Generate drills" not in page.text


def test_page_shows_plan_and_generate_button(client, session):
    session.add(Mistake(module=Module.story, category=Category.case, subcategory="genitive plural", wrong="a", right="b"))
    session.commit()
    page = client.get("/drills")
    assert "Focused:" in page.text and "Generate drills" in page.text and "about 30 seconds" in page.text


def test_open_focused_set_shows_rule_card_then_items(client, session):
    ds = make_set(session)
    page = client.get("/drills")
    assert "Rule card" in page.text and "After 5+ use the genitive plural." in page.text and "Start" in page.text
    assert 'name="answer"' not in page.text
    item = client.get("/drills/item")
    assert 'name="answer"' in item.text and 'lang="ru"' in item.text and "[рубль]" in item.text
    assert 'spellcheck="false"' in item.text and 'autocomplete="off"' in item.text and "autofocus" in item.text
    assert "Question 1 of 2" in item.text
    assert ds.id


def test_set_in_progress_skips_rule_card(client, session):
    ds = make_set(session)
    drill_player.submit(session, ds, 0, "рублей", 1, NOW)
    page = client.get("/drills")
    assert "Rule card" not in page.text and "Question 2 of 2" in page.text


def test_mixed_set_has_no_rule_card(client, session):
    make_set(session, kind="mixed", intro=False)
    assert "Question 1 of 2" in client.get("/drills").text


def post(client, ds, idx, answer, attempt):
    return client.post("/drills/answer", data={"set_id": ds.id, "idx": idx, "attempt": attempt, "answer": answer})


def test_answer_flow_wrong_then_hint_then_reveal(client, session):
    ds = make_set(session)
    r = post(client, ds, 0, "рубля", 1)
    assert "Not quite" in r.text and GEN_PL in r.text and "Genitive plural" in r.text and 'name="attempt" value="2"' in r.text
    assert 'value="рубля"' in r.text
    r = post(client, ds, 0, "рубля!", 2)
    assert "Not this time" in r.text and "Биле́т сто́ит пять рубле́й." in r.text and "5+ takes genitive plural" in r.text
    assert "Next" in r.text and "autofocus" in r.text
    assert len(session.exec(select(Mistake).where(Mistake.module == Module.drill)).all()) == 1


def test_answer_flow_correct_then_finish_screen(client, session):
    ds = make_set(session)
    r = post(client, ds, 0, "рублей", 1)
    assert "Correct" in r.text and "Next" in r.text
    r = post(client, ds, 1, "книг", 1)
    assert "Finish" in r.text
    done = client.get(f"/drills/done?set_id={ds.id}")
    assert "Set finished" in done.text and "2</b> of 2" in done.text and "Generate another set" in done.text
    assert 'href="/"' in done.text and "Genitive plural" in done.text


def test_empty_answer_route_asks_again(client, session):
    ds = make_set(session)
    r = post(client, ds, 0, "  ", 1)
    assert "Type an answer first" in r.text
    assert session.exec(select(DrillAnswer)).all() == []


def test_answer_unknown_set_or_item_404(client, session):
    ds = make_set(session)
    assert client.post("/drills/answer", data={"set_id": 999, "idx": 0, "answer": "x"}).status_code == 404
    assert post(client, ds, 9, "x", 1).status_code == 404


def test_generate_shows_new_set(client, session, monkeypatch):
    holder = {}

    def fake(db, client=None, now=None):
        holder["ds"] = make_set(db)
        return holder["ds"]

    monkeypatch.setattr(drills, "next_set", fake)
    r = client.post("/drills/generate")
    assert "Rule card" in r.text


@pytest.mark.parametrize("exc", [ClaudeError("The API is busy."), drills.NotEnoughItems("Too few good items.")])
def test_generate_errors_show_inline_with_retry(client, session, monkeypatch, exc):
    session.add(Mistake(module=Module.story, category=Category.case, subcategory="genitive plural", wrong="a", right="b"))
    session.commit()

    def boom(db, client=None, now=None):
        raise exc

    monkeypatch.setattr(drills, "next_set", boom)
    r = client.post("/drills/generate")
    assert r.status_code == 200 and str(exc) in r.text and "Try again" in r.text


def test_second_try_wrong_on_an_item_without_category_uses_the_sets(session):
    """Sets generated before items carried a category must not crash the miss path."""
    item = make_item()
    del item["category"]
    ds = make_set(session, items=[item])
    r = drill_player.submit(session, ds, 0, "рубля", 2, NOW)
    assert r.final and not r.correct
    assert session.exec(select(Mistake).where(Mistake.module == Module.drill)).one().category == Category.case

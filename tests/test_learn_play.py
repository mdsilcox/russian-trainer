import json

import pytest
from sqlmodel import select

from app.models import ExerciseAttempt, Unit
from app.routes import learn_play
from app.services import exercises, unit_content, units
from app.services.exercises import (
    BuildItem, ChoiceItem, DictationItem, FillItem, ListenChoiceItem, MatchItem, TransformItem, TranslateItem,
)

UNIT = unit_content.DEMO_UNIT
BASE = f"/learn/{UNIT}/play"


@pytest.fixture
def seeded(session):
    units.seed_curriculum(session)
    unit_content.seed_demo(session)
    return session.get(Unit, UNIT)


@pytest.fixture
def finishes(monkeypatch):
    """Spy on units.finish_step as the player calls it."""
    calls = []
    real = units.finish_step

    def spy(session, unit, kind, score, variant=0, now=None):
        calls.append((kind, round(score, 3), variant))
        return real(session, unit, kind, score, variant, now)

    monkeypatch.setattr(learn_play.units, "finish_step", spy)
    return calls


def right(item) -> str:
    """A correct response for any item, as the player posts it."""
    if item.type in ("choice", "listen_choice"):
        return str(item.answer_index)
    if item.type == "match":
        return json.dumps([[p["left"], p["right"]] for p in item.pairs])
    if item.type == "dictation":
        return item.audio_ru
    return item.answer


def wrong(item) -> str:
    if item.type in ("choice", "listen_choice"):
        return str((item.answer_index + 1) % len(item.options))
    return "неправильно"


def answer(client, kind, idx, response, score=0, attempt=1, variant=0, misses=0):
    return client.post(f"{BASE}/{kind}/answer", data={
        "variant": variant, "idx": idx, "score": score, "attempt": attempt, "response": response, "misses": misses})


def nxt(client, kind, idx, score, variant=0):
    return client.post(f"{BASE}/{kind}/next", data={"variant": variant, "idx": idx, "score": score})


def items_of(session, unit, kind, variant=0):
    return units.get_items(session, unit, kind, variant)[1]


# --- checkers --------------------------------------------------------------------------------

def test_check_choice_and_listen_choice_by_index():
    choice = ChoiceItem(id="a", question_ru="Мы ___ гости́нице.", options=["в", "на"], answer_index=0)
    assert exercises.check(choice, "0") and exercises.check(choice, 0)
    assert not exercises.check(choice, "1")
    assert not exercises.check(choice, "") and not exercises.check(choice, "x") and not exercises.check(choice, None)
    listen = ListenChoiceItem(id="b", audio_ru="Я тут.", question_en="?", options=["x", "y", "z"], answer_index=2)
    assert exercises.check(listen, " 2 ") and not exercises.check(listen, "0")


def test_check_fill_ignores_stress_case_yo_and_spacing():
    fill = FillItem(id="f", prompt_ru="Я в ___.", cue="аэропорт", translation_en="x", answer="аэропорту́",
                    accepted=["аэропорте"])
    assert exercises.check(fill, "аэропорту")
    assert exercises.check(fill, "  АЭРОПОРТУ́ ")
    assert exercises.check(fill, "аэропорте")
    assert not exercises.check(fill, "аэропорт")
    assert not exercises.check(fill, "")
    yo = FillItem(id="g", prompt_ru="Это ___.", cue="", translation_en="x", answer="ёлка")
    assert exercises.check(yo, "елка")


def test_check_transform_translate_and_accepted_variants():
    t = TransformItem(id="t", source_ru="Я иду́ в музе́й.", task="x", answer="Я в музе́е.", accepted=["Я уже́ в музе́е."])
    assert exercises.check(t, "я в музее") and exercises.check(t, "Я уже в музее!")
    assert not exercises.check(t, "Я в музей")
    tr = TranslateItem(id="r", en="We are at the market.", answer="Мы на ры́нке.")
    assert exercises.check(tr, "мы на рынке.") and not exercises.check(tr, "Мы в рынке")


def test_check_build_ignores_final_full_stop():
    b = BuildItem(id="b", meaning_en="x", tiles=["Магази́н", "на", "у́лице."], answer="Магази́н на у́лице.",
                  accepted=["На у́лице магази́н."])
    assert exercises.check(b, "Магазин на улице")
    assert exercises.check(b, "магазин на улице.")
    assert exercises.check(b, "На улице магазин")
    assert not exercises.check(b, "на магазин улице")


def test_check_dictation_uses_audio_text_and_accepted():
    d = DictationItem(id="d", audio_ru="Апте́ка на пло́щади.", translation_en="x", accepted=["Аптека на площади"])
    assert exercises.check(d, "аптека на площади")
    assert exercises.check(d, "Апте́ка на пло́щади.")
    assert not exercises.check(d, "аптека на площадь")


def test_check_match_needs_every_pair():
    m = MatchItem(id="m", pairs=[{"left": "вокза́л", "right": "на вокза́ле"}, {"left": "парк", "right": "в па́рке"}])
    ok = [["вокзал", "на вокзале"], ["парк", "в парке"]]
    assert exercises.check(m, json.dumps(ok)) and exercises.check(m, ok)
    assert not exercises.check(m, json.dumps([["вокзал", "в парке"], ["парк", "на вокзале"]]))
    assert not exercises.check(m, json.dumps(ok[:1]))
    assert not exercises.check(m, json.dumps(ok + ok[:1]))
    assert not exercises.check(m, "not json") and not exercises.check(m, "")


# --- pages -----------------------------------------------------------------------------------

def test_play_page_shows_first_item(client, seeded):
    html = client.get(f"{BASE}/practice").text
    assert "Question 1 of 8" in html
    assert 'name="response"' in html and "learn_play.css" in html


def test_every_item_type_renders(client, seeded, session):
    expected = {"choice": "lp-option", "fill": "lp-blank", "match": "data-lp-match", "transform": "lp-input",
                "build": "data-lp-build", "translate": "lp-input"}
    for idx, item in enumerate(items_of(session, seeded, "practice")):
        html = client.get(f"{BASE}/practice/item", params={"idx": idx}).text
        assert expected[item.type] in html, item.type
        assert "Question %d of 8" % (idx + 1) in html
    for idx, item in enumerate(items_of(session, seeded, "listening")):
        html = client.get(f"{BASE}/listening/item", params={"idx": idx}).text
        assert f'data-item-type="{item.type}"' in html
        assert 'name="response"' in html


def test_build_tiles_are_stable_and_shuffled(client, seeded, session):
    idx = next(i for i, it in enumerate(items_of(session, seeded, "practice")) if it.type == "build")
    first = client.get(f"{BASE}/practice/item", params={"idx": idx}).text
    assert first == client.get(f"{BASE}/practice/item", params={"idx": idx}).text
    item = items_of(session, seeded, "practice")[idx]
    pos = [first.index(f">{t}</button>") for t in item.tiles]
    assert pos != sorted(pos)  # not left in answer order


def test_unknown_unit_or_kind_is_404(client, seeded):
    assert client.get("/learn/nope/play/practice").status_code == 404
    assert client.get(f"{BASE}/lesson").status_code == 404
    assert client.get(f"{BASE}/practice/item", params={"idx": 99}).status_code == 404


def test_unwritten_set_shows_friendly_message_with_link_back(client, seeded, monkeypatch):
    def not_yet(*a, **k):
        raise NotImplementedError

    monkeypatch.setattr(unit_content, "generate_items", not_yet)
    html = client.get(f"/learn/u02-where-to/play/practice/item").text
    assert "been written yet" in html
    assert 'href="/learn/u02-where-to"' in html


def test_claude_error_is_shown_inline(client, seeded, monkeypatch):
    from app.services.claude import ClaudeError

    def boom(*a, **k):
        raise ClaudeError("Claude is busy. Try again in a minute.")

    monkeypatch.setattr(learn_play.units, "get_items", boom)
    html = client.get(f"{BASE}/practice/item").text
    assert "Claude is busy" in html and "Try again" in html and f'href="/learn/{UNIT}"' in html


def test_missing_content_page_loads_behind_a_loading_state(client, seeded):
    html = client.get("/learn/u02-where-to/play/practice").text
    assert 'hx-trigger="load"' in html and "Preparing your exercises" in html


# --- attempt rules -----------------------------------------------------------------------------

def attempts(session):
    return list(session.exec(select(ExerciseAttempt).order_by(ExerciseAttempt.id)).all())


def test_practice_gives_two_tries_then_the_answer(client, seeded, session):
    item = items_of(session, seeded, "practice")[0]  # choice q1
    first = answer(client, "practice", 0, wrong(item)).text
    assert "Not quite" in first
    assert "Try again" in first
    assert "Stations go with" not in first  # explanation and answer wait for the end
    second = answer(client, "practice", 0, wrong(item), attempt=2).text
    assert "Not this time" in second
    assert "Stations go with" in second
    assert [(a.attempt, a.correct) for a in attempts(session)] == [(1, False), (2, False)]


def test_practice_hint_shows_the_items_instruction(client, seeded, session, monkeypatch):
    item = items_of(session, seeded, "practice")[1]
    patched = item.model_copy(update={"instruction": "Think about the ending after в."})
    monkeypatch.setattr(learn_play.units, "get_items", lambda *a, **k: ("T", [patched]))
    html = answer(client, "practice", 0, "xxx").text
    assert "Not quite" in html and "Think about the ending after в." in html
    assert patched.answer not in html


def test_second_try_credit_does_not_count_for_score(client, seeded, session):
    item = items_of(session, seeded, "practice")[0]
    html = answer(client, "practice", 0, right(item), attempt=2, score=3).text
    assert "Correct on the second try" in html
    assert 'name="score" value="3"' in html
    html = answer(client, "practice", 0, right(item), attempt=1, score=3).text
    assert 'name="score" value="4"' in html


@pytest.mark.parametrize("kind", ["pretest", "quiz"])
def test_pretest_and_quiz_allow_one_try_and_explain(client, seeded, session, kind):
    item = items_of(session, seeded, kind)[0]
    html = answer(client, kind, 0, wrong(item)).text
    assert "Not this time" in html and item.explanation in html
    assert "Not quite" not in html and "Try again" not in html
    assert [(a.attempt, a.correct) for a in attempts(session)] == [(1, False)]
    # a stale second attempt is still treated as the only one
    html = answer(client, kind, 0, wrong(item), attempt=2).text
    assert "Not this time" in html and attempts(session)[-1].attempt == 1


def test_correct_first_try_shows_explanation_in_a_quiz(client, seeded, session):
    item = items_of(session, seeded, "quiz")[0]
    html = answer(client, "quiz", 0, right(item)).text
    assert "Correct" in html and item.explanation in html


def test_empty_answer_costs_nothing(client, seeded, session):
    html = answer(client, "practice", 0, "").text
    assert "Give an answer first" in html
    assert attempts(session) == []


def test_match_counts_misses_against_first_try(client, seeded, session):
    idx = next(i for i, it in enumerate(items_of(session, seeded, "practice")) if it.type == "match")
    item = items_of(session, seeded, "practice")[idx]
    clean = answer(client, "practice", idx, right(item), score=1).text
    assert 'name="score" value="2"' in clean
    messy = answer(client, "practice", idx, right(item), score=1, misses=2).text
    assert 'name="score" value="1"' in messy and "Matched, with 2 slips" in messy


def test_every_item_type_can_be_answered_right(client, seeded, session):
    for kind in ("practice", "listening"):
        for idx, item in enumerate(items_of(session, seeded, kind)):
            html = answer(client, kind, idx, right(item)).text
            assert "lp-verdict" in html and ">Correct<" in html, (kind, item.type)


# --- finishing ---------------------------------------------------------------------------------

def play_through(client, session, unit, kind, variant=0, miss=()):
    """Answer every item (right unless its index is in `miss`), then press Finish; returns the final page."""
    items = items_of(session, unit, kind, variant)
    score = 0
    for idx, item in enumerate(items):
        wrong_first = idx in miss
        html = answer(client, kind, idx, wrong(item) if wrong_first else right(item), score=score,
                      variant=variant).text
        if wrong_first and kind not in learn_play.ONE_TRY:
            html = answer(client, kind, idx, wrong(item), score=score, attempt=2, variant=variant).text
        score += 0 if wrong_first else 1
        assert f'name="idx" value="{idx + 1}"' in html
    return nxt(client, kind, len(items), score, variant), len(items), score


def test_finish_calls_finish_step_with_kind_variant_and_score(client, seeded, session, finishes):
    page, total, score = play_through(client, session, seeded, "practice", variant=1, miss=(0,))
    assert finishes == [("practice", round((total - 1) / total, 3), 1)]
    assert f"{total - 1}</b> of {total}" in page.text
    assert "Back to the unit" in page.text and f'href="/learn/{UNIT}"' in page.text
    assert units.progress(session, seeded).steps_json["practice:1"]["score"] == pytest.approx((total - 1) / total, abs=0.001)


def test_quiz_pass_message_is_shown(client, seeded, session, finishes):
    page, total, _ = play_through(client, session, seeded, "quiz")
    assert finishes == [("quiz", 1.0, 0)]
    assert "Passed" in page.text and "100%" in page.text


def test_failed_quiz_shows_what_happens_next(client, seeded, session, finishes):
    n = len(items_of(session, seeded, "quiz"))
    page, _, _ = play_through(client, session, seeded, "quiz", miss=tuple(range(n)))
    assert finishes == [("quiz", 0.0, 0)]
    assert "remediation" in page.text.lower()


def test_pretest_ace_offers_fast_track(client, seeded, session, finishes):
    page, _, _ = play_through(client, session, seeded, "pretest")
    assert finishes == [("pretest", 1.0, 0)]
    assert "Skip to the quiz" in page.text
    assert f'action="/learn/{UNIT}/fast-track"' in page.text


def test_weak_pretest_has_no_fast_track(client, seeded, session):
    n = len(items_of(session, seeded, "pretest"))
    page, _, _ = play_through(client, session, seeded, "pretest", miss=tuple(range(n)))
    assert "Skip to the quiz" not in page.text


def test_fast_track_route_redirects_to_the_unit(client, seeded, session):
    play_through(client, session, seeded, "pretest")
    r = client.post(f"/learn/{UNIT}/fast-track", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/learn/{UNIT}"
    session.expire_all()
    assert "fast_track" in units.progress(session, seeded).steps_json


def test_fast_track_without_the_score_changes_nothing(client, seeded, session):
    r = client.post(f"/learn/{UNIT}/fast-track", follow_redirects=False)
    assert r.status_code == 303
    session.expire_all()
    assert "fast_track" not in (units.progress(session, seeded).steps_json or {})
    assert client.post("/learn/nope/fast-track").status_code == 404


def test_remediation_intro_is_shown_before_the_first_item(client, seeded, session):
    body = {"title": "Remediation", "intro": "Think of в as a box you are inside.",
            "items": [i.model_dump() for i in items_of(session, seeded, "practice")[:2]]}
    units.store(session, UNIT, "remediation", 0, body)
    html = client.get(f"{BASE}/remediation").text
    assert "Think of в as a box" in html
    later = client.get(f"{BASE}/remediation/item", params={"idx": 1}).text
    assert "Think of в as a box" not in later


def test_match_slips_wording(client, seeded, session):
    q = items_of(session, seeded, "quiz")
    midx = next(i for i, it in enumerate(q) if it.type == "match")
    html = answer(client, "quiz", midx, right(q[midx]), misses=1).text
    assert "Not this time" in html and "second try" not in html
    p = items_of(session, seeded, "practice")
    pidx = next(i for i, it in enumerate(p) if it.type == "match")
    html = answer(client, "practice", pidx, right(p[pidx]), misses=2).text
    assert "Matched, with 2 slips" in html and "second try" not in html


def test_listening_result_shows_what_was_heard_with_replay(client, seeded, session):
    for idx, item in enumerate(items_of(session, seeded, "listening")):
        html = answer(client, "listening", idx, right(item)).text
        assert 'data-speak="%s"' % item.audio_ru in html and "You heard" in html, item.type
        if item.type == "dictation":
            assert item.translation_en.replace("'", "&#39;") in html

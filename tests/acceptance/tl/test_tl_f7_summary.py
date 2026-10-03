"""Feature 7: pre-lesson summary (structured Claude call)."""

import dataclasses
from datetime import timedelta

import fsrs
import pytest
from sqlmodel import select

from tl_h import D, STRESS, make_card, noon


def _facts_fixture(session):
    """Lessons at D-14, D-7, D (under test) and D+7; activity before, inside and after the window [D-7, D]."""
    from app.models import CardState, Category, Mistake, Module, Session as Study
    from app.services import lessons, srs

    lessons.create_lesson(session, D - timedelta(days=14), "very old")
    lessons.create_lesson(session, D - timedelta(days=7), "previous")
    lesson = lessons.create_lesson(session, D, "Genitive")
    lessons.create_lesson(session, D + timedelta(days=7), "next one")

    for day, minutes, completed in [(-8, 100, True), (-7, 20, True), (-3, 15.5, True), (-2, 50, False)]:
        session.add(Study(date=D + timedelta(days=day), minutes=minutes, completed=completed))
    session.commit()

    def card(ru, day, module=Module.manual):
        c = make_card(session, ru=ru, en=ru, source_module=module)
        c.created_at = noon(D + timedelta(days=day))
        session.add(c)
        session.commit()
        return c

    old = card("старое", -9)
    card("граница", -7)
    card("тутор", -1, Module.tutor)
    card("ручное", -1)
    # Reviews: one before the window, one on the boundary day, two later.
    cs = session.exec(select(CardState).where(CardState.card_id == old.id)).one()
    for day in (-8, -7, -1, -1):
        srs.review(session, cs, fsrs.Rating.Good, noon(D + timedelta(days=day)))

    def mistakes(category, n, day):
        for _ in range(n):
            session.add(Mistake(module=Module.story, category=category, wrong="x", right="y",
                                created_at=noon(D + timedelta(days=day))))
        session.commit()

    mistakes(Category.case, 5, -8)  # before the window: ignored
    mistakes(Category.case, 3, -2)
    mistakes(Category.stress, 2, -1)
    mistakes(Category.aspect, 2, -1)
    mistakes(Category.idiom, 1, -1)

    a = lessons.add_task(session, "done in window", D)
    b = lessons.add_task(session, "done long ago", D)
    lessons.add_task(session, "still open 1", D + timedelta(days=1))
    lessons.add_task(session, "still open 2", D - timedelta(days=4))
    lessons.complete_task(session, a.id, noon(D - timedelta(days=3)))
    lessons.complete_task(session, b.id, noon(D - timedelta(days=10)))

    lessons.add_question(session, "second question", "/cards", noon(D - timedelta(days=1)))
    lessons.add_question(session, "first question", "/", noon(D - timedelta(days=2)))
    asked = lessons.add_question(session, "already asked", "/", noon(D - timedelta(days=2)))
    lessons.mark_asked(session, asked.id)
    return lesson


def test_f7_facts_window(session):
    from app.services import lessons

    lesson = _facts_fixture(session)
    f = lessons.summary_facts(session, lesson.id, noon(D))
    assert dataclasses.is_dataclass(f)
    assert f.since == D - timedelta(days=7)
    assert f.minutes == pytest.approx(35.5)
    assert f.reviews == 3
    assert f.new_cards == 3
    assert f.tutor_cards == 1


def test_f7_facts_top_mistakes(session):
    from app.services import lessons

    lesson = _facts_fixture(session)
    f = lessons.summary_facts(session, lesson.id, noon(D))
    # case x3, then aspect and stress tie at 2 (alphabetical by value), idiom x1 is cut.
    assert [getattr(m, "value", m) for m in f.top_mistakes] == ["case", "aspect", "stress"]


def test_f7_facts_tasks_and_questions(session):
    from app.services import lessons

    lesson = _facts_fixture(session)
    f = lessons.summary_facts(session, lesson.id, noon(D))
    assert f.tasks_done == 1
    assert f.tasks_open == 2
    assert list(f.questions) == ["first question", "second question"]


def test_f7_facts_no_previous_lesson(session):
    from app.models import Session as Study
    from app.services import lessons

    lesson = lessons.create_lesson(session, D, "Only lesson")
    lessons.create_lesson(session, D + timedelta(days=7), "future one")
    session.add(Study(date=D - timedelta(days=8), minutes=99, completed=True))
    session.add(Study(date=D - timedelta(days=7), minutes=10, completed=True))
    session.commit()
    f = lessons.summary_facts(session, lesson.id, noon(D))
    assert f.since == D - timedelta(days=7)
    assert f.minutes == pytest.approx(10)
    assert f.top_mistakes == [] and f.questions == []
    assert (f.reviews, f.new_cards, f.tutor_cards, f.tasks_done, f.tasks_open) == (0, 0, 0, 0, 0)


def _client_with(*responses):
    from acc_common import FakeClaude

    return FakeClaude().push(*responses)


def test_f7_prompt_has_questions(session):
    from app.services import lessons
    from app.services.claude import Task

    lesson = _facts_fixture(session)
    fake = _client_with({"summary_ru": "Мы изуча́ли роди́тельный паде́ж.", "focus_points": ["Practise genitive plural"]})
    lessons.pre_lesson_summary(session, lesson.id, fake, noon(D))
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["task"] == Task.lesson_summary
    assert call["model"] is lessons.LessonSummaryText
    assert "first question" in call["prompt"] and "second question" in call["prompt"]
    assert "already asked" not in call["prompt"]
    assert "Genitive" in call["prompt"]


def test_f7_summary_result_shape(session):
    from app.services import lessons

    lesson = _facts_fixture(session)
    fake = _client_with({"summary_ru": "Хорошо́ порабо́тали.", "focus_points": ["Aspect pairs", "Stress"]})
    s = lessons.pre_lesson_summary(session, lesson.id, fake, noon(D))
    assert dataclasses.is_dataclass(s)
    assert isinstance(s.facts, lessons.SummaryFacts) and s.facts.since == D - timedelta(days=7)
    assert s.summary_ru == "Хорошо́ порабо́тали."
    assert list(s.focus_points) == ["Aspect pairs", "Stress"]
    assert set(lessons.LessonSummaryText.model_fields) == {"summary_ru", "focus_points"}


def test_f7_summary_fixes_accents(session):
    from app.services import lessons

    lesson = lessons.create_lesson(session, D, "Topic")
    fake = _client_with({"summary_ru": "Мы купи́ли биле́т в купé и гуля́ли.", "focus_points": ["x"]})
    s = lessons.pre_lesson_summary(session, lesson.id, fake, noon(D))
    assert "é" not in s.summary_ru
    assert "купе" + STRESS in s.summary_ru


def test_f7_task_enum_uses_sonnet():
    from app.services import claude

    assert claude.Task.lesson_summary.value == "lesson_summary"
    assert claude.TASK_MODELS[claude.Task.lesson_summary] == claude.SONNET


def test_f7_summary_route(client, session, fake_claude):
    from app.services import lessons
    from app.services.claude import Task

    lesson = lessons.create_lesson(session, D, "Genitive")
    lessons.add_question(session, "What about plurals?", "/", noon(D))
    fake_claude.push({"summary_ru": "Мы повтори́ли но́вые слова́.", "focus_points": ["Drill the plural endings"]})
    r = client.post(f"/lessons/{lesson.id}/summary")
    assert r.status_code == 200
    assert "<html" not in r.text.lower()
    assert "Мы повтори́ли но́вые слова́." in r.text and "Drill the plural endings" in r.text
    assert len(fake_claude.calls) == 1 and fake_claude.calls[0]["task"] == Task.lesson_summary
    assert "What about plurals?" in fake_claude.calls[0]["prompt"]


def test_f7_summary_route_shows_claude_error(client, session, fake_claude):
    from app.services import lessons
    from app.services.claude import ClaudeError

    lesson = lessons.create_lesson(session, D, "Genitive")
    fake_claude.push(ClaudeError("busy right now"))
    r = client.post(f"/lessons/{lesson.id}/summary")
    assert r.status_code == 200
    assert "busy right now" in r.text
    low = r.text.lower()
    assert "retry" in low or "try again" in low


def test_f7_summary_route_without_ai(client, session):
    from app.services import lessons

    lesson = lessons.create_lesson(session, D, "Genitive")
    r = client.post(f"/lessons/{lesson.id}/summary")
    assert r.status_code == 200
    assert "<html" not in r.text.lower()

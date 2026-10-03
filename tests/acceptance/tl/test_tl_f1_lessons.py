"""Feature 1: lesson model and service."""

from datetime import timedelta

import pytest

from tl_h import D, noon


def test_f1_create_and_get(session):
    from app.services import lessons

    lesson = lessons.create_lesson(
        session, D, "Genitive case", goals=["Use genitive after numbers", "", "   ", "Learn 10 words"],
        materials=[{"title": "Notes", "url": "https://example.com/notes"}], notes="Bring homework",
    )
    assert lesson.id is not None
    got = lessons.get_lesson(session, lesson.id)
    assert got.topic == "Genitive case"
    assert got.date == D
    assert got.notes == "Bring homework"
    assert list(got.goals) == ["Use genitive after numbers", "Learn 10 words"]
    assert [dict(m) for m in got.materials] == [{"title": "Notes", "url": "https://example.com/notes"}]
    assert got.created_at is not None


def test_f1_defaults_and_missing(session):
    from app.services import lessons

    lesson = lessons.create_lesson(session, D, "Greetings")
    assert list(lesson.goals) == []
    assert list(lesson.materials) == []
    assert lesson.notes in ("", None)
    assert lessons.get_lesson(session, 9999) is None


@pytest.mark.parametrize("topic", ["", "   ", "\n"])
def test_f1_topic_required(session, topic):
    from app.services import lessons

    with pytest.raises(ValueError):
        lessons.create_lesson(session, D, topic)
    assert lessons.list_lessons(session) == []


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://example.com/file", "example.com/page", "data:text/html,hi", "//example.com"])
def test_f1_material_url_must_be_http(session, url):
    from app.services import lessons

    with pytest.raises(ValueError):
        lessons.create_lesson(session, D, "Topic", materials=[{"title": "x", "url": url}])
    assert lessons.list_lessons(session) == []


def test_f1_material_title_defaults_to_url(session):
    from app.services import lessons

    lesson = lessons.create_lesson(
        session, D, "Topic",
        materials=[{"url": "http://example.com/a"}, {"title": "", "url": "https://example.com/b"}, {"title": "Named", "url": "https://example.com/c"}],
    )
    titles = {m["url"]: m["title"] for m in lessons.get_lesson(session, lesson.id).materials}
    assert titles == {"http://example.com/a": "http://example.com/a", "https://example.com/b": "https://example.com/b",
                      "https://example.com/c": "Named"}


def test_f1_list_order_newest_date_then_newest_id(session):
    from app.services import lessons

    lessons.create_lesson(session, D, "a")
    lessons.create_lesson(session, D + timedelta(days=7), "b")
    lessons.create_lesson(session, D, "c")
    lessons.create_lesson(session, D - timedelta(days=7), "d")
    assert [x.topic for x in lessons.list_lessons(session)] == ["b", "c", "a", "d"]


def test_f1_update_lesson(session):
    from app.services import lessons

    lesson = lessons.create_lesson(session, D, "Old", goals=["g1"])
    updated = lessons.update_lesson(
        session, lesson.id, topic="New", date=D + timedelta(days=1), goals=["x", "", "y"], notes="n2",
        materials=[{"url": "https://example.com/z"}],
    )
    got = lessons.get_lesson(session, lesson.id)
    assert updated.id == got.id
    assert got.topic == "New" and got.date == D + timedelta(days=1) and got.notes == "n2"
    assert list(got.goals) == ["x", "y"]
    assert got.materials[0]["url"] == "https://example.com/z"
    assert got.materials[0]["title"] == "https://example.com/z"


def test_f1_update_rejects_blank_topic(session):
    from app.services import lessons

    lesson = lessons.create_lesson(session, D, "Keep me")
    with pytest.raises(ValueError):
        lessons.update_lesson(session, lesson.id, topic="  ")
    assert lessons.get_lesson(session, lesson.id).topic == "Keep me"


def test_f1_current_and_next_lesson(session):
    from app.services import lessons

    now = noon(D)
    assert lessons.current_lesson(session, now) is None
    assert lessons.next_lesson(session, now) is None
    lessons.create_lesson(session, D - timedelta(days=14), "past old")
    lessons.create_lesson(session, D - timedelta(days=3), "past")
    lessons.create_lesson(session, D + timedelta(days=2), "soon")
    lessons.create_lesson(session, D + timedelta(days=9), "later")
    assert lessons.current_lesson(session, now).topic == "past"
    assert lessons.next_lesson(session, now).topic == "soon"


def test_f1_current_next_with_only_one_side(session):
    from app.services import lessons

    now = noon(D)
    lessons.create_lesson(session, D + timedelta(days=1), "future")
    assert lessons.current_lesson(session, now) is None
    assert lessons.next_lesson(session, now).topic == "future"
    lessons.create_lesson(session, D - timedelta(days=1), "yesterday")
    assert lessons.current_lesson(session, now).topic == "yesterday"

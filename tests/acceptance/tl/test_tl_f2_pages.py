"""Feature 2: lesson pages."""

from datetime import timedelta

from tl_h import D, location_ok, noon


def test_f2_list_page_renders_with_form(client):
    r = client.get("/lessons")
    assert r.status_code == 200
    assert "<form" in r.text
    assert 'name="topic"' in r.text and 'name="date"' in r.text


def test_f2_list_shows_lessons(client, session):
    from app.services import lessons

    lessons.create_lesson(session, D, "Dative case")
    lessons.create_lesson(session, D - timedelta(days=7), "Greetings")
    r = client.get("/lessons")
    assert "Dative case" in r.text and "Greetings" in r.text
    assert r.text.index("Dative case") < r.text.index("Greetings")
    assert f'href="/lessons/{lessons.list_lessons(session)[0].id}"' in r.text


def test_f2_post_creates_and_redirects(client, session):
    from app.services import lessons

    r = client.post("/lessons", data={
        "date": "2026-03-10", "topic": "Cases", "goals": "one\n\ntwo\r\n",
        "materials": "Site | https://example.com/a\nhttps://example.com/b", "notes": "hello",
    }, follow_redirects=False)
    assert r.status_code == 303
    lesson = lessons.list_lessons(session)[0]
    assert location_ok(r, f"/lessons/{lesson.id}")
    assert lesson.topic == "Cases" and lesson.date == D and lesson.notes == "hello"
    assert list(lesson.goals) == ["one", "two"]
    assert {m["url"]: m["title"] for m in lesson.materials} == {
        "https://example.com/a": "Site", "https://example.com/b": "https://example.com/b"}


def test_f2_post_invalid_returns_400_with_form_as_typed(client, session):
    from app.services import lessons

    r = client.post("/lessons", data={"date": "2026-03-10", "topic": "  ", "goals": "kept goal text", "materials": "", "notes": "typed notes here"})
    assert r.status_code == 400
    assert "typed notes here" in r.text and "kept goal text" in r.text
    r = client.post("/lessons", data={"date": "2026-03-10", "topic": "T", "goals": "", "materials": "Bad | javascript:alert(1)", "notes": "n"})
    assert r.status_code == 400
    assert lessons.list_lessons(session) == []


def test_f2_post_bad_date_returns_400(client, session):
    from app.services import lessons

    r = client.post("/lessons", data={"date": "not-a-date", "topic": "T", "goals": "", "materials": "", "notes": ""})
    assert r.status_code == 400
    assert lessons.list_lessons(session) == []


def test_f2_detail_page_content(client, session):
    from app.services import lessons

    lesson = lessons.create_lesson(
        session, D, "Past tense", goals=["Retell a day", "Use perfective"],
        materials=[{"title": "Worksheet", "url": "https://example.com/ws"}], notes="Ask about выходные")
    lessons.add_task(session, "Write a diary entry", D + timedelta(days=3), lesson_id=lesson.id)
    lessons.add_words(session, lesson.id, [{"ru": "дневник", "en": "diary"}])
    lessons.add_question(session, "When do I use the pluperfect?", "/review", noon(D))
    r = client.get(f"/lessons/{lesson.id}")
    assert r.status_code == 200
    for text in ["Past tense", "Retell a day", "Use perfective", "Worksheet", "Ask about выходные",
                 "Write a diary entry", "дневник", "diary", "When do I use the pluperfect?"]:
        assert text in r.text, text
    assert 'href="https://example.com/ws"' in r.text


def test_f2_detail_unknown_is_404(client, session):
    from app.services import lessons

    lesson = lessons.create_lesson(session, D, "Exists")
    assert client.get(f"/lessons/{lesson.id}").status_code == 200
    assert client.get(f"/lessons/{lesson.id + 100}").status_code == 404


def test_f2_detail_escapes_html(client, session):
    from app.services import lessons

    lesson = lessons.create_lesson(session, D, "<script>alert(1)</script>", goals=["<img src=x onerror=alert(2)>"], notes="<b>bold</b>")
    r = client.get(f"/lessons/{lesson.id}")
    assert "<script>alert(1)</script>" not in r.text
    assert "<img src=x" not in r.text
    assert "<b>bold</b>" not in r.text


def test_f2_nav_has_lessons_link(client):
    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/lessons"' in r.text
    assert ">Lessons<" in r.text

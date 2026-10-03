"""Feature 6: "Question for my tutor", from any page."""

from datetime import timedelta

import pytest

from tl_h import D, location_ok, noon

# Adapted for main (the user's Phase 6 choice): the control sits on Today, review and the lesson
# pages only, instead of every page the spec named.
PAGES = ["/", "/review", "/lessons"]
NOT_ON = ["/cards", "/dashboard", "/workshop", "/plan", "/grammar", "/drills", "/scenarios", "/shelf", "/settings"]


def test_f6_add_question_fields(session):
    from app.services import lessons

    q = lessons.add_question(session, "  Why is it в, not на?  ", "/review", noon(D))
    assert q.id is not None and q.asked is False
    assert q.text == "Why is it в, not на?" and q.page == "/review"
    assert q.created_at is not None


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_f6_add_question_blank(session, text):
    from app.services import lessons

    with pytest.raises(ValueError):
        lessons.add_question(session, text, "/", noon(D))
    assert lessons.open_questions(session) == []


def test_f6_open_questions_oldest_first_and_mark_asked(session):
    from app.services import lessons

    q1 = lessons.add_question(session, "first", "/", noon(D))
    q2 = lessons.add_question(session, "second", "/cards", noon(D + timedelta(days=1)))
    q3 = lessons.add_question(session, "third", "/", noon(D + timedelta(days=2)))
    assert [q.text for q in lessons.open_questions(session)] == ["first", "second", "third"]
    done = lessons.mark_asked(session, q2.id)
    assert done.id == q2.id and done.asked is True
    assert [q.text for q in lessons.open_questions(session)] == ["first", "third"]
    assert {q1.id, q3.id} == {q.id for q in lessons.open_questions(session)}


def test_f6_question_route_htmx_partial(client, session):
    from app.services import lessons

    r = client.post("/questions", data={"text": "What is the aspect pair of брать?", "page": "/review"},
                    headers={"HX-Request": "true"}, follow_redirects=False)
    assert r.status_code == 200
    assert "<html" not in r.text.lower()
    q = lessons.open_questions(session)[0]
    assert q.text == "What is the aspect pair of брать?" and q.page == "/review" and q.asked is False


def test_f6_question_route_redirects_to_page(client, session):
    from app.services import lessons

    r = client.post("/questions", data={"text": "q1", "page": "/cards"}, follow_redirects=False)
    assert r.status_code == 303 and location_ok(r, "/cards")
    r = client.post("/questions", data={"text": "q2", "page": ""}, follow_redirects=False)
    assert r.status_code == 303 and location_ok(r, "/")
    assert [q.text for q in lessons.open_questions(session)] == ["q1", "q2"]


@pytest.mark.parametrize("page", ["//evil.example", "//evil.example/x", "https://evil.example/", "evil.example"])
def test_f6_question_redirect_rejects_external(client, session, page):
    from app.services import lessons

    r = client.post("/questions", data={"text": "hi", "page": page}, follow_redirects=False)
    assert r.status_code == 303
    assert location_ok(r, "/"), r.headers["location"]
    assert len(lessons.open_questions(session)) == 1


def test_f6_question_blank_is_400(client, session):
    from app.services import lessons

    r = client.post("/questions", data={"text": "   ", "page": "/review"}, follow_redirects=False)
    assert r.status_code == 400
    r = client.post("/questions", data={"text": "", "page": "/review"}, headers={"HX-Request": "true"})
    assert r.status_code == 400
    assert lessons.open_questions(session) == []


def test_f6_asked_route(client, session):
    from app.services import lessons

    lesson = lessons.create_lesson(session, D, "L")
    q = lessons.add_question(session, "Ask me", "/", noon(D))
    q2 = lessons.add_question(session, "Ask me too", "/", noon(D))
    r = client.post(f"/questions/{q.id}/asked", data={"next": f"/lessons/{lesson.id}"}, follow_redirects=False)
    assert r.status_code == 303 and location_ok(r, f"/lessons/{lesson.id}")
    r = client.post(f"/questions/{q2.id}/asked", follow_redirects=False)
    assert r.status_code == 303 and location_ok(r, "/lessons")
    session.expire_all()
    assert lessons.open_questions(session) == []


def test_f6_control_on_every_page(client):
    missing = []
    for path in PAGES:
        r = client.get(path)
        assert r.status_code == 200, path
        if "data-tutor-question" not in r.text:
            missing.append(path)
    assert missing == []
    extra = [path for path in NOT_ON if "data-tutor-question" in client.get(path).text]
    assert extra == []


def test_f6_control_on_lesson_page_and_has_form(client, session):
    from app.services import lessons

    lesson = lessons.create_lesson(session, D, "L")
    r = client.get(f"/lessons/{lesson.id}")
    assert "data-tutor-question" in r.text
    assert 'name="text"' in r.text and 'name="page"' in r.text
    assert "/questions" in r.text

"""Feature 4: tasks with due dates, on Today."""

from datetime import timedelta

import pytest

from tl_h import D, after, location_ok, noon, real_today


def test_f4_add_task_fields(session):
    from app.services import lessons

    lesson = lessons.create_lesson(session, D, "L")
    free = lessons.add_task(session, "Read chapter 1", D + timedelta(days=2))
    tied = lessons.add_task(session, "Do exercises", D, lesson_id=lesson.id)
    assert free.id is not None and free.lesson_id is None
    assert free.title == "Read chapter 1" and free.due == D + timedelta(days=2)
    assert free.done_at is None and free.created_at is not None
    assert tied.lesson_id == lesson.id


@pytest.mark.parametrize("title", ["", "  ", "\n"])
def test_f4_add_task_blank_title(session, title):
    from app.services import lessons

    with pytest.raises(ValueError):
        lessons.add_task(session, title, D)
    assert lessons.open_tasks(session) == []


def test_f4_complete_task(session):
    from app.services import lessons

    a = lessons.add_task(session, "a", D)
    b = lessons.add_task(session, "b", D)
    done = lessons.complete_task(session, a.id, noon(D))
    assert done.id == a.id and done.done_at is not None
    assert [t.title for t in lessons.open_tasks(session)] == ["b"]
    assert b.done_at is None


def test_f4_open_tasks_order(session):
    from app.services import lessons

    lessons.add_task(session, "late", D + timedelta(days=5))
    lessons.add_task(session, "early-1", D - timedelta(days=1))
    lessons.add_task(session, "mid", D + timedelta(days=1))
    lessons.add_task(session, "early-2", D - timedelta(days=1))
    done = lessons.add_task(session, "done", D - timedelta(days=9))
    lessons.complete_task(session, done.id, noon(D))
    assert [t.title for t in lessons.open_tasks(session)] == ["early-1", "early-2", "mid", "late"]


def test_f4_tasks_for_today_window(session):
    from app.services import lessons

    lessons.add_task(session, "day3", D + timedelta(days=3))
    lessons.add_task(session, "day2", D + timedelta(days=2))
    lessons.add_task(session, "overdue-old", D - timedelta(days=30))
    lessons.add_task(session, "today", D)
    lessons.add_task(session, "overdue", D - timedelta(days=1))
    done = lessons.add_task(session, "done", D + timedelta(days=1))
    lessons.complete_task(session, done.id, noon(D))
    lessons.add_task(session, "tomorrow", D + timedelta(days=1))
    got = [t.title for t in lessons.tasks_for_today(session, noon(D))]
    assert got == ["overdue-old", "overdue", "today", "tomorrow", "day2"]


def test_f4_task_route_adds_to_lesson(client, session):
    from app.services import lessons

    lesson = lessons.create_lesson(session, D, "L")
    r = client.post(f"/lessons/{lesson.id}/tasks", data={"title": "Memorise the list", "due": "2026-03-14"}, follow_redirects=False)
    assert r.status_code == 303 and location_ok(r, f"/lessons/{lesson.id}")
    tasks = lessons.open_tasks(session)
    assert [(t.title, t.due, t.lesson_id) for t in tasks] == [("Memorise the list", D + timedelta(days=4), lesson.id)]
    assert "Memorise the list" in client.get(f"/lessons/{lesson.id}").text


def test_f4_done_route_redirects_to_local_next(client, session):
    from app.services import lessons

    t = lessons.add_task(session, "x", D)
    r = client.post(f"/tasks/{t.id}/done", data={"next": "/lessons/3"}, follow_redirects=False)
    assert r.status_code == 303 and location_ok(r, "/lessons/3")
    session.expire_all()
    assert lessons.open_tasks(session) == []
    t2 = lessons.add_task(session, "y", D)
    r = client.post(f"/tasks/{t2.id}/done", follow_redirects=False)
    assert r.status_code == 303 and location_ok(r, "/")


@pytest.mark.parametrize("bad", ["//evil.example", "//evil.example/path", "https://evil.example/", "evil.example", "javascript:alert(1)"])
def test_f4_done_next_rejects_protocol_relative(client, session, bad):
    from app.services import lessons

    t = lessons.add_task(session, "x", D)
    r = client.post(f"/tasks/{t.id}/done", data={"next": bad}, follow_redirects=False)
    assert r.status_code == 303
    assert location_ok(r, "/"), r.headers["location"]
    session.expire_all()
    assert lessons.open_tasks(session) == []


def test_f4_today_shows_tasks_block(client, session):
    from app.services import lessons

    today = real_today()
    over = lessons.add_task(session, "Overdue homework", today - timedelta(days=2))
    now_task = lessons.add_task(session, "Due today thing", today)
    tom = lessons.add_task(session, "Tomorrow thing", today + timedelta(days=1))
    later = lessons.add_task(session, "Weekday thing", today + timedelta(days=2))
    lessons.add_task(session, "Too far thing", today + timedelta(days=3))
    r = client.get("/")
    assert r.status_code == 200
    block = after(r.text, "data-tutor-tasks")
    assert block, "no data-tutor-tasks block"
    low = block.lower()
    for title in ["Overdue homework", "Due today thing", "Tomorrow thing", "Weekday thing"]:
        assert title in block, title
    assert "Too far thing" not in r.text
    assert "overdue" in low and "today" in low and "tomorrow" in low
    assert (today + timedelta(days=2)).strftime("%A").lower() in low
    assert "Done" in block
    for t in (over, now_task, tom, later):
        assert f"/tasks/{t.id}/done" in block


def test_f4_today_has_no_block_without_tasks(client, session):
    from app.services import lessons

    r = client.get("/")
    assert "data-tutor-tasks" not in r.text
    today = real_today()
    lessons.add_task(session, "Far away", today + timedelta(days=10))
    done = lessons.add_task(session, "Finished", today)
    lessons.complete_task(session, done.id, noon(today))
    assert "data-tutor-tasks" not in client.get("/").text


def test_f4_today_done_button_flow(client, session):
    from app.services import lessons

    t = lessons.add_task(session, "Finish me", real_today())
    assert "Finish me" in after(client.get("/").text, "data-tutor-tasks")
    r = client.post(f"/tasks/{t.id}/done", data={"next": "/"}, follow_redirects=True)
    assert r.status_code == 200
    assert "data-tutor-tasks" not in r.text

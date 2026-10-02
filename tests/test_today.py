from datetime import datetime, timedelta, timezone

from sqlmodel import select

from app.models import Card, CardState, ReviewLog, Session as StudySession, Setting, Story, TranslationAttempt
from app.services import today
from app.services.stats import local_date

# Noon on a local calendar day, so results don't depend on the machine's timezone.
NOW = datetime(2026, 10, 2, 12, 0).astimezone().astimezone(timezone.utc)


def add_state(db, state=2, due=NOW - timedelta(hours=1)):
    card = Card(ru="а", en="a")
    db.add(card)
    db.commit()
    cs = CardState(card_id=card.id, state=state, due=due)
    db.add(cs)
    db.commit()
    return cs


def add_log(db, cs, when, duration_ms=None, state_before=2):
    db.add(ReviewLog(card_state_id=cs.id, rating=3, reviewed_at=when, duration_ms=duration_ms,
                     state_before=state_before, due_before=when))
    db.commit()


def add_story(db, title, attempt_at=None, feedback=True):
    story = Story(title=title, source_lang="en", source_text="x")
    db.add(story)
    db.commit()
    if attempt_at:
        db.add(TranslationAttempt(story_id=story.id, text="t", created_at=attempt_at,
                                  feedback_json={"ok": 1} if feedback else None))
        db.commit()
    return story


# --- plan maths ----------------------------------------------------------------


def test_seconds_per_card_defaults_without_history(session):
    assert today.seconds_per_card(session, NOW) == 12.0


def test_seconds_per_card_averages_plus_overhead(session):
    cs = add_state(session)
    for ms in (5000, 9000):
        add_log(session, cs, NOW - timedelta(days=1), ms)
    assert today.seconds_per_card(session, NOW) == 7.0 + 3.0


def test_seconds_per_card_ignores_outliers_missing_and_old(session):
    cs = add_state(session)
    add_log(session, cs, NOW - timedelta(days=1), 5000)
    add_log(session, cs, NOW - timedelta(days=1), 300_000)  # walked away
    add_log(session, cs, NOW - timedelta(days=1), None)
    add_log(session, cs, NOW - timedelta(days=20), 50_000)  # outside the window
    assert today.seconds_per_card(session, NOW) == 8.0


def test_review_block_fits_budget(session):
    for _ in range(10):
        add_state(session)
    block = today.plan_reviews(session, NOW)
    assert (block.queued, block.max_cards, block.planned, block.rollover) == (10, 50, 10, 0)
    assert block.minutes == 2.0


def test_review_block_caps_and_rolls_over(session):
    session.merge(Setting(key="daily_new_cards", value=0))
    session.merge(Setting(key="session_split", value={"srs": 1, "drill_or_story": 8, "scenario": 7}))
    session.commit()
    for _ in range(8):
        add_state(session)
    block = today.plan_reviews(session, NOW)  # 60s / 12s = 5 cards
    assert (block.queued, block.max_cards, block.planned, block.rollover) == (8, 5, 5, 3)
    assert block.minutes == 1.0


def test_review_block_counts_new_cards(session):
    add_state(session, state=0, due=NOW)
    add_state(session)
    block = today.plan_reviews(session, NOW)
    assert (block.queued, block.new) == (2, 1)


# --- writing suggestion --------------------------------------------------------


def test_no_stories_suggests_new(session):
    block = today.plan_writing(session)
    assert block.story is None and block.href == "/workshop/new" and block.minutes == 8


def test_suggests_most_recent_story_with_feedback(session):
    add_story(session, "old", NOW - timedelta(days=3))
    recent = add_story(session, "recent", NOW - timedelta(hours=2))
    add_story(session, "never attempted")
    assert today.plan_writing(session).story.id == recent.id
    assert today.plan_writing(session).href == f"/workshop/{recent.id}"


def test_story_without_feedback_not_suggested(session):
    add_story(session, "pending", NOW, feedback=False)
    assert today.suggest_story(session) is None


def test_latest_attempt_decides(session):
    story = add_story(session, "revised", NOW - timedelta(days=1))
    session.add(TranslationAttempt(story_id=story.id, text="rev", created_at=NOW))  # revision, no feedback yet
    other = add_story(session, "other", NOW - timedelta(hours=5))
    session.commit()
    assert today.suggest_story(session).id == other.id


# --- session tracking ----------------------------------------------------------


def test_start_is_idempotent(session):
    first = today.start_session(session, NOW)
    again = today.start_session(session, NOW + timedelta(minutes=5))
    assert first.id == again.id
    assert first.date == local_date(NOW)


def test_finish_counts_reviews_in_window(session):
    row = today.start_session(session, NOW)
    cs_new, cs_old = add_state(session, state=0), add_state(session)
    add_log(session, cs_old, NOW - timedelta(minutes=1))  # before start
    add_log(session, cs_new, NOW + timedelta(minutes=2), state_before=0)
    add_log(session, cs_new, NOW + timedelta(minutes=3), state_before=0)  # same card twice (learning step)
    add_log(session, cs_old, NOW + timedelta(minutes=4))
    done = today.finish_session(session, NOW + timedelta(minutes=10))
    assert done.id == row.id and done.completed
    assert (done.minutes, done.reviews, done.new_cards) == (10.0, 3, 1)


def test_finish_under_a_minute_refused(session):
    today.start_session(session, NOW)
    assert today.finish_session(session, NOW + timedelta(seconds=59)) is None
    assert today.active_session(session, NOW + timedelta(seconds=59)) is not None
    done = today.finish_session(session, NOW + timedelta(seconds=60))
    assert done is not None and done.reviews == 0


def test_finish_caps_minutes(session):
    today.start_session(session, NOW)
    # Still active at 89 min; minutes are capped at 90 regardless.
    done = today.finish_session(session, NOW + timedelta(minutes=89))
    assert done.minutes == 89.0
    assert today.MAX_SESSION_MINUTES == 90.0


def test_stale_unfinished_session_is_ignored_across_days(session):
    old_start = NOW - timedelta(hours=30)
    session.add(StudySession(date=local_date(old_start), started_at=old_start))
    session.commit()
    assert today.active_session(session, NOW) is None
    assert today.finish_session(session, NOW) is None
    fresh = today.start_session(session, NOW)
    assert fresh.date == local_date(NOW)
    assert len(session.exec(select(StudySession)).all()) == 2


def test_day_summary_only_counts_today(session):
    yesterday = NOW - timedelta(days=1)
    session.add(StudySession(date=local_date(yesterday), started_at=yesterday, minutes=20, completed=True))
    session.commit()
    assert today.day_summary(session, NOW) is None
    today.start_session(session, NOW)
    today.finish_session(session, NOW + timedelta(minutes=5))
    today.start_session(session, NOW + timedelta(minutes=6))
    today.finish_session(session, NOW + timedelta(minutes=9))
    summary = today.day_summary(session, NOW + timedelta(minutes=10))
    assert (summary.sessions, summary.minutes, summary.streak) == (2, 8.0, 2)


# --- routes --------------------------------------------------------------------


def test_page_idle_active_and_done(client, engine):
    from sqlmodel import Session

    page = client.get("/")
    assert page.status_code == 200
    assert "Start session" in page.text and "coming soon" in page.text and "Write a new short story" in page.text

    r = client.post("/today/start", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    page = client.get("/")
    assert "Finish session" in page.text and 'data-started="' in page.text

    # Under a minute: refused, still active.
    r = client.post("/today/finish", follow_redirects=False)
    assert r.headers["location"] == "/?msg=too_short"
    assert "Less than a minute" in client.get("/?msg=too_short").text

    with Session(engine) as db:
        row = db.exec(select(StudySession)).one()
        row.started_at = datetime.now(timezone.utc) - timedelta(minutes=12)
        db.add(row)
        db.commit()
    r = client.post("/today/finish", follow_redirects=False)
    assert r.headers["location"] == "/"
    page = client.get("/")
    assert "Done for today" in page.text and "Start another session" in page.text
    assert "/review" in page.text and "/workshop" in page.text

    client.post("/today/start")
    assert "Finish session" in client.get("/").text
    with Session(engine) as db:
        assert len(db.exec(select(StudySession)).all()) == 2


def test_page_shows_trip_countdown_and_api_notice(client, session, monkeypatch):
    from app.web import templates

    session.merge(Setting(key="trip_date", value=(local_date(datetime.now(timezone.utc)) + timedelta(days=363)).isoformat()))
    session.commit()
    monkeypatch.setitem(templates.env.globals, "ai_enabled", lambda: False)
    text = client.get("/").text
    assert "363 days to Moscow" in text
    assert "AI is off" in text
    monkeypatch.setitem(templates.env.globals, "ai_enabled", lambda: True)
    assert "AI feedback is off" not in client.get("/").text

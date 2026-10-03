from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlmodel import select

from app.db import MIGRATIONS, make_engine, migrate
from app.models import (
    Card, CardState, Category, MedalAward, Mistake, Module, ReviewLog, Session, Setting, Story, TranslationAttempt,
)
from app.services import medals, stats
from sqlmodel import Session as DbSession

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def by_key(session, now=NOW):
    return {s.key: s for s in medals.evaluate(session, now)}


def study_days(session, count, end=None):
    end = end or stats.local_date(NOW)
    for i in range(count):
        session.add(Session(date=end - timedelta(days=i), completed=True, minutes=10))
    session.commit()


def add_cards(session, n):
    for i in range(n):
        session.add(Card(ru=f"слово{i}", en=f"word{i}"))
    session.commit()


def add_attempt(session):
    story = Story(title="t", source_lang="en", source_text="x")
    session.add(story)
    session.commit()
    attempt = TranslationAttempt(story_id=story.id, text="y")
    session.add(attempt)
    session.commit()
    return attempt


def test_twelve_medals_all_locked_on_empty_db(session):
    states = medals.evaluate(session, NOW)
    assert len(states) == 12
    assert not any(s.earned for s in states)
    assert session.exec(select(MedalAward)).all() == []


def test_future_medals_never_earned_and_labelled(session):
    states = by_key(session)
    assert states["roleplay_10"].progress_text == "Arrives with role-play"
    assert states["genitive_plural"].progress_text == "Arrives with drills"
    assert states["motion_verbs"].progress_text == "Arrives with drills"
    assert not any(states[k].available for k in ("roleplay_10", "genitive_plural", "motion_verbs"))


def test_streak_medals(session):
    study_days(session, 7)
    states = by_key(session)
    assert states["streak_7"].earned and not states["streak_30"].earned
    assert states["streak_30"].progress_text == "7 / 30 days"
    study_days(session, 30, end=stats.local_date(NOW) - timedelta(days=100))
    assert by_key(session)["streak_30"].earned


def test_card_count_medals(session):
    add_cards(session, 100)
    states = by_key(session)
    assert states["cards_100"].earned and not states["cards_500"].earned
    assert states["cards_500"].pct == 20


def test_first_story_needs_an_attempt(session):
    session.add(Story(title="t", source_lang="en", source_text="x"))
    session.commit()
    assert not by_key(session)["first_story"].earned
    add_attempt(session)
    assert by_key(session)["first_story"].earned


def test_self_corrected_story(session):
    attempt = add_attempt(session)

    def mistake(fixed):
        session.add(Mistake(module=Module.story, ref_id=attempt.id, category=Category.case, wrong="a", right="b", self_corrected=fixed))
        session.commit()

    assert not by_key(session)["self_fixed"].earned  # no mistakes at all
    mistake(True)
    mistake(None)
    assert not by_key(session)["self_fixed"].earned  # one unfixed
    other = add_attempt(session)
    session.add(Mistake(module=Module.story, ref_id=other.id, category=Category.case, wrong="a", right="b", self_corrected=True))
    session.commit()
    assert by_key(session)["self_fixed"].earned


def add_reviews(session, count, again=0, at=NOW):
    card = Card(ru="к", en="c")
    session.add(card)
    session.commit()
    cs = CardState(card_id=card.id)
    session.add(cs)
    session.commit()
    for i in range(count):
        session.add(ReviewLog(card_state_id=cs.id, rating=1 if i < again else 3, reviewed_at=at, state_before=2, due_before=at))
    session.commit()


def test_flawless_day(session):
    add_reviews(session, 12, again=1)
    assert not by_key(session)["flawless"].earned
    add_reviews(session, 9, at=NOW - timedelta(days=3))
    assert not by_key(session)["flawless"].earned
    assert by_key(session)["flawless"].current == 9
    add_reviews(session, 10, at=NOW - timedelta(days=6))
    assert by_key(session)["flawless"].earned


def test_hours_studied(session):
    session.add(Session(date=date(2026, 9, 1), minutes=5999))
    session.commit()
    states = by_key(session)
    assert not states["hours_100"].earned
    assert states["hours_100"].progress_text == "99.9 / 100 hours"
    session.add(Session(date=date(2026, 9, 2), minutes=1))
    session.commit()
    assert by_key(session)["hours_100"].earned


def test_trip_day(session):
    session.delete(session.get(Setting, "trip_date"))  # the seed ships a default
    session.commit()
    assert by_key(session)["trip_day"].progress_text == "Set your trip date in Settings"
    session.add(Setting(key="trip_date", value="2026-10-10"))
    session.commit()
    states = by_key(session)
    assert not states["trip_day"].earned and states["trip_day"].progress_text == "7 days to go"
    session.get(Setting, "trip_date").value = "2026-10-03"
    session.add(session.get(Setting, "trip_date"))
    session.commit()
    assert by_key(session)["trip_day"].earned


def test_awards_persist_and_are_idempotent(session):
    add_cards(session, 100)
    first = by_key(session)["cards_100"]
    later = NOW + timedelta(days=5)
    again = by_key(session, later)["cards_100"]
    assert first.earned_at == again.earned_at
    assert len(session.exec(select(MedalAward)).all()) == 1


def test_earned_stays_earned_after_streak_breaks(session):
    study_days(session, 7)
    assert by_key(session)["streak_7"].earned
    for row in session.exec(select(Session)).all():
        session.delete(row)
    session.commit()
    assert by_key(session)["streak_7"].earned


def test_pending_then_seen_flow(client, session):
    add_cards(session, 100)
    data = client.get("/medals/pending").json()["medals"]
    assert [m["key"] for m in data] == ["cards_100"]
    assert "<svg" in data[0]["art"] and data[0]["ru"].startswith("Сто")
    assert client.get("/medals/pending").json()["medals"]  # still pending until seen
    assert client.post("/medals/cards_100/seen").json() == {"ok": True}
    assert client.get("/medals/pending").json()["medals"] == []
    assert client.post("/medals/streak_30/seen").status_code == 404


def test_pending_newest_first(session):
    session.add(MedalAward(key="cards_100", earned_at=NOW - timedelta(days=2)))
    session.add(MedalAward(key="first_story", earned_at=NOW - timedelta(days=1)))
    session.commit()
    assert [s.key for s in medals.pending(session, NOW)] == ["first_story", "cards_100"]


def test_dashboard_renders_medallions(client, session):
    add_cards(session, 100)
    html = client.get("/dashboard").text
    assert 'id="medals"' in html and "Medallions" in html
    assert html.count('class="cell ') == 12
    assert "1 of 12 earned" in html or "1 of 12" in html.replace("\n", " ")
    assert "Arrives with drills" in html and "Arrives with role-play" in html
    assert 'data-medal="cards_100"' in html
    assert "medals.css" in html


def test_migration_creates_medal_awards_on_old_db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:  # a database as it was at schema version 5
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version VALUES (5)"))
    assert migrate(engine) == len(MIGRATIONS)
    with DbSession(engine) as s:
        s.add(MedalAward(key="cards_100"))
        s.commit()
        assert s.exec(text("SELECT key, seen FROM medal_awards")).one() == ("cards_100", 0)

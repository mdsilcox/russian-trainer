"""Data builders for the T-C hidden tests: ORM inserts, service calls and raw SQL inserts."""

import random
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import text
from sqlmodel import select

# A fixed "now": noon local time on a fixed day, so nothing depends on the machine's time zone.
NOON = datetime.combine(date(2026, 10, 3), time(12, 0)).astimezone().astimezone(timezone.utc)
TODAY = date(2026, 10, 3)

SOURCE_TABLES = ("sessions", "review_log", "drill_answers", "translation_attempts", "messages", "input_log")


def at_local(day: date, hour: int = 12, minute: int = 0) -> datetime:
    """A UTC datetime that is `hour:minute` on `day` in local time."""
    return datetime.combine(day, time(hour, minute)).astimezone().astimezone(timezone.utc)


def naive_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def sql_ts(dt: datetime) -> str:
    return naive_utc(dt).strftime("%Y-%m-%d %H:%M:%S.%f")


# --- ORM builders -------------------------------------------------------------------------


def add_session(db, day, minutes, completed, reviews=0, new_cards=0, started_at=None):
    from app.models import Session

    row = Session(date=day, minutes=minutes, completed=completed, reviews=reviews, new_cards=new_cards,
                  started_at=started_at or at_local(day, 9))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def new_card_state(db, ru="а"):
    from app.models import CardState
    from app.services import cards

    card = cards.create_card(db, ru=ru, en="a")
    return db.exec(select(CardState).where(CardState.card_id == card.id)).one()


def add_review(db, cs, day, rating=3, state_before=2, hour=12):
    from app.models import ReviewLog

    when = at_local(day, hour)
    row = ReviewLog(card_state_id=cs.id, rating=rating, reviewed_at=when, state_before=state_before, due_before=when)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def add_input(db, day, minutes, kind="reading"):
    from app.models import InputLog

    row = InputLog(date=day, minutes=minutes, kind=kind, title="x")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def add_story(db, title="s"):
    from app.models import Story

    story = Story(title=title, source_lang="en", source_text="x")
    db.add(story)
    db.commit()
    db.refresh(story)
    return story


def add_attempt(db, story, day, hour=12):
    from app.models import TranslationAttempt

    row = TranslationAttempt(story_id=story.id, text="t", created_at=at_local(day, hour))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def add_drill_set(db):
    from app.models import Category, DrillSet

    ds = DrillSet(category=Category.case, items_json=[])
    db.add(ds)
    db.commit()
    db.refresh(ds)
    return ds


def add_drill_answer(db, ds, day, correct=True, idx=0, hour=12):
    from app.models import DrillAnswer

    row = DrillAnswer(drill_set_id=ds.id, item_idx=idx, answer="x", correct=correct, created_at=at_local(day, hour))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def add_conversation(db):
    from app.models import Conversation, Scenario

    n = len(db.exec(select(Scenario.id)).all())
    sc = Scenario(slug=f"sc{n}", title="T", setting="s", partner_role="p", persona="p", opening_ru="Привет")
    db.add(sc)
    db.commit()
    db.refresh(sc)
    conv = Conversation(scenario_id=sc.id, level=1, goals_met_json=[])
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def add_message(db, conv, role, day, hour=12):
    from app.models import Message

    row = Message(conversation_id=conv.id, role=role, content="x", created_at=at_local(day, hour))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def all_kinds_world(db, day=TODAY):
    """One row of every source kind on `day` (ORM). Returns a dict of the created rows."""
    cs = new_card_state(db)
    story = add_story(db)
    ds = add_drill_set(db)
    conv = add_conversation(db)
    return dict(
        session=add_session(db, day, 25.0, True, reviews=3, new_cards=1),
        review=add_review(db, cs, day, rating=3, state_before=2),
        input=add_input(db, day, 30, "listening"),
        attempt=add_attempt(db, story, day),
        drill=add_drill_answer(db, ds, day, True),
        message=add_message(db, conv, "user", day),
        partner=add_message(db, conv, "partner", day),
        story=story, conv=conv, cs=cs, ds=ds,
    )


def random_world(db, seed, today=TODAY, span=60):
    """A seeded mix: completed and incomplete sessions (all with minutes), input, reviews, attempts."""
    rng = random.Random(seed)
    cs = new_card_state(db)
    story = add_story(db)
    for back in range(span):
        day = today - timedelta(days=back)
        for _ in range(rng.choice([0, 0, 1, 1, 2])):
            add_session(db, day, rng.choice([0, 5, 12.5, 20, 30.5, 45, 7.25]), rng.random() < 0.6,
                        reviews=rng.randint(0, 40), new_cards=rng.randint(0, 10))
        if rng.random() < 0.3:
            add_input(db, day, rng.randint(5, 90), rng.choice(["reading", "listening", "watching"]))
        if rng.random() < 0.2:
            for _ in range(rng.randint(1, 14)):
                add_review(db, cs, day, rating=rng.choice([1, 2, 3, 3, 4]), hour=rng.randint(8, 20))
        if rng.random() < 0.05:
            add_attempt(db, story, day)
    return cs


def delete_sources(db):
    """Raw SQL, bypassing the ORM: empty the six source tables."""
    for table in SOURCE_TABLES:
        db.exec(text(f"DELETE FROM {table}"))
    db.commit()


# --- raw SQL builders (bypass the ORM) --------------------------------------------------------


def raw_session(conn, day, minutes, completed, reviews=0, new_cards=0):
    conn.execute(text(
        "INSERT INTO sessions (date, started_at, minutes, reviews, new_cards, drills, scenario_turns, completed) "
        "VALUES (:d, :s, :m, :r, :n, 0, 0, :c)"),
        dict(d=day.isoformat(), s=sql_ts(at_local(day, 9)), m=minutes, r=reviews, n=new_cards, c=int(completed)))


def raw_review(conn, cs_id, day, rating=3, state_before=2, hour=12):
    when = sql_ts(at_local(day, hour))
    conn.execute(text(
        "INSERT INTO review_log (card_state_id, rating, reviewed_at, state_before, due_before) "
        "VALUES (:c, :r, :w, :s, :w)"), dict(c=cs_id, r=rating, w=when, s=state_before))


def raw_input(conn, day, minutes, kind="reading"):
    conn.execute(text(
        "INSERT INTO input_log (date, minutes, kind, title, created_at) VALUES (:d, :m, :k, 'x', :t)"),
        dict(d=day.isoformat(), m=minutes, k=kind, t=sql_ts(at_local(day, 12))))


def raw_story(conn):
    conn.execute(text("INSERT INTO stories (title, source_lang, source_text, created_at) VALUES ('s', 'en', 'x', :t)"),
                 dict(t=sql_ts(NOON)))
    return conn.execute(text("SELECT MAX(id) FROM stories")).scalar()


def raw_attempt(conn, story_id, day):
    conn.execute(text(
        "INSERT INTO translation_attempts (story_id, text, created_at) VALUES (:s, 't', :t)"),
        dict(s=story_id, t=sql_ts(at_local(day, 12))))

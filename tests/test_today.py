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

    from app.services import plan as plan_svc

    with Session(engine) as db:
        plan_svc.set_rhythm(db, ["writing"] * 7)

    page = client.get("/")
    assert page.status_code == 200
    assert "Start session" in page.text and "Speaking" in page.text and "Write a new short story" in page.text

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


# --- header extras -------------------------------------------------------------


def _trip(session, days):
    session.merge(Setting(key="trip_date", value=(local_date(NOW) + timedelta(days=days)).isoformat()))
    session.commit()


def test_trip_progress_months(session):
    _trip(session, 363)
    assert today.trip_progress(session, NOW).month == 1
    _trip(session, 30)
    assert today.trip_progress(session, NOW).month == 12
    _trip(session, 700)
    assert today.trip_progress(session, NOW).month == 1
    _trip(session, -1)
    assert today.trip_progress(session, NOW) is None


def test_weak_spots_only_recent(session):
    from app.models import Category, Mistake, Module

    assert today.weak_spots(session, NOW) == []
    session.add(Mistake(module=Module.manual, wrong='x', right='y', category=Category.case, created_at=NOW - timedelta(days=1)))
    session.add(Mistake(module=Module.manual, wrong='x', right='y', category=Category.case, created_at=NOW - timedelta(days=2)))
    session.add(Mistake(module=Module.manual, wrong='x', right='y', category=Category.stress, created_at=NOW - timedelta(days=90)))
    session.commit()
    spots = today.weak_spots(session, NOW)
    assert [(s.label, s.count) for s in spots] == [("Cases", 2)]


def test_word_of_the_day_changes_daily_and_skips_suspended(session):
    day = local_date(NOW)
    assert today.word_of_the_day(session, day) is None
    for i in range(5):
        session.add(Card(ru=f"слово{i}", en=f"word {i}"))
    session.add(Card(ru="скрыт", en="hidden", suspended=True))
    session.commit()
    start = day - timedelta(days=day.toordinal() % 5)  # cycles align to the calendar
    picks = [today.word_of_the_day(session, start + timedelta(days=d)).ru for d in range(30)]
    assert "скрыт" not in picks
    assert all(a != b for a, b in zip(picks, picks[1:]))  # never the same two days running
    assert sorted(picks.count(f"слово{i}") for i in range(5)) == [6] * 5  # each card in turn, evenly
    assert today.word_of_the_day(session, start).ru == picks[0]  # steady within the day


def test_word_of_the_day_prefers_cards_still_learning(session):
    day = local_date(NOW)
    learning = []
    for i in range(10):
        card = Card(ru=f"учу{i}", en=f"learning {i}")
        session.add(card)
        session.flush()
        session.add(CardState(card_id=card.id, state=2, stability=3.0))
        learning.append(card.ru)
    for i in range(10):
        card = Card(ru=f"знаю{i}", en=f"known {i}")
        session.add(card)
        session.flush()
        session.add(CardState(card_id=card.id, state=2, stability=90.0))
    session.commit()
    picks = {today.word_of_the_day(session, day + timedelta(days=d)).ru for d in range(20)}
    assert picks <= set(learning)


# --- flair: Moscow clock and growth ------------------------------------------------


def test_growth_stage_boundaries():
    assert today.growth_stage(None) == 0
    assert today.growth_stage(365) == 0
    assert today.growth_stage(293) == 0
    assert today.growth_stage(292) == 1
    assert today.growth_stage(220) == 1
    assert today.growth_stage(219) == 2
    assert today.growth_stage(147) == 2
    assert today.growth_stage(146) == 3
    assert today.growth_stage(74) == 3
    assert today.growth_stage(73) == 4
    assert today.growth_stage(1) == 4
    assert today.growth_stage(0) == 4
    assert today.growth_stage(-10) == 4
    assert today.growth_stage(900) == 0


def test_sky_phase_hours():
    assert [today.sky_phase(h) for h in (4, 5, 7, 8, 17, 18, 20, 21, 23, 0)] == [
        "night", "dawn", "dawn", "day", "day", "dusk", "dusk", "night", "night", "night"]


def test_moscow_clock_is_utc_plus_three():
    c = today.moscow_clock(datetime(2026, 10, 3, 21, 30, tzinfo=timezone.utc))
    assert (c.time, c.phase) == ("00:30", "night")
    c = today.moscow_clock(datetime(2026, 7, 1, 5, 5, tzinfo=timezone.utc))
    assert (c.time, c.phase) == ("08:05", "day")
    assert today.moscow_clock(datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc)).phase == "dawn"


def test_page_has_clock_vine_and_ink_word(client, session):
    session.add(Card(ru="вокзал", ru_stressed="вокза́л", en="railway station"))
    session.merge(Setting(key="trip_date", value=(local_date(datetime.now(timezone.utc)) + timedelta(days=100)).isoformat()))
    session.commit()
    text = client.get("/").text
    assert "data-moscow-clock" in text and "В Москве́ сейча́с" in text
    assert 'class="gv st3"' in text
    assert "ink-base" in text and "вокза́л" in text


def test_ink_stress_keeps_vowels_in_script_and_hyphenated_words_whole():
    from app.web import ink_stress, is_phrase

    html = str(ink_stress("говорю́ по-ру́сски <b>"))
    assert "́" not in html
    assert 'говор<span class="ink-acc">ю</span>' in html
    assert '<span class="ink-w">по-р<span class="ink-acc">у</span>сски</span>' in html
    assert "&lt;b&gt;" in html
    assert is_phrase("Я тут") and not is_phrase("спаси́бо")


# --- block II: writing or drills ---------------------------------------------------


def _drill_day(weekday):
    """A noon moment on the given weekday (0 = Monday) near NOW, in local time."""
    day = NOW.astimezone()
    return day + timedelta(days=(weekday - day.weekday()) % 7)


def _add_weak_topic(db):
    from app.models import Category, Mistake, Module

    db.add(Mistake(module=Module.story, category=Category.case, subcategory="genitive plural", wrong="a", right="b"))
    db.commit()


def _rhythm_for(session, kind):
    """Make every weekday a `kind` day, so tests don't depend on the weekday."""
    from app.services import plan as plan_svc

    plan_svc.set_rhythm(session, [kind] * 7)


LEAD = "Today's lead"


def test_block_two_is_writing_only_with_nothing_to_drill(session, monkeypatch):
    monkeypatch.setattr(today.drills, "plan_next", lambda db, now=None: ("none", []))
    _rhythm_for(session, "grammar")
    plan = today.build_plan(session, _drill_day(0))
    assert plan.drills is None and not plan.drills_first and plan.mode == "writing"


def test_grammar_and_interleaved_days_lead_with_drills(session):
    _add_weak_topic(session)
    for kind in ("grammar", "interleaved"):
        _rhythm_for(session, kind)
        plan = today.build_plan(session, _drill_day(1))
        assert plan.mode == "drills" and plan.drills_first and plan.lead and not plan.speaking_lead
        assert plan.drills.kind == "focused" and plan.drills.href == "/drills" and plan.drills.open is None
        assert plan.drills.minutes == plan.writing.minutes


def test_rhythm_not_weekday_decides_the_lead(session):
    from app.services import plan as plan_svc

    _add_weak_topic(session)
    plan_svc.set_rhythm(session, ["grammar", "writing"] * 3 + ["light"])
    assert today.build_plan(session, _drill_day(0)).mode == "drills"
    assert today.build_plan(session, _drill_day(1)).mode == "writing"
    assert today.build_plan(session, _drill_day(6)).mode == "light"


def test_open_set_counts_even_without_a_plan(session):
    from app.models import Category, DrillSet

    _rhythm_for(session, "grammar")
    session.add(DrillSet(category=Category.case, items_json=[{"topic_label": "Genitive plural"}], kind="mixed"))
    session.commit()
    plan = today.build_plan(session, _drill_day(1))
    assert plan.drills.open is not None and plan.drills.kind == "mixed" and plan.drills.labels == ["Genitive plural"]


def _page_on(client, session, monkeypatch, kind, weekday=1):
    _rhythm_for(session, kind)
    monkeypatch.setattr(today, "_now", lambda now: _drill_day(weekday).astimezone(timezone.utc))
    return client.get("/").text


def test_page_grammar_day_drills_lead_writing_alt(client, session, monkeypatch):
    _add_weak_topic(session)
    page = _page_on(client, session, monkeypatch, "grammar")
    assert "Start drills" in page and "write a new story" in page and "Mixed drills" not in page
    assert page.index("Start drills") < page.index("write a new story")
    assert "Tuesday: Grammar drills" in page


def test_page_interleaved_day_says_mixed(client, session, monkeypatch):
    _add_weak_topic(session)
    page = _page_on(client, session, monkeypatch, "interleaved")
    assert "Mixed drills" in page and "A mixed set is best today" in page and "Start drills" in page


def test_page_writing_and_translation_days_lead_with_writing(client, session, monkeypatch):
    _add_weak_topic(session)
    page = _page_on(client, session, monkeypatch, "writing")
    assert page.index("New story") < page.index("do grammar drills")
    assert "check the stress" not in page
    page = _page_on(client, session, monkeypatch, "translation")
    assert "Translate a short story and check the stress" in page
    assert page.index("New story") < page.index("do grammar drills")


def test_page_input_day(client, session, monkeypatch):
    from app.services import shelf

    shelf.log_minutes(session, 25, "reading", now=_drill_day(1))
    page = _page_on(client, session, monkeypatch, "input")
    assert "Reading and listening" in page and 'href="/shelf"' in page and "25" in page
    assert "write a new story" in page


def test_page_light_day(client, session, monkeypatch):
    page = _page_on(client, session, monkeypatch, "light")
    assert "Light day: just reviews and something easy to watch" in page and 'href="/shelf"' in page
    assert "write a new story" in page


def test_page_roleplay_day_makes_block_three_the_lead(client, session, monkeypatch):
    from app.services import scenarios

    scenarios.seed(session)
    page = _page_on(client, session, monkeypatch, "roleplay")
    assert page.count(LEAD) == 1
    assert "Role-play is today" in page and 'href="/scenarios/' in page and "all scenarios" in page
    assert page.index("New story") < page.index(LEAD) < page.index("Role-play is today")


def test_page_non_roleplay_day_leads_in_block_two_only(client, session, monkeypatch):
    page = _page_on(client, session, monkeypatch, "writing")
    assert page.count(LEAD) == 1 and page.index(LEAD) < page.index("New story")
    assert "Role-play is today" not in page


# --- block III: scenario suggestion ----------------------------------------------------


def test_suggest_scenario_none_when_unseeded(session):
    assert today.suggest_scenario(session) is None
    assert today.plan_speaking(session).href == "/scenarios"


def test_suggest_scenario_never_practised_first_then_oldest(session):
    from app.models import Conversation, Scenario
    from app.services import scenarios

    scenarios.seed(session)
    ordered = session.exec(select(Scenario).order_by(Scenario.sort)).all()
    assert today.suggest_scenario(session).slug == ordered[0].slug
    # first two practiced: the third, never practiced, wins
    session.add(Conversation(scenario_id=ordered[0].id, started_at=NOW - timedelta(days=1)))
    session.add(Conversation(scenario_id=ordered[1].id, started_at=NOW - timedelta(days=5)))
    session.commit()
    assert today.suggest_scenario(session).slug == ordered[2].slug
    # everything practiced: the one practiced longest ago wins (ordered[1], 5 days)
    for sc in ordered[2:]:
        session.add(Conversation(scenario_id=sc.id, started_at=NOW - timedelta(days=2)))
    session.commit()
    assert today.suggest_scenario(session).slug == ordered[1].slug
    assert today.plan_speaking(session).href == f"/scenarios/{ordered[1].slug}"


# --- header: day focus, month, check-in -------------------------------------------------


def _seed_plan(session, trip):
    from app.services import plan as plan_svc

    session.merge(Setting(key="trip_date", value=trip.isoformat()))
    session.commit()
    plan_svc.seed(session, NOW)
    return plan_svc.current_month(session, NOW)


def test_header_shows_focus_and_month_link(client, session, monkeypatch):
    from app.services import plan as plan_svc

    month = _seed_plan(session, local_date(NOW) + timedelta(days=200))
    for m in plan_svc.months(session):  # earlier months already checked in
        if m.month_idx < month.month_idx:
            plan_svc.save_review(session, m, 3, "", NOW)
    page = _page_on(client, session, monkeypatch, "light", weekday=4)
    assert "Friday: Light review" in page
    assert "This month:" in page and month.title in page and 'href="/plan"' in page
    assert "Time to check in" not in page


def test_header_without_plan_has_no_month_line(client, session, monkeypatch):
    page = _page_on(client, session, monkeypatch, "light", weekday=4)
    assert "Friday: Light review" in page and "This month:" not in page


def test_check_in_notice_when_review_due(client, session, monkeypatch):
    from app.services import plan as plan_svc

    month = _seed_plan(session, local_date(NOW) + timedelta(days=200))
    start, end = plan_svc.month_range(month)
    day = datetime.combine(end - timedelta(days=1), datetime.min.time()).replace(hour=12).astimezone()
    monkeypatch.setattr(today, "_now", lambda now: day.astimezone(timezone.utc))
    page = client.get("/").text
    assert "Time to check in on" in page and month.title in page
    assert today.build_plan(session, day).review_title == month.title


# --- the unit step leads block II ------------------------------------------------------------


def _seed_units(session):
    from app.services import plan as plan_svc, unit_content, units

    session.merge(Setting(key="trip_date", value=(local_date(NOW) + timedelta(days=200)).isoformat()))
    session.commit()
    plan_svc.seed(session, NOW)
    for m in plan_svc.months(session):  # no check-in notice in the way
        plan_svc.save_review(session, m, 3, "", NOW)
    units.seed_curriculum(session)
    unit_content.seed_demo(session)
    return units.current_unit(session, NOW)


def test_unit_step_leads_by_day_kind(session):
    from app.services import plan as plan_svc, units

    unit = _seed_units(session)
    assert unit is not None
    plan_svc.set_rhythm(session, ["grammar"] * 7)
    plan = today.build_plan(session, _drill_day(1))
    assert plan.unit.id == unit.id and plan.unit_step.key == "learn" and plan.unit_step.href == f"/learn/{unit.id}/lesson"
    units.finish_step(session, unit, "learn", 1.0, now=NOW)
    plan_svc.set_rhythm(session, ["input"] * 7)
    plan = today.build_plan(session, _drill_day(1))
    assert plan.unit_step.key == "listening" and plan.unit_step.href.endswith("/play/listening")
    assert plan.unit_alt is not None and plan.unit_alt.key != "listening"
    plan_svc.set_rhythm(session, ["light"] * 7)
    plan = today.build_plan(session, _drill_day(1))
    assert plan.unit_step is None and plan.mode == "light"


def test_page_unit_step_card_and_alternative(client, session, monkeypatch):
    unit = _seed_units(session)
    page = _page_on(client, session, monkeypatch, "grammar")
    assert unit.title in page and f'href="/learn/{unit.id}/lesson"' in page
    assert "Or " in page and "Grammar drills" not in page.split("numeral\">II")[1].split("numeral\">III")[0].split("plan-body")[0]


def test_roleplay_day_keeps_block_three_as_lead_with_unit(client, session, monkeypatch):
    _seed_units(session)
    page = _page_on(client, session, monkeypatch, "roleplay")
    assert page.count(LEAD) == 1 and page.index(LEAD) > page.index("numeral\">III") - 400


def test_revisits_line(client, session, monkeypatch):
    from app.models import TopicReview
    from app.services import units

    unit = _seed_units(session)
    page = _page_on(client, session, monkeypatch, "grammar")
    assert "Revisits due" not in page
    session.add(TopicReview(unit_id=unit.id, step=2, due=local_date(NOW) - timedelta(days=1)))
    session.commit()
    assert [u.id for u in units.revisits_due(session, NOW)] == [unit.id]
    page = _page_on(client, session, monkeypatch, "grammar")
    assert "Revisits due" in page and f'href="/learn/{unit.id}/play/revisit?variant=2"' in page


def test_no_units_falls_back_to_rhythm_block(client, session, monkeypatch):
    page = _page_on(client, session, monkeypatch, "writing")
    plan = today.build_plan(session, _drill_day(1))
    assert plan.unit is None and plan.unit_step is None and not plan.revisits
    assert "New story" in page and "Revisits due" not in page

from datetime import date, datetime, timedelta, timezone

from app.models import (
    Card, CardState, Category, InputLog, Mistake, Module, ReviewLog, Session as StudySession,
)
from app.services import stats

# Noon on Friday 2026-10-02, local time, so results don't depend on the machine's timezone.
NOW = datetime(2026, 10, 2, 12, 0).astimezone()
TODAY = date(2026, 10, 2)
THIS_MONDAY = date(2026, 9, 28)


def at(day: date, hour: int = 12) -> datetime:
    return datetime(day.year, day.month, day.day, hour).astimezone().astimezone(timezone.utc)


def add_mistake(session, category, day, module=Module.story, hour=12):
    session.add(Mistake(module=module, category=category, wrong="x", right="y", created_at=at(day, hour)))
    session.commit()


def add_card_state(session, source=Module.story, state=2, due=NOW):
    card = Card(ru="а", en="a", source_module=source)
    session.add(card)
    session.commit()
    cs = CardState(card_id=card.id, state=state, due=due.astimezone(timezone.utc))
    session.add(cs)
    session.commit()
    return cs


def add_reviews(session, cs, ratings, state_before=2, when=NOW):
    for rating in ratings:
        session.add(
            ReviewLog(
                card_state_id=cs.id, rating=rating, state_before=state_before,
                reviewed_at=when.astimezone(timezone.utc), due_before=when.astimezone(timezone.utc),
            )
        )
    session.commit()


# --- nice_axis -----------------------------------------------------------------------

def test_nice_axis_rounds_up_to_round_steps():
    assert stats.nice_axis(0) == (1, [0, 1])
    assert stats.nice_axis(4) == (4, [0, 1, 2, 3, 4])
    assert stats.nice_axis(9) == (10, [0, 5, 10])
    assert stats.nice_axis(23) == (30, [0, 10, 20, 30])
    top, ticks = stats.nice_axis(101)
    assert top >= 101 and ticks[0] == 0 and ticks[-1] == top


# --- mistake trend -------------------------------------------------------------------

def test_mistake_trend_empty(session):
    trend = stats.mistake_trend(session, NOW)
    assert trend.total == 0
    assert len(trend.weeks) == 12 and trend.series == []
    assert trend.weeks[-1].start == THIS_MONDAY
    assert trend.weeks[0].start == THIS_MONDAY - timedelta(weeks=11)


def test_mistake_trend_week_boundaries(session):
    add_mistake(session, Category.aspect, THIS_MONDAY)  # Monday: this week
    add_mistake(session, Category.aspect, THIS_MONDAY - timedelta(days=1))  # Sunday: last week
    add_mistake(session, Category.aspect, THIS_MONDAY - timedelta(days=1), hour=23)
    trend = stats.mistake_trend(session, NOW)
    assert [w.total for w in trend.weeks[-2:]] == [2, 1]
    assert trend.total == 3


def test_mistake_trend_window_edges(session):
    first = THIS_MONDAY - timedelta(weeks=11)
    add_mistake(session, Category.case, first)  # first day of the window
    add_mistake(session, Category.case, first - timedelta(days=1))  # just before: dropped
    add_mistake(session, Category.case, TODAY + timedelta(days=1))  # future: dropped
    trend = stats.mistake_trend(session, NOW)
    assert trend.total == 1
    assert trend.weeks[0].total == 1


def test_mistake_trend_splits_drills_from_real_use(session):
    add_mistake(session, Category.aspect, TODAY, module=Module.story)
    add_mistake(session, Category.aspect, TODAY, module=Module.drill)
    add_mistake(session, Category.aspect, TODAY, module=Module.drill)
    trend = stats.mistake_trend(session, NOW)
    (segment,) = trend.weeks[-1].segments
    assert (segment.real, segment.drill) == (1, 2)
    assert segment.series.label == "Verb aspect"
    assert segment.series.color != segment.series.tint


def test_mistake_trend_ranks_series_and_groups_the_rest(session):
    categories = list(Category)  # 11
    for rank, category in enumerate(categories):
        for _ in range(len(categories) - rank):
            add_mistake(session, category, TODAY)
    trend = stats.mistake_trend(session, NOW)
    assert len(trend.series) == stats.MISTAKE_SERIES + 1
    assert trend.series[0].label == stats.category_label(categories[0])
    assert trend.series[-1].label == "Other"
    assert trend.series[-1].total == sum(len(categories) - r for r in range(stats.MISTAKE_SERIES, len(categories)))
    assert len({s.color for s in trend.series}) == len(trend.series)
    assert trend.axis_max >= trend.weeks[-1].total
    assert len(trend.weeks[-1].segments) == len(trend.series)


# --- retention by source ---------------------------------------------------------------

def test_retention_by_source_excludes_new_cards_and_small_sources(session):
    story = add_card_state(session, Module.story)
    add_reviews(session, story, [1, 2, 3, 4, 3])  # 4 of 5 kept
    add_reviews(session, story, [1, 1], state_before=stats.srs.NEW)  # first sight: ignored
    drill = add_card_state(session, Module.drill)
    add_reviews(session, drill, [3, 3, 3, 3])  # only 4 reviews: hidden
    data = stats.retention_by_source(session, NOW)
    assert [(r.source, r.reviews, r.kept) for r in data.rows] == [(Module.story, 5, 4)]
    assert data.rows[0].rate == 0.8
    assert [(r.source, r.reviews) for r in data.hidden] == [(Module.drill, 4)]


def test_retention_by_source_window_and_ordering(session):
    media = add_card_state(session, Module.media)
    manual = add_card_state(session, Module.manual)
    add_reviews(session, media, [2] * 5)
    add_reviews(session, manual, [1] * 5)
    add_reviews(session, manual, [3] * 5, when=NOW - timedelta(days=31))  # outside 30 days
    data = stats.retention_by_source(session, NOW)
    assert [r.source for r in data.rows] == [Module.manual, Module.media]  # enum order
    assert data.rows[0].rate == 0.0 and data.rows[1].rate == 1.0
    assert data.hidden == []


def test_retention_by_source_empty(session):
    data = stats.retention_by_source(session, NOW)
    assert data.rows == [] and data.hidden == []


# --- forecast --------------------------------------------------------------------------

def test_forecast_days_buckets(session):
    add_card_state(session, due=NOW - timedelta(days=3))  # overdue counts today
    add_card_state(session, due=NOW)
    add_card_state(session, due=NOW + timedelta(days=1))
    add_card_state(session, due=NOW + timedelta(days=1))
    add_card_state(session, due=NOW + timedelta(days=29))
    add_card_state(session, due=NOW + timedelta(days=30))  # beyond the window
    add_card_state(session, state=0, due=NOW)  # new cards are not reviews
    fc = stats.forecast_days(session, NOW)
    assert len(fc.days) == 30
    assert fc.days[0].day == TODAY and fc.days[29].day == TODAY + timedelta(days=29)
    assert [fc.days[i].count for i in (0, 1, 2, 29)] == [2, 2, 0, 1]
    assert fc.total == 5
    assert fc.axis_max >= 2 and fc.ticks[0] == 0


def test_forecast_days_empty(session):
    fc = stats.forecast_days(session, NOW)
    assert fc.total == 0 and len(fc.days) == 30


# --- heatmap ---------------------------------------------------------------------------

def test_heatmap_combines_study_and_input_minutes(session):
    session.add(StudySession(date=TODAY, minutes=10.0))
    session.add(StudySession(date=TODAY, minutes=5.0))
    session.add(InputLog(date=TODAY, minutes=25, kind="reading"))
    session.add(InputLog(date=TODAY - timedelta(days=1), minutes=8, kind="listening"))
    session.commit()
    hm = stats.practice_heatmap(session, NOW)
    cells = {c.day: c for week in hm.weeks for c in week if c}
    today = cells[TODAY]
    assert (today.study, today.input, today.total) == (15.0, 25, 40.0)
    assert today.level == 4 and hm.busiest == 40.0
    assert cells[TODAY - timedelta(days=1)].level == 1  # 8 of 40 minutes
    assert cells[TODAY - timedelta(days=2)].level == 0
    assert hm.total_minutes == 48.0 and hm.active_days == 2


def test_heatmap_shape(session):
    session.add(StudySession(date=TODAY, minutes=1.0))
    session.commit()
    hm = stats.practice_heatmap(session, NOW)
    assert len(hm.weeks) == 26 and all(len(w) == 7 for w in hm.weeks)
    assert hm.weeks[0][0].day == THIS_MONDAY - timedelta(weeks=25)  # Monday first
    last = hm.weeks[-1]
    assert last[0].day == THIS_MONDAY and last[4].day == TODAY
    assert last[5] is None and last[6] is None  # days to come
    assert hm.month_labels and all(0 <= col < 26 for col, _ in hm.month_labels)


def test_heatmap_ignores_days_outside_window(session):
    old = THIS_MONDAY - timedelta(weeks=26)
    session.add(StudySession(date=old, minutes=30.0))
    session.add(InputLog(date=old, minutes=30, kind="reading"))
    session.commit()
    hm = stats.practice_heatmap(session, NOW)
    assert hm.total_minutes == 0 and hm.active_days == 0


# --- page ------------------------------------------------------------------------------

def test_dashboard_renders_empty_states(client):
    html = client.get("/dashboard").text
    assert "Mistakes appear here once you've had feedback on a story or a drill" in html
    assert "Retention by source appears here" in html
    assert "Due reviews appear here" in html
    assert "Your practice days appear here" in html
    assert "<svg class=\"chart" not in html
    assert "—" not in html.split("<main", 1)[-1].split("Medallions")[0]


def test_dashboard_renders_all_four_charts(client, session):
    now = datetime.now(timezone.utc)
    for _ in range(2):
        session.add(Mistake(module=Module.story, category=Category.aspect, wrong="x", right="y", created_at=now))
    session.add(Mistake(module=Module.drill, category=Category.aspect, wrong="x", right="y", created_at=now))
    card = Card(ru="а", en="a", source_module=Module.story)
    session.add(card)
    session.commit()
    cs = CardState(card_id=card.id, state=2, due=now + timedelta(days=2))
    session.add(cs)
    session.commit()
    for _ in range(6):
        session.add(ReviewLog(card_state_id=cs.id, rating=3, state_before=2, reviewed_at=now, due_before=now))
    local_today = stats.local_date(now)
    session.add(StudySession(date=local_today, minutes=12.0))
    session.add(InputLog(date=local_today, minutes=20, kind="reading"))
    session.commit()

    html = client.get("/dashboard").text
    for title in (
        "Mistakes per category per week, last 12 weeks",
        "Retention by card source, last 30 days",
        "Reviews due per day, next 30 days",
        "Minutes practised per day, last 26 weeks",
    ):
        assert f"<title>{title}</title>" in html
    assert html.count('<svg class="chart') == 4
    assert "Verb aspect" in html and "Stories" in html
    assert "12 min studied, 20 min input" in html
    assert "appear here" not in html

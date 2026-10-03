"""Legacy oracle: the base implementations of the four readers, reading the source tables directly.

Copied from the base app (stats.streaks, stats.practice_heatmap, today.day_summary and the
practice measures of medals.evaluate) so equivalence tests compare a run against the original maths.
Only models and tiny helpers are imported from the app; none of the maths is.
"""

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from math import ceil

from sqlmodel import select

from app.models import InputLog, ReviewLog, Session, TranslationAttempt


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def local_date(now: datetime) -> date:
    return _utc(now).astimezone().date()


def streaks(db, now):
    """(current, longest)."""
    today = local_date(now)
    days = set(db.exec(select(Session.date).where(Session.completed == True)).all())  # noqa: E712
    if not days:
        return (0, 0)
    longest = run = 0
    previous = None
    for day in sorted(days):
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day
    day = today if today in days else today - timedelta(days=1)
    current = 0
    while day in days:
        current += 1
        day -= timedelta(days=1)
    return (current, longest)


def day_summary(db, now):
    """(sessions, minutes, reviews, new_cards, streak) or None."""
    rows = db.exec(select(Session).where(Session.date == local_date(now), Session.completed == True)).all()  # noqa: E712
    if not rows:
        return None
    return (
        len(rows),
        round(sum(r.minutes for r in rows), 1),
        sum(r.reviews for r in rows),
        sum(r.new_cards for r in rows),
        streaks(db, now)[0],
    )


def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def heatmap(db, now, weeks=26):
    """Flat description: dict(cells=[(day, study, input, level)], busiest, total, active_days, labels)."""
    today = local_date(now)
    first = _week_start(today) - timedelta(weeks=weeks - 1)
    study = {}
    for day, minutes in db.exec(select(Session.date, Session.minutes).where(Session.date >= first)).all():
        study[day] = study.get(day, 0) + (minutes or 0)
    logged = {}
    for day, minutes in db.exec(select(InputLog.date, InputLog.minutes).where(InputLog.date >= first)).all():
        logged[day] = logged.get(day, 0) + (minutes or 0)
    days = [first + timedelta(days=i) for i in range(weeks * 7)]
    totals = [study.get(d, 0) + logged.get(d, 0) for d in days if d <= today]
    busiest = max(totals + [0])

    def level(total):
        return 0 if total <= 0 else min(4, ceil(4 * total / busiest))

    cells = []
    for day in days:
        if day > today:
            cells.append(None)
            continue
        s, i = study.get(day, 0), logged.get(day, 0)
        cells.append((day, s, i, level(s + i)))
    labels = []
    for w in range(weeks):
        monday = first + timedelta(weeks=w)
        if w == 0 or monday.month != (monday - timedelta(weeks=1)).month:
            labels.append((w, monday.strftime("%b")))
    if len(labels) > 1 and labels[1][0] - labels[0][0] < 3:
        labels.pop(0)
    return dict(cells=cells, busiest=busiest, total=sum(totals), active_days=sum(1 for t in totals if t > 0), labels=labels)


def flatten_heatmap(hm):
    """The same flat description from a run's stats.Heatmap."""
    cells = []
    for column in hm.weeks:
        for cell in column:
            cells.append(None if cell is None else (cell.day, cell.study, cell.input, cell.level))
    return dict(cells=cells, busiest=hm.busiest, total=hm.total_minutes, active_days=hm.active_days, labels=list(hm.month_labels))


def _clean_review_day(db):
    per_day = defaultdict(lambda: [0, 0])
    for rating, at in db.exec(select(ReviewLog.rating, ReviewLog.reviewed_at)).all():
        row = per_day[_utc(at).astimezone().date()]
        row[0] += 1
        row[1] += rating <= 1
    return max((n for n, again in per_day.values() if not again), default=0)


def medal_measures(db, now):
    """The `current` value of each practice medal, as the base medals.evaluate computes it."""
    longest = streaks(db, now)[1]
    minutes = sum(db.exec(select(Session.minutes)).all())
    attempts = len(db.exec(select(TranslationAttempt.id)).all())
    return {
        "streak_7": float(longest),
        "streak_30": float(longest),
        "first_story": float(attempts),
        "flawless": float(_clean_review_day(db)),
        "hours_100": minutes / 60,
    }

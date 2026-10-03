"""Medallions: milestone awards computed from real study data.

`evaluate` reads the database, stores any newly earned medal in `medal_awards`
(once earned, always earned) and returns the state of all twelve for display.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlmodel import Session as DbSession, select

from app.models import MedalAward, Mistake, Module, ReviewLog, Session, TranslationAttempt
from app.services import srs, stats

PERFECT_MIN_REVIEWS = 10


@dataclass(frozen=True)
class MedalDef:
    key: str
    design: int  # which painted SVG in templates/_medals.html
    ru: str  # with stress marks
    en: str
    how: str
    story: str
    field: str  # center color of the medallion
    dot: str
    target: int = 1
    unit: str = ""  # progress unit, e.g. "days"
    future: str | None = None  # label for medals whose feature does not exist yet

    @property
    def ru_plain(self) -> str:
        return self.ru.replace("́", "")


RED, DARK = "#B3261E", "#111012"
GOLD_DOT, RED_DOT = "#E2C46A", "#B3261E"

MEDALS: list[MedalDef] = [
    MedalDef("streak_7", 1, "Неде́ля подря́д", "A week, unbroken", "Study seven days in a row.",
             "Seven days without a break. The habit has started to hold.", RED, GOLD_DOT, 7, "days"),
    MedalDef("streak_30", 2, "Ме́сяц подря́д", "A month, unbroken", "Study thirty days in a row.",
             "Thirty days in a row. Russian is now part of your day.", DARK, RED_DOT, 30, "days"),
    MedalDef("cards_100", 3, "Сто слов", "One hundred words", "Gather 100 cards in your deck.",
             "One hundred cards in the deck, each one a word you chose to keep.", DARK, RED_DOT, 100, "cards"),
    MedalDef("cards_500", 4, "Пятьсо́т слов", "Five hundred words", "Gather 500 cards in your deck.",
             "Five hundred cards. A real vocabulary is taking shape.", RED, GOLD_DOT, 500, "cards"),
    MedalDef("first_story", 5, "Пе́рвый расска́з", "The first story", "Translate your first story.",
             "Your first story, written from the first line to the last.", RED, GOLD_DOT, 1, "stories"),
    MedalDef("self_fixed", 6, "Сам испра́вил", "Fixed it myself", "Fix every mistake in a story yourself.",
             "Every mistake in a story found and fixed by your own hand.", DARK, RED_DOT, 1, "stories"),
    MedalDef("roleplay_10", 7, "Собесе́дник", "A good conversationalist", "Complete 10 role-plays.",
             "Ten conversations held. You can keep up your end.", RED, GOLD_DOT, 10, "role-plays",
             future="Arrives with role-play"),
    MedalDef("flawless", 8, "Безупре́чно", "Flawless", "Review 10 or more cards in a day without a miss.",
             "A whole day of reviews and not one card forgotten.", DARK, RED_DOT, PERFECT_MIN_REVIEWS, "reviews"),
    MedalDef("genitive_plural", 9, "Роди́тельный покорён", "Genitive plural conquered",
             "Master the genitive plural.", "The genitive plural, tamed at last.", RED, GOLD_DOT,
             future="Arrives with drills"),
    MedalDef("motion_verbs", 10, "В пути́", "On the way", "Master the verbs of motion.",
             "Going, walking, driving, flying: every verb of motion in its place.", DARK, RED_DOT,
             future="Arrives with drills"),
    MedalDef("hours_100", 11, "Сто часо́в", "One hundred hours", "Study for 100 hours in total.",
             "One hundred hours of study. That is a lot of Russian.", DARK, RED_DOT, 100, "hours"),
    MedalDef("trip_day", 12, "Москва́!", "Moscow!", "Reach the day of your trip.",
             "The day has come. Удачи!", RED, GOLD_DOT, 1, "days"),
]
BY_KEY = {m.key: m for m in MEDALS}


@dataclass(frozen=True)
class MedalState:
    defn: MedalDef
    earned: bool
    earned_at: datetime | None
    seen: bool
    current: float
    available: bool  # false when the underlying feature does not exist yet
    progress_text: str

    def __getattr__(self, name):  # expose definition fields (key, ru, en, how, ...) to templates
        if name == "defn":
            raise AttributeError(name)
        return getattr(self.defn, name)

    @property
    def pct(self) -> int:
        if self.earned:
            return 100
        if not self.available or not self.defn.target:
            return 0
        return max(0, min(100, int(self.current / self.defn.target * 100)))

    @property
    def date_label(self) -> str:
        if not self.earned_at:
            return ""
        d = srs._utc(self.earned_at).astimezone()
        return f"Earned {d.day} {d.strftime('%b')}"


def _fmt(value: float) -> str:
    value = int(value * 10) / 10  # floor, so 99.99 never reads as 100
    return str(int(value)) if value == int(value) else f"{value:.1f}"


def _clean_review_day(session: DbSession) -> int:
    """Most reviews on a calendar day (local) that had no Again rating; 0 if none."""
    per_day: dict = defaultdict(lambda: [0, 0])
    for rating, at in session.exec(select(ReviewLog.rating, ReviewLog.reviewed_at)).all():
        row = per_day[srs._utc(at).astimezone().date()]
        row[0] += 1
        row[1] += rating <= 1
    return max((n for n, again in per_day.values() if not again), default=0)


def _self_corrected_stories(session: DbSession) -> int:
    """Attempts with at least one logged mistake where every mistake was self-corrected."""
    by_attempt: dict[int, list[bool]] = defaultdict(list)
    for ref_id, fixed in session.exec(
        select(Mistake.ref_id, Mistake.self_corrected).where(Mistake.module == Module.story)
    ).all():
        if ref_id is not None:
            by_attempt[ref_id].append(bool(fixed))
    return sum(1 for flags in by_attempt.values() if flags and all(flags))


def _measure(session: DbSession, now: datetime, trip: int | None) -> dict[str, float | None]:
    """Current value toward each computable medal. Not-yet-built features are absent."""
    streak = stats.streaks(session, now)
    minutes = sum(session.exec(select(Session.minutes)).all())
    attempts = len(session.exec(select(TranslationAttempt.id)).all())
    cards = stats.deck_counts(session).cards
    return {
        "streak_7": streak.longest,
        "streak_30": streak.longest,
        "cards_100": cards,
        "cards_500": cards,
        "first_story": attempts,
        "self_fixed": _self_corrected_stories(session),
        "flawless": _clean_review_day(session),
        "hours_100": minutes / 60,
        "trip_day": None if trip is None else (1 if trip <= 0 else 0),
    }


def _progress_text(defn: MedalDef, current: float, trip: int | None) -> str:
    if defn.future:
        return defn.future
    if defn.key == "trip_day":
        if trip is None:
            return "Set your trip date in Settings"
        return f"{trip} {'day' if trip == 1 else 'days'} to go"
    if defn.key == "flawless":
        return f"Best clean day: {_fmt(current)} / {defn.target} reviews"
    return f"{_fmt(min(current, defn.target))} / {defn.target} {defn.unit}"


def evaluate(session: DbSession, now: datetime | None = None) -> list[MedalState]:
    """State of all medallions; stores newly earned ones so they stay earned."""
    now = now or datetime.now(timezone.utc)
    trip = stats.days_until_trip(session, now)
    values = _measure(session, now, trip)
    awards = {a.key: a for a in session.exec(select(MedalAward)).all()}

    fresh = False
    for defn in MEDALS:
        value = values.get(defn.key)
        if defn.key in awards or defn.future or value is None:
            continue
        if value >= defn.target:
            awards[defn.key] = MedalAward(key=defn.key, earned_at=now, seen=False)
            session.add(awards[defn.key])
            fresh = True
    if fresh:
        session.commit()

    states = []
    for defn in MEDALS:
        award = awards.get(defn.key)
        current = float(values.get(defn.key) or 0)
        states.append(MedalState(
            defn=defn, earned=award is not None, earned_at=award.earned_at if award else None,
            seen=bool(award and award.seen), current=current, available=not defn.future,
            progress_text=_progress_text(defn, current, trip),
        ))
    return states


def pending(session: DbSession, now: datetime | None = None) -> list[MedalState]:
    """Earned medals whose ceremony has not been shown yet, newest first."""
    states = [s for s in evaluate(session, now) if s.earned and not s.seen]
    return sorted(states, key=lambda s: srs._utc(s.earned_at), reverse=True)


def mark_seen(session: DbSession, key: str) -> bool:
    award = session.get(MedalAward, key)
    if award is None:
        return False
    if not award.seen:
        award.seen = True
        session.add(award)
        session.commit()
    return True

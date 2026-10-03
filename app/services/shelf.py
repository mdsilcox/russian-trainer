"""The media shelf («Полка»): a curated ladder of things to read, watch and hear, plus the input log.

The shelf itself is plain data drawn from docs/research.md (section 3). Only the minutes
the learner spends live in the database (`InputLog`).
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlmodel import Session, col, func, select

from app.models import InputLog
from app.services import stats

KINDS = ("reading", "listening", "watching")
KIND_LABELS = {"reading": "Reading", "listening": "Listening", "watching": "Watching"}
MAX_MINUTES = 600

# Which kind of input each shelf format counts as when logged.
_LOG_KIND = {
    "book": "reading",
    "graded reader": "reading",
    "film": "watching",
    "series": "watching",
    "YouTube": "watching",
    "podcast": "listening",
}

_CYRILLIC = re.compile("[а-яА-ЯёЁ]")


@dataclass(frozen=True)
class Level:
    name: str
    cefr: str
    blurb: str


LEVELS = (
    Level("Start here", "A2 to B1", "Easy, clear speech or short texts. Aim to follow most of it without stopping."),
    Level("Getting comfortable", "B1", "Real Russian with plenty of support: native children's prose, classic comedies, learner podcasts."),
    Level("Stretch", "B1+ to B2", "Everyday modern speech at near-normal speed. Expect to miss some; use subtitles."),
    Level("Native pace", "B2 and up", "Fast, slangy or literary. For the long run, not the first pass."),
)


@dataclass(frozen=True)
class ShelfItem:
    slug: str
    title: str  # original title (Russian where it has one)
    title_en: str
    kind: str  # book, graded reader, film, series, YouTube, podcast
    level: str
    why: str
    minutes_hint: int
    link: str | None = None
    adult: bool = False

    @property
    def log_kind(self) -> str:
        return _LOG_KIND[self.kind]

    @property
    def title_is_russian(self) -> bool:
        return bool(_CYRILLIC.search(self.title))


_MOSFILM = "https://www.youtube.com/mosfilm"

SHELF: tuple[ShelfItem, ...] = (
    # Start here
    ShelfItem("nu-pogodi", "Ну, погоди́!", "Nu, pogodi! (Just you wait!)", "series", "Start here",
              "Almost wordless slapstick, so there is little to understand and nothing to fear. A relaxed first watch that shows you a Soviet childhood classic.",
              10, link="https://www.youtube.com/watch?v=q6NvTBZuWmY"),
    ShelfItem("masha-medved", "Ма́ша и Медве́дь", "Masha and the Bear", "series", "Start here",
              "Short episodes with clear, everyday speech. Good for the sound of simple spoken Russian.", 10),
    ShelfItem("smeshariki", "Смеша́рики", "Smeshariki (Kikoriki)", "series", "Start here",
              "Clear everyday speech in short cartoon episodes; easy to replay a favorite until you catch every line.", 10),
    ShelfItem("richards-beginners", "Short Stories in Russian for Beginners", "Olly Richards, with audio", "graded reader", "Start here",
              "Short stories with audio and glossaries. Likely easy for you, which is the point: fast, confident reading.", 20,
              link="https://www.amazon.com/Stories-Beginners-Yourself-Beginners-multiple-Languages/dp/1473683491"),
    ShelfItem("zlatoust", "Библиоте́ка Златоу́ста", "Zlatoust Library adapted readers", "graded reader", "Start here",
              "Adapted readers in five levels keyed to the ТРКИ word lists, including adapted Chekhov. Pick the level where you know about 95% of the words.", 20,
              link="https://www.livelib.ru/pubseries/705241-biblioteka-zlatousta"),
    ShelfItem("slow-russian", "Slow Russian", "Slow Russian with Daria Molchanova", "podcast", "Start here",
              "Clear, slowed speech on everyday topics. A low-effort daily listen and a good source of phrases to mine.", 15,
              link="https://podcasts.apple.com/us/podcast/slow-russian/id1069742339"),
    ShelfItem("russian-made-easy", "Russian Made Easy", "Russian Made Easy with Mark Thomson", "podcast", "Start here",
              "Beginner material, probably below your level. Useful for quick revision and for easy, confidence-building listening.", 15,
              link="https://russianmadeeasy.com/"),
    # Getting comfortable
    ShelfItem("richards-intermediate", "Short Stories in Russian for Intermediate Learners", "Olly Richards, with audio", "graded reader", "Getting comfortable",
              "The natural next step: longer stories with audio, written for B1 to B2, so most words are within reach.", 25,
              link="https://us.teachyourself.com/products/short-stories-in-russian-for-intermediate-learners"),
    ShelfItem("nosov-mishkina-kasha", "Ми́шкина ка́ша", "Nosov, Mishka's Porridge", "book", "Getting comfortable",
              "Short native children's prose with free audio online. Simple plots and everyday vocabulary, but not graded, so expect some lookups.", 20,
              link="https://mishka-knizhka.ru/audio-rasskazy-dlya-detej/audio-rasskazy-nosova/mishkina-kasha-audio/"),
    ShelfItem("deniskiny-rasskazy", "Дени́скины расска́зы", "Dragunsky, Deniska's Stories", "book", "Getting comfortable",
              "Short, funny stories of everyday Moscow family life. Real native prose in bite-sized pieces; free texts exist online.", 20),
    ShelfItem("russian-with-max", "Learn Russian with Max", "Comprehensible Russian Podcast", "YouTube", "Getting comfortable",
              "Comprehensible-input episodes from a certified teacher, pitched at A2 to B1+. Easy to follow without a transcript.", 20,
              link="https://www.youtube.com/@RussianWithMax"),
    ShelfItem("raketa", "Раке́та", "Raketa Russian Language Podcast (University of Chicago)", "podcast", "Getting comfortable",
              "Short audio episodes with transcripts: listen first, then read along and mine sentences.", 15,
              link="https://ceeres.uchicago.edu/resources/raketa-russian-language-podcast"),
    ShelfItem("ironiya-sudby", "Иро́ния судьбы́, или С лёгким па́ром!", "The Irony of Fate (1975)", "film", "Getting comfortable",
              "The Moscow New Year classic. Watch it around New Year with subtitles on, and you will know what every Russian family quotes.", 90,
              link=_MOSFILM),
    ShelfItem("ivan-vasilevich", "Ива́н Васи́льевич меня́ет профе́ссию", "Ivan Vasilievich Changes Profession (1973)", "film", "Getting comfortable",
              "A fast, funny classic comedy with lots of everyday dialogue. Free on the official Mosfilm channel.", 90, link=_MOSFILM),
    ShelfItem("moskva-slezam", "Москва́ слеза́м не ве́рит", "Moscow Does Not Believe in Tears (1979)", "film", "Getting comfortable",
              "Oscar-winning drama about life in Moscow. Slower, more realistic speech than the comedies, and good background for the trip.", 140,
              link=_MOSFILM),
    # Stretch
    ShelfItem("kukhnya", "Ку́хня", "The Kitchen (sitcom)", "series", "Stretch",
              "A modern sitcom set in a Moscow restaurant: everyday speech, jokes and short episodes. Check that any upload you use is a legitimate one.", 25),
    ShelfItem("yolki", "Ёлки", "Yolki (Six Degrees of Celebration, 2010)", "film", "Stretch",
              "A family-friendly New Year anthology of short interwoven stories in modern spoken Russian.", 100),
    ShelfItem("easy-russian", "Easy Russian", "Easy Russian street interviews", "YouTube", "Stretch",
              "Unscripted Moscow and St Petersburg street interviews with Russian and English subtitles. The best match for the speech you will hear on the trip.", 20,
              link="https://www.youtube.com/@EasyRussianVideos"),
    # Native pace
    ShelfItem("chekhov", "То́лстый и то́нкий, Хамелео́н, Смерть чино́вника", "Chekhov short stories in the original", "book", "Native pace",
              "Short, classic and brilliantly compact. Original text with a dictionary at hand, after the adapted versions.", 20),
    ShelfItem("arzamas", "Арзама́с", "Arzamas (culture and history)", "podcast", "Native pace",
              "Native-speed talk on culture and history. Rewarding once your listening is solid; treat it as a long-term goal.", 30,
              link="https://arzamas.academy/"),
    ShelfItem("metod", "Ме́тод", "The Method (2015)", "series", "Native pace",
              "A violent thriller at native speed and slangy in places. Not family viewing.", 50,
              link="https://www.film.ru/serials/metod", adult=True),
    ShelfItem("obychnaya-zhenshchina", "Обы́чная же́нщина", "An Ordinary Woman (2018)", "series", "Native pace",
              "Fast, modern dialogue and everyday language. Mature content, not family viewing.", 45, adult=True),
    ShelfItem("chiki", "Чи́ки", "Chiki (2020)", "series", "Native pace",
              "Fast, slangy modern speech. Mature content, not family viewing.", 45, adult=True),
    ShelfItem("slovo-patsana", "Сло́во пацана́. Кровь на асфа́льте", "The Boy's Word: Blood on the Asphalt (2023)", "series", "Native pace",
              "Set among 1980s Kazan gangs, so the slang is thick. A stretch goal, and not family viewing.", 50,
              link="https://www.kinopoisk.ru/series/5304403/", adult=True),
)

_BY_SLUG = {item.slug: item for item in SHELF}


def items() -> tuple[ShelfItem, ...]:
    return SHELF


def get(slug: str | None) -> ShelfItem | None:
    return _BY_SLUG.get(slug or "")


def by_level() -> list[tuple[Level, list[ShelfItem]]]:
    return [(level, [i for i in SHELF if i.level == level.name]) for level in LEVELS]


# --- The input log -----------------------------------------------------------------

def log_minutes(
    session: Session,
    minutes: int,
    kind: str,
    title: str = "",
    shelf_slug: str | None = None,
    now: datetime | None = None,
) -> InputLog:
    """Record minutes of input on the learner's local date."""
    if kind not in KINDS:
        raise ValueError("Pick reading, listening or watching.")
    if not isinstance(minutes, int) or not 1 <= minutes <= MAX_MINUTES:
        raise ValueError(f"Minutes must be a whole number from 1 to {MAX_MINUTES}.")
    item = get(shelf_slug)
    if shelf_slug and item is None:
        raise ValueError("Unknown shelf item.")
    entry = InputLog(
        date=stats.local_date(now),
        minutes=minutes,
        kind=kind,
        title=title.strip() or (item.title if item else KIND_LABELS[kind]),
        shelf_slug=shelf_slug or None,
    )
    session.add(entry)
    session.commit()
    return entry


def _total_since(session: Session, first_day: date) -> int:
    total = session.exec(select(func.coalesce(func.sum(InputLog.minutes), 0)).where(col(InputLog.date) >= first_day)).one()
    return int(total)


def input_minutes(session: Session, days: int, now: datetime | None = None) -> int:
    """Minutes logged in the last `days` days, today included."""
    return _total_since(session, stats.local_date(now) - timedelta(days=days - 1))


def this_week(session: Session, now: datetime | None = None) -> int:
    """Minutes logged since Monday of the learner's current local week."""
    today = stats.local_date(now)
    return _total_since(session, today - timedelta(days=today.weekday()))

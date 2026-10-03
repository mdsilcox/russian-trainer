"""Database tables.

JSON columns hold structured Claude output (feedback, drill items, debriefs)
that we display but never query by field.
"""

from datetime import date as Date, datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Module(str, Enum):
    manual = "manual"
    starter = "starter"
    story = "story"
    drill = "drill"
    scenario = "scenario"


class Category(str, Enum):
    case = "case"
    aspect = "aspect"
    motion_verb = "motion_verb"
    participle = "participle"
    agreement = "agreement"
    word_choice = "word_choice"
    word_order = "word_order"
    preposition = "preposition"
    stress = "stress"
    spelling = "spelling"
    idiom = "idiom"


class Direction(str, Enum):
    recognition = "ru_en"
    production = "en_ru"


class Setting(SQLModel, table=True):
    __tablename__ = "settings"
    key: str = Field(primary_key=True)
    value: Any = Field(sa_column=Column(JSON))


class Card(SQLModel, table=True):
    __tablename__ = "cards"
    id: int | None = Field(default=None, primary_key=True)
    ru: str = Field(index=True)
    ru_stressed: str | None = None
    stress_verified: bool = False
    en: str
    example_ru: str | None = None
    example_en: str | None = None
    pos: str | None = None
    gender: str | None = None
    aspect: str | None = None
    aspect_partner: str | None = None
    notes: str | None = None
    tags: str = ""  # space-separated
    source_module: Module = Module.manual
    source_ref_id: int | None = None
    created_at: datetime = Field(default_factory=utcnow)
    suspended: bool = False
    kind: str = "word"  # "word", "form" (high-frequency form in context), "stress" (stress shift) or "chunk" (phrase)


class CardState(SQLModel, table=True):
    """FSRS memory state, one row per card per direction."""

    __tablename__ = "card_state"
    __table_args__ = (UniqueConstraint("card_id", "direction"),)
    id: int | None = Field(default=None, primary_key=True)
    card_id: int = Field(foreign_key="cards.id", index=True)
    direction: Direction = Direction.recognition
    due: datetime = Field(default_factory=utcnow, index=True)
    stability: float | None = None
    difficulty: float | None = None
    state: int = 0  # 0 = new (never reviewed); otherwise fsrs.State value
    step: int | None = None
    reps: int = 0
    lapses: int = 0
    last_review: datetime | None = None


class ReviewLog(SQLModel, table=True):
    __tablename__ = "review_log"
    id: int | None = Field(default=None, primary_key=True)
    card_state_id: int = Field(foreign_key="card_state.id", index=True)
    rating: int
    reviewed_at: datetime = Field(default_factory=utcnow, index=True)
    duration_ms: int | None = None
    state_before: int
    due_before: datetime


class Story(SQLModel, table=True):
    __tablename__ = "stories"
    id: int | None = Field(default=None, primary_key=True)
    title: str
    source_lang: str  # "en" or "ru"
    source_text: str
    created_at: datetime = Field(default_factory=utcnow)


class TranslationAttempt(SQLModel, table=True):
    __tablename__ = "translation_attempts"
    id: int | None = Field(default=None, primary_key=True)
    story_id: int = Field(foreign_key="stories.id", index=True)
    text: str
    feedback_json: dict | None = Field(default=None, sa_column=Column(JSON))
    corrected_text: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Mistake(SQLModel, table=True):
    __tablename__ = "mistakes"
    id: int | None = Field(default=None, primary_key=True)
    module: Module
    ref_id: int | None = None
    category: Category = Field(index=True)
    subcategory: str | None = None
    wrong: str
    right: str
    explanation: str | None = None
    card_id: int | None = Field(default=None, foreign_key="cards.id")
    drilled_count: int = 0
    mastered: bool = False
    self_corrected: bool | None = None  # story feedback: did the learner fix it before seeing the answer?
    fix_attempts: int = 0
    last_drilled_on: Date | None = None  # local day of the last counted correct drill answer
    topic: str | None = None  # grammar reference section when known exactly (drills); else derived from subcategory
    created_at: datetime = Field(default_factory=utcnow, index=True)


class DrillSet(SQLModel, table=True):
    __tablename__ = "drill_sets"
    id: int | None = Field(default=None, primary_key=True)
    category: Category
    subcategory: str | None = None
    items_json: list = Field(sa_column=Column(JSON))
    from_mistake_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    topic: str | None = None  # grammar reference section (weakness topic); mixed sets tag each item instead
    kind: str = "focused"  # "focused" (one topic, opens with a rule card) or "mixed" (interleaved topics)
    intro_json: dict | None = Field(default=None, sa_column=Column(JSON))  # the rule card
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)


class DrillAnswer(SQLModel, table=True):
    __tablename__ = "drill_answers"
    id: int | None = Field(default=None, primary_key=True)
    drill_set_id: int = Field(foreign_key="drill_sets.id", index=True)
    item_idx: int
    answer: str
    correct: bool
    created_at: datetime = Field(default_factory=utcnow)


class Scenario(SQLModel, table=True):
    __tablename__ = "scenarios"
    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True)
    title: str
    setting: str
    partner_role: str
    goals_json: list = Field(default_factory=list, sa_column=Column(JSON))
    level: int = 1


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"
    id: int | None = Field(default=None, primary_key=True)
    scenario_id: int = Field(foreign_key="scenarios.id", index=True)
    started_at: datetime = Field(default_factory=utcnow)
    ended_at: datetime | None = None
    debrief_json: dict | None = Field(default=None, sa_column=Column(JSON))


class Message(SQLModel, table=True):
    __tablename__ = "messages"
    id: int | None = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversations.id", index=True)
    role: str  # "user" or "partner"
    content: str
    corrections_json: list | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class Session(SQLModel, table=True):
    __tablename__ = "sessions"
    id: int | None = Field(default=None, primary_key=True)
    date: Date = Field(index=True)
    started_at: datetime = Field(default_factory=utcnow)
    minutes: float = 0
    reviews: int = 0
    new_cards: int = 0
    drills: int = 0
    scenario_turns: int = 0
    completed: bool = False


class ApiUsage(SQLModel, table=True):
    __tablename__ = "api_usage"
    id: int | None = Field(default=None, primary_key=True)
    task: str
    model: str
    backend: str = "api"  # "api" (billed per token) or "subscription" (claude -p)
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float
    request_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)


class PlanMonth(SQLModel, table=True):
    __tablename__ = "plan_months"
    month_idx: int = Field(primary_key=True)
    start_date: Date
    focus: str
    goals_json: list = Field(default_factory=list, sa_column=Column(JSON))
    status: str = "planned"


class MedalAward(SQLModel, table=True):
    """A medallion once earned stays earned; `seen` is false until its ceremony has been shown."""

    __tablename__ = "medal_awards"
    key: str = Field(primary_key=True)
    earned_at: datetime = Field(default_factory=utcnow)
    seen: bool = False

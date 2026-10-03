"""Exercise items for guided-learning units: the shared contract (P5).

The unit engine generates items in these shapes; the exercise player renders one template per type
(`templates/learn/items/_<type>.html`) and checks answers with `check(item, response)`.

Russian strings carry stress marks (U+0301). Answer checking ignores stress marks, ё/е, case,
surrounding punctuation and extra spaces (reuse `drill_player.norm`).

Contract owners: the item models are the orchestrator's (change them only by agreement);
`check`, `ITEM_RENDERERS` and the player are Lane A's; the listening renderers are Lane C's.
"""

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

Skill = Literal["grammar", "vocab", "listening", "production"]


class ItemBase(BaseModel):
    id: str = Field(description="Stable within its content set, e.g. 'q3'")
    topic: str = Field(default="", description="Weakness topic (grammar section URL) the item practices")
    skill: Skill = "grammar"
    instruction: str = Field(default="", description="One short English line telling the learner what to do")
    explanation: str = Field(default="", description="One or two English sentences shown after answering: the rule behind the answer")


class ChoiceItem(ItemBase):
    """Pick the right option; `question_ru` may contain ___ for the gap."""
    type: Literal["choice"] = "choice"
    question_ru: str
    question_en: str = ""
    options: list[str] = Field(description="3-4 options; distractors are typical learner errors")
    answer_index: int


class FillItem(ItemBase):
    """Type the missing word(s); same shape as drill items."""
    type: Literal["fill"] = "fill"
    prompt_ru: str = Field(description="One sentence with exactly one ___")
    cue: str = Field(description="Dictionary form or options in brackets")
    translation_en: str
    answer: str
    accepted: list[str] = Field(default_factory=list)


class MatchItem(ItemBase):
    """Match each left item to its right item (shown shuffled)."""
    type: Literal["match"] = "match"
    pairs: list[dict] = Field(description="3-6 objects {left, right}")


class TransformItem(ItemBase):
    """Rewrite a sentence as instructed ('make it where-to', 'make it plural')."""
    type: Literal["transform"] = "transform"
    source_ru: str
    task: str = Field(description="What to change, in English")
    answer: str
    accepted: list[str] = Field(default_factory=list)


class BuildItem(ItemBase):
    """Put the word tiles in order to make the sentence (tiles shown shuffled)."""
    type: Literal["build"] = "build"
    meaning_en: str
    tiles: list[str] = Field(description="The words of the answer, in answer order; the player shuffles them")
    answer: str
    accepted: list[str] = Field(default_factory=list, description="Other correct orders, as full sentences")


class TranslateItem(ItemBase):
    """Translate one short English sentence into Russian."""
    type: Literal["translate"] = "translate"
    skill: Skill = "production"
    en: str
    answer: str
    accepted: list[str] = Field(default_factory=list)


class ListenChoiceItem(ItemBase):
    """Hear a Russian sentence (speak control, text hidden until answered) and choose what it means."""
    type: Literal["listen_choice"] = "listen_choice"
    skill: Skill = "listening"
    audio_ru: str
    question_en: str = Field(description="e.g. 'Where is the speaker going?'")
    options: list[str] = Field(description="3-4 English options")
    answer_index: int


class DictationItem(ItemBase):
    """Hear a short Russian sentence and type it."""
    type: Literal["dictation"] = "dictation"
    skill: Skill = "listening"
    audio_ru: str
    translation_en: str
    accepted: list[str] = Field(default_factory=list)


Item = Annotated[
    Union[ChoiceItem, FillItem, MatchItem, TransformItem, BuildItem, TranslateItem, ListenChoiceItem, DictationItem],
    Field(discriminator="type"),
]
ITEM_TYPES = ["choice", "fill", "match", "transform", "build", "translate", "listen_choice", "dictation"]


class ItemSet(BaseModel):
    """What the engine stores and serves for a practice set, pre-test, quiz, listening set, remediation or revisit."""
    title: str
    intro: str = ""  # optional English lead-in shown before the first item (remediation: the alternative explanation)
    items: list[Item]


def parse_items(raw: list[dict]) -> list:
    """Validate stored item dicts back into models."""
    return ItemSet(title="", items=raw).items


# --- Answer checking (Lane A) -------------------------------------------------------------------

def _accepts(response, *answers: str) -> bool:
    from app.services.drill_player import norm

    given = norm(str(response or ""))
    return bool(given) and given in {norm(a) for a in answers if norm(a)}


def _index(response) -> int | None:
    try:
        return int(str(response).strip())
    except (TypeError, ValueError):
        return None


def check(item, response) -> bool:
    """Is `response` right for `item`?

    The response is a string, as posted by the player: an option index for choice and listen_choice,
    the typed or assembled text for the rest, and for match a JSON list of [left, right] pairs (a list
    is accepted too). Text is compared with `drill_player.norm`, so stress marks, ё/е, case, spacing and
    the final full stop don't matter.
    """
    if item.type in ("choice", "listen_choice"):
        return _index(response) == item.answer_index
    if item.type == "dictation":
        return _accepts(response, item.audio_ru, *item.accepted)
    if item.type in ("fill", "transform", "translate", "build"):
        return _accepts(response, item.answer, *item.accepted)
    if item.type == "match":
        return _check_match(item, response)
    return False


def _check_match(item, response) -> bool:
    import json

    from app.services.drill_player import norm

    if isinstance(response, str):
        try:
            response = json.loads(response)
        except ValueError:
            return False
    try:
        given = {(norm(left), norm(right)) for left, right in response}
    except (TypeError, ValueError):
        return False
    wanted = {(norm(p["left"]), norm(p["right"])) for p in item.pairs}
    return len(given) == len(wanted) == len(response) and given == wanted

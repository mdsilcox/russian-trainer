"""Role-play engine (P3.2a): the conversation service the scenario chat UI builds on.

Two separate Claude calls per learner turn, so the partner never breaks character to teach:
1. the PARTNER reply, streamed, in Russian only, in character, sized to the chosen level;
2. a TURN REVIEW (structured): corrections for the learner's line, routed through the mistake
   router like story feedback, plus which scenario goals the conversation has now achieved.
Hints and the end-of-conversation debrief are structured calls too.

Flow for the UI:
    conv = start(session, scenario, level)            # saves the partner's opening line
    msg = add_learner_turn(session, conv, text)        # saves the learner's line
    for chunk in partner_stream(session, client, conv): ...   # streams + saves the reply
    review = review_turn(session, client, conv, msg)   # corrections + goals (can run after)
    hint(session, client, conv) / end(session, conv) / debrief(session, client, conv)
"""

from collections.abc import Iterator
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from app.models import Category, Conversation, Message, Module, Scenario
from app.services.cards import fix_latin_accents
from app.services.claude import ClaudeClient, Task
from app.services.feedback import Issue
from app.services.mistakes import LOGGED_SEVERITIES, RouteResult, log_mistake

PARTNER, LEARNER = "partner", "user"
LEVELS = {1: "Slow and clear", 2: "Everyday", 3: "Natural speed"}
HISTORY_TURNS = 24  # messages sent to the partner call; older ones are dropped
NO_EM_DASH = ("Punctuation: never use em dashes (—) in English text; use a comma, colon, full stop or parentheses. "
              "Inside Russian sentences keep the dash only where Russian grammar requires it.")

LEVEL_STYLE = {
    1: ("Speak slowly and clearly for a learner: short sentences (usually under 10 words), common everyday words, "
        "polite вы, no slang or idioms. If the learner seems lost, say the same thing again more simply, still in Russian."),
    2: ("Speak naturally, as you would to any polite foreign visitor: normal sentences and everyday vocabulary, "
        "an occasional colloquial word. Don't simplify unless they are clearly lost."),
    3: ("Speak at natural native speed and register for your persona: colloquial forms (щас, ничего́ себе́, да ла́дно), "
        "idioms, ellipsis, interruptions, the odd bit of slang; be as brisk or chatty as your persona would be. "
        "Don't simplify for the learner."),
}

PARTNER_SYSTEM = """You are playing a character in a Russian conversation practice for an English-speaking adult learner at intermediate (B1) level who is preparing for a family trip to Moscow.

Scene: {setting}
You are: {partner_role}. {persona}

The learner is trying to:
{goals}

How to play it:
- Speak ONLY Russian, always in character. Never switch to English, never translate, never explain grammar, never correct the learner's mistakes, never mention that this is practice. If they write English or something you can't understand, react as your character really would (confused, ask again, gesture at the menu), in Russian.
- Keep each reply short: one to three sentences, like real speech. Ask one thing at a time.
- Make the learner do the work: respond to what they say and let the conversation move toward their goals, but don't achieve their goals for them or volunteer everything at once. Add small realistic complications now and then (a dish is sold out, the card machine is down, a road is closed).
- {level_style}
- Put a stress mark (U+0301, after the stressed vowel) on every word of two or more syllables, never on ё or one-syllable words. Write numbers as words when a learner would need to hear them.
- If the conversation has reached a natural end (they paid and left, they arrived), close it politely in character."""

REVIEW_SYSTEM = """You review one line written by an English-speaking intermediate (B1) learner of Russian during a role-play, and track the role-play's goals.

Corrections:
- Look only at the learner's latest line. Report real errors: grammar, wrong word, unnatural phrasing. Copy `wrong` character-for-character from their line, as short as possible (usually 1-4 words); `right` replaces exactly those words. One issue per distinct error, never twice.
- severity "error": ungrammatical or wrong meaning; "unnatural": grammatical but a Muscovite wouldn't say it; "style": a minor preference (use sparingly).
- Don't flag missing stress marks, ё written as е, missing capitals or end punctuation, or casual chat-style spelling of punctuation. Don't flag correct alternatives. Spoken-style short answers ("Да, два.") are fine.
- Categories: case, aspect, motion_verb, participle, agreement, word_choice, word_order, preposition, stress, spelling, idiom. Use consistent, reusable subcategory labels (e.g. "prepositional after в/на", "accusative for direction", "genitive after numerals 5+", "идти vs ехать").
- Explanations in English, one or two sentences naming the rule.
- `better`: if the line works but a native speaker would say it more naturally, give that version (stress-marked); otherwise null.

Goals: given the goal list and the whole conversation, list the 0-based indexes of every goal the LEARNER has achieved so far (they did it themselves in Russian; the partner doing it for them doesn't count).

""" + NO_EM_DASH

HINT_SYSTEM = """You coach an English-speaking intermediate (B1) learner of Russian mid role-play. Suggest the learner's next line: ONE short, natural spoken turn (one sentence, two at most, under 15 words) that a real person would say right now, replying to the partner's last line and moving toward ONE goal they haven't achieved yet. Match their level (simpler at level 1, more natural at 3). Stress-mark every word of two or more syllables (U+0301; never on ё or one-syllable words). Give its English meaning and one short tip (which word or form to notice).

Punctuation: no dashes of any kind in the suggested line or the English; use commas and full stops."""

DEBRIEF_SYSTEM = """You write a short, encouraging debrief after a Russian role-play by an English-speaking intermediate (B1) learner preparing for a trip to Moscow. Explanations in English.

- summary: two or three sentences: what went well, and the one pattern most worth practicing.
- phrases: three to five useful words or phrases the learner lacked, avoided, or would have needed to sound natural in THIS situation (things a native speaker said, or that would have helped them reach a goal). Each stress-marked (U+0301 on every word of 2+ syllables, never ё), with its English meaning, a short example sentence from this kind of situation (stress-marked) and its translation, and why it is worth learning.
- next_level_tip: one sentence on what to try when replaying this scenario at a harder level.

""" + NO_EM_DASH


class TurnReview(BaseModel):
    issues: list[Issue]
    better: str | None = Field(description="A more natural version of the learner's whole line, stress-marked, or null")
    goals_met: list[int] = Field(description="0-based indexes of every goal the learner has achieved so far")


class Hint(BaseModel):
    ru: str = Field(description="The suggested next line, stress-marked")
    en: str
    tip: str


class DebriefPhrase(BaseModel):
    ru: str
    en: str
    example_ru: str
    example_en: str
    why: str


class Debrief(BaseModel):
    summary: str
    phrases: list[DebriefPhrase]
    next_level_tip: str


# --- Conversation state ----------------------------------------------------------------------


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def scenario_of(session: Session, conversation: Conversation) -> Scenario:
    scenario = session.get(Scenario, conversation.scenario_id)
    if scenario is None:
        raise LookupError(f"Conversation {conversation.id} has no scenario")
    return scenario


def messages(session: Session, conversation: Conversation) -> list[Message]:
    return list(session.exec(
        select(Message).where(Message.conversation_id == conversation.id).order_by(col(Message.created_at), col(Message.id))
    ).all())


def _add(session: Session, conversation: Conversation, role: str, content: str, now: datetime | None = None) -> Message:
    msg = Message(conversation_id=conversation.id, role=role, content=content.strip(), created_at=_now(now))
    session.add(msg)
    session.commit()
    session.refresh(msg)
    return msg


def start(session: Session, scenario: Scenario, level: int, now: datetime | None = None) -> Conversation:
    """Open a conversation at a level (1-3) with the scenario's opening line already said."""
    if level not in LEVELS:
        raise ValueError(f"Level must be one of {sorted(LEVELS)}")
    conv = Conversation(scenario_id=scenario.id, level=level, started_at=_now(now), goals_met_json=[])
    session.add(conv)
    session.commit()
    session.refresh(conv)
    if scenario.opening_ru.strip():
        _add(session, conv, PARTNER, scenario.opening_ru, now)
    return conv


def add_learner_turn(session: Session, conversation: Conversation, text: str, now: datetime | None = None) -> Message:
    if conversation.ended_at is not None:
        raise ValueError("This conversation has ended")
    if not text.strip():
        raise ValueError("Say something first")
    return _add(session, conversation, LEARNER, text, now)


def end(session: Session, conversation: Conversation, now: datetime | None = None) -> Conversation:
    if conversation.ended_at is None:
        conversation.ended_at = _now(now)
        session.add(conversation)
        session.commit()
    return conversation


# --- Prompts -----------------------------------------------------------------------------------


def _goals_text(scenario: Scenario) -> str:
    return "\n".join(f"{i}. {g}" for i, g in enumerate(scenario.goals_json or [])) or "(no explicit goals)"


def partner_system(scenario: Scenario, level: int) -> str:
    return PARTNER_SYSTEM.format(
        setting=scenario.setting, partner_role=scenario.partner_role, persona=scenario.persona,
        goals=_goals_text(scenario), level_style=LEVEL_STYLE.get(level, LEVEL_STYLE[2]),
    )


def partner_messages(history: list[Message]) -> list[dict]:
    """Claude messages for the partner call: the partner is the assistant. The API needs a user
    message first, so a stage direction opens the scene when the partner spoke first."""
    turns = [m for m in history if m.content.strip()][-HISTORY_TURNS:]
    out: list[dict] = []
    if turns and turns[0].role == PARTNER:
        out.append({"role": "user", "content": "(Сце́на начина́ется.)"})
    for m in turns:
        role = "assistant" if m.role == PARTNER else "user"
        if out and out[-1]["role"] == role:  # merge consecutive same-role lines
            out[-1]["content"] += "\n" + m.content
        else:
            out.append({"role": role, "content": m.content})
    return out


def transcript(history: list[Message]) -> str:
    return "\n".join(f"{'LEARNER' if m.role == LEARNER else 'PARTNER'}: {m.content}" for m in history)


# --- Claude calls ------------------------------------------------------------------------------


def partner_stream(session: Session, client: ClaudeClient, conversation: Conversation,
                   now: datetime | None = None) -> Iterator[str]:
    """Stream the partner's reply to the conversation so far; the full reply is saved when done."""
    scenario = scenario_of(session, conversation)
    history = messages(session, conversation)
    if not history or history[-1].role != LEARNER:
        raise ValueError("The partner replies to a learner turn")
    parts: list[str] = []
    for chunk in client.stream_text(Task.roleplay, partner_system(scenario, conversation.level), partner_messages(history),
                                    max_tokens=600):
        parts.append(chunk)
        yield chunk
    reply = fix_latin_accents("".join(parts).strip())
    if reply:
        _add(session, conversation, PARTNER, reply, now)


def review_turn(session: Session, client: ClaudeClient, conversation: Conversation, message: Message) -> TurnReview:
    """Corrections for one learner line (stored on the message, errors routed as mistakes) and the
    goals achieved so far (stored on the conversation)."""
    scenario = scenario_of(session, conversation)
    history = [m for m in messages(session, conversation) if m.id <= message.id]
    prompt = (
        f"Scene: {scenario.setting} The partner is a {scenario.partner_role}.\n\n"
        f"Goals:\n{_goals_text(scenario)}\n\n"
        f"Conversation so far:\n{transcript(history)}\n\n"
        f"The learner's latest line to correct:\n<line>\n{message.content}\n</line>"
    )
    review = client.ask_structured(Task.roleplay_corrections, REVIEW_SYSTEM, prompt, TurnReview, max_tokens=3000)
    review.issues = [i.model_copy(update={"right": fix_latin_accents(i.right)})
                     for i in review.issues if i.wrong.strip() and i.wrong in message.content]
    review.better = fix_latin_accents(review.better) if review.better else None
    message.corrections_json = [i.model_dump() for i in review.issues] + (
        [{"better": review.better}] if review.better else [])
    session.add(message)

    goal_count = len(scenario.goals_json or [])
    met = sorted({*(conversation.goals_met_json or []), *(g for g in review.goals_met if 0 <= g < goal_count)})
    conversation.goals_met_json = met
    session.add(conversation)
    session.commit()

    result = RouteResult()
    for issue in review.issues:
        if issue.severity in LOGGED_SEVERITIES:
            log_mistake(
                session, result, module=Module.scenario, ref_id=conversation.id, category=Category(issue.category),
                subcategory=issue.subcategory, wrong=issue.wrong, right=issue.right, explanation=issue.explanation,
                example_ru=message.content,
            )
    return review


def corrections(message: Message) -> tuple[list[Issue], str | None]:
    """(issues, better) stored on a learner message by review_turn."""
    issues, better = [], None
    for item in message.corrections_json or []:
        if "better" in item:
            better = item["better"]
        else:
            issues.append(Issue(**item))
    return issues, better


def hint(session: Session, client: ClaudeClient, conversation: Conversation) -> Hint:
    scenario = scenario_of(session, conversation)
    met = set(conversation.goals_met_json or [])
    open_goals = [g for i, g in enumerate(scenario.goals_json or []) if i not in met] or ["finish the conversation politely"]
    prompt = (
        f"Scene: {scenario.setting} The partner is a {scenario.partner_role}. Learner level: {conversation.level} "
        f"({LEVELS[conversation.level]}).\nGoals not yet achieved: {'; '.join(open_goals)}\n\n"
        f"Conversation so far:\n{transcript(messages(session, conversation))}\n\nSuggest the learner's next line."
    )
    result = client.ask_structured(Task.roleplay_corrections, HINT_SYSTEM, prompt, Hint, max_tokens=1000)
    result.ru = fix_latin_accents(result.ru)
    return result


def debrief(session: Session, client: ClaudeClient, conversation: Conversation) -> Debrief:
    """Summary and phrases the learner lacked; stored on the conversation (computed once)."""
    if conversation.debrief_json:
        return Debrief(**conversation.debrief_json)
    scenario = scenario_of(session, conversation)
    history = messages(session, conversation)
    goals = scenario.goals_json or []
    met = set(conversation.goals_met_json or [])
    fixes = [f"«{i.wrong}» → «{i.right}» ({i.subcategory})" for m in history if m.role == LEARNER for i in corrections(m)[0]]
    prompt = (
        f"Scenario: {scenario.title}. {scenario.setting} Partner: {scenario.partner_role}. Level {conversation.level}.\n"
        f"Goals achieved: {'; '.join(g for i, g in enumerate(goals) if i in met) or 'none'}\n"
        f"Goals missed: {'; '.join(g for i, g in enumerate(goals) if i not in met) or 'none'}\n"
        f"Corrections made during the chat: {'; '.join(fixes) or 'none'}\n\n"
        f"Conversation:\n{transcript(history)}"
    )
    result = client.ask_structured(Task.roleplay_corrections, DEBRIEF_SYSTEM, prompt, Debrief, max_tokens=3000)
    result.phrases = [p.model_copy(update={"ru": fix_latin_accents(p.ru), "example_ru": fix_latin_accents(p.example_ru)})
                      for p in result.phrases[:5]]
    conversation.debrief_json = result.model_dump()
    session.add(conversation)
    session.commit()
    return result

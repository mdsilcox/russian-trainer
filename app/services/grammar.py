"""Grammar reference helpers: links from mistake categories into the reference, and the
small markup renderer used by the grammar templates (content lives in app/grammar_content.py)."""

import re

from markupsafe import Markup, escape

from app.grammar_content import stress

CASES = "/grammar/cases"
NUMBERS = "/grammar/numbers"
MOTION = "/grammar/motion"
ASPECT = "/grammar/aspect"
STRESS = "/grammar/stress"
PITFALLS = "/grammar/pitfalls"

# Where a mistake category lands when nothing more specific matches.
CATEGORY_SECTION = {
    "case": CASES,
    "aspect": ASPECT,
    "motion_verb": MOTION,
    "participle": "/grammar",
    "agreement": f"{CASES}#adjectives",
    "word_choice": PITFALLS,
    "word_order": PITFALLS,
    "preposition": f"{CASES}#prepositions",
    "stress": STRESS,
    "spelling": f"{CASES}#spelling-rules",
    "idiom": PITFALLS,
}

# Keyword rules: the first rule with any keyword found in the (lower-cased) subcategory wins.
_CASE_RULES = [
    (("numeral", "number", "5+", "2-4", "2–4", "after 5", "after 2", "числит"), f"{NUMBERS}#numbers-rule"),
    (("genitive plural", "gen. pl", "gen pl", "genitive pl", "родительный множ"), f"{CASES}#genitive-plural"),
    (("animate", "одушевл"), f"{CASES}#animate-accusative"),
    (("locative", "second prepositional", "-у'", "-у́", "в аэропорту"), f"{CASES}#prepositional-locative"),
]
_CASE_WORDS = [
    (("prepositional", "предложн"), "prepositional"),
    (("genitive", "родительн"), "genitive"),
    (("dative", "дательн"), "dative"),
    (("accusative", "винительн"), "accusative"),
    (("instrumental", "творительн"), "instrumental"),
    (("nominative", "именительн"), "nominative"),
]
_DIRECTION_WORDS = ("direction", "куда", "motion toward", "в/на", "в или на", "в и на", "в vs на", "location")

_PREP_IDS = {
    "у": "prep-u", "от": "prep-ot", "до": "prep-do", "из": "prep-iz", "без": "prep-bez", "для": "prep-dlya",
    "около": "prep-okolo", "после": "prep-posle", "мимо": "prep-mimo", "к": "prep-k", "по": "prep-po",
    "за": "prep-za-acc", "под": "prep-pod", "перед": "prep-pered", "над": "prep-nad", "между": "prep-mezhdu",
    "о": "prep-o", "об": "prep-o", "обо": "prep-o", "через": "prep-cherez",
}


def _has(text: str, words) -> bool:
    return any(w in text for w in words)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w'-]+", text.replace("́", ""))


def _case_link(sub: str) -> str | None:
    for words, url in _CASE_RULES:
        if _has(sub, words):
            return url
    if _has(sub, ("prepositional", "предложн")) and not _has(sub, ("direction", "accusative", "куда")):
        return f"{CASES}#prepositional"
    if _has(sub, _DIRECTION_WORDS):
        return f"{CASES}#location-direction"
    for words, case in _CASE_WORDS:
        if _has(sub, words):
            return f"{CASES}#{case}"
    return None


def _aspect_link(sub: str) -> str | None:
    if _has(sub, ("negat", "не надо", "не нужно", "prohibit", "нельзя")):
        return f"{ASPECT}#aspect-negation"
    if _has(sub, ("command", "imperative", "request", "императив")):
        return f"{ASPECT}#aspect-commands"
    if _has(sub, ("pair", "formation", "suffix", "prefix")):
        return f"{ASPECT}#aspect-pairs"
    if _has(sub, ("perfective", "imperfective", "completed", "sequence", "process", "repeat", "habit", "result")):
        return f"{ASPECT}#aspect-choose"
    return None


def _motion_link(sub: str) -> str | None:
    if _has(sub, ("prefix", "при-", "у-", "пере", "вы-", "до-", "про-", "arrive", "leave", "cross")):
        return f"{MOTION}#motion-prefixes"
    if _has(sub, ("conjugat", "present tense", "form")):
        return f"{MOTION}#motion-conjugation"
    if _has(sub, ("perfective", "imperfective", "aspect")):
        return f"{MOTION}#motion-aspect"
    if _has(sub, (" vs ", "versus", "uni", "multi", "round trip", "идти", "ходить", "ехать", "ездить", "лететь", "летать")):
        return f"{MOTION}#motion-use"
    return None


def _stress_link(sub: str) -> str | None:
    if "ё" in sub:
        return f"{STRESS}#stress-yo"
    if _has(sub, ("past", "feminine", "был", "жил")):
        return f"{STRESS}#stress-past"
    if _has(sub, ("verb", "present", "first person", "1sg")):
        return f"{STRESS}#stress-verbs"
    if _has(sub, ("mobile", "shift", "plural", "noun", "accusative")):
        return f"{STRESS}#stress-mobile"
    return None


def _word_choice_link(sub: str) -> str | None:
    toks = set(_tokens(sub))
    if toks & {"знать", "уметь", "мочь", "know", "can"} or _has(sub, ("знать", "уметь", "мочь")):
        return f"{PITFALLS}#pitfall-know-can"
    if "свой" in toks or "свой" in sub:
        return f"{PITFALLS}#pitfall-svoy"
    if toks & {"ты", "вы"} or _has(sub, ("formal", "informal", "polite")):
        return f"{PITFALLS}#pitfall-ty-vy"
    if _has(sub, ("у меня", "have", "possession")):
        return f"{PITFALLS}#pitfall-u-menya"
    if _has(sub, ("в/на", "в vs на", "в и на")):
        return f"{PITFALLS}#pitfall-v-na"
    return None


def _preposition_link(sub: str) -> str | None:
    toks = _tokens(sub)
    if "в" in toks or "на" in toks or _has(sub, ("в/на", "location", "direction")):
        return f"{CASES}#location-direction"
    if "с" in toks:
        return f"{CASES}#prep-s-instr" if _has(sub, ("instrumental", "with")) else f"{CASES}#prep-s-gen"
    for tok in toks:
        if tok in _PREP_IDS:
            return f"{CASES}#{_PREP_IDS[tok]}"
    return None


def _spelling_link(sub: str) -> str | None:
    return f"{CASES}#spelling-rules" if _has(sub, ("7", "5-letter", "ы", "и after", "unstressed")) else None


def _agreement_link(sub: str) -> str | None:
    if _has(sub, ("numeral", "number")):
        return f"{NUMBERS}#numbers-rule"
    if _has(sub, ("pronoun", "possessive", "свой", "мой", "этот")):
        return f"{CASES}#possessives"
    return None


_SPECIFIC = {
    "case": _case_link, "aspect": _aspect_link, "motion_verb": _motion_link, "stress": _stress_link,
    "word_choice": _word_choice_link, "preposition": _preposition_link, "spelling": _spelling_link,
    "agreement": _agreement_link,
}


def link_for(category: str | None, subcategory: str | None = None) -> str:
    """URL of the reference section that explains a mistake category/subcategory."""
    if not category:
        return "/grammar"
    category = category.strip().lower()
    base = CATEGORY_SECTION.get(category)
    if base is None:
        return "/grammar"
    sub = (subcategory or "").strip().lower()
    if sub and category in _SPECIFIC:
        found = _SPECIFIC[category](sub)
        if found:
            return found
    return base


# --------------------------------------------------------------------------------------------
# Markup for the content strings
# --------------------------------------------------------------------------------------------

_LINK_RE = re.compile(r"\[([^\[\]]+)\]\((/[^)\s]*)\)")
_RU_RE = re.compile(r"\[\[(.+?)\]\]", re.S)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)
_SPLIT_RE = re.compile(r"([^\s|,]*)\|([^\s|,]*)")


def _ru_span(m: re.Match) -> str:
    inner = _SPLIT_RE.sub(
        lambda p: p.group(1) + (f'<b class="end">{p.group(2)}</b>' if p.group(2) else ""), m.group(1))
    return f'<span lang="ru">{inner}</span>'


def rich(text: str | None) -> Markup:
    """Render a content string: [[Russian]] spans (with stem|ending highlight), **bold**, [links](/url)."""
    if not text:
        return Markup("")
    out = str(escape(stress(text)))
    out = _LINK_RE.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', out)
    out = _RU_RE.sub(_ru_span, out)
    out = _BOLD_RE.sub(r"<strong>\1</strong>", out)
    return Markup(out)


def gform(spec: str | None) -> Markup:
    """Render one paradigm cell such as 'стол|а́' (alternatives separated by ', ')."""
    return rich(f"[[{spec}]]") if spec else Markup("")


def ru_text(text: str | None) -> Markup:
    """Plain Russian text (stress already marked) in a lang="ru" span."""
    return Markup('<span lang="ru">{}</span>').format(stress(text or ""))

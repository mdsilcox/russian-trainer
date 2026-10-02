"""Grammar reference pages: /grammar and its six sections."""

from fastapi import APIRouter, Request

from app import grammar_content as gc
from app.services.grammar import gform, ru_text, rich
from app.web import templates

router = APIRouter()

templates.env.filters["rich"] = rich
templates.env.filters["gform"] = gform
templates.env.filters["ru_text"] = ru_text

CASE_INDEX = {name: i for i, name in enumerate(gc.CASE_ORDER)}


def _page(request: Request, name: str, **context):
    base = {"nav_items": gc.SUBNAV, "active": name}
    return templates.TemplateResponse(request, f"grammar/{name}.html", {**base, **context})


@router.get("/grammar")
def index(request: Request):
    return _page(request, "index", sections=gc.SECTIONS, high_yield=gc.HIGH_YIELD)


@router.get("/grammar/cases")
def cases(request: Request):
    return _page(
        request, "cases", cases=gc.CASES, case_index=CASE_INDEX, paradigms=gc.PARADIGMS,
        adjectives=gc.ADJECTIVES, adjective_forms=gc.adjective_forms, pronouns=gc.PRONOUNS,
        pron_after=gc.PRON_AFTER, possessives=gc.POSSESSIVES, location=gc.LOCATION_DIRECTION,
        prepositions=gc.PREPOSITIONS, spelling=gc.SPELLING_RULES)


@router.get("/grammar/numbers")
def numbers(request: Request):
    return _page(
        request, "numbers", rule=gc.NUMBERS_RULE, gender=gc.NUMBER_GENDER, nouns=gc.NUMBER_NOUNS,
        blocks=[gc.NUMBER_EXAMPLES[k] for k in ("money", "time", "years")], words=gc.NUMBER_WORDS)


@router.get("/grammar/motion")
def motion(request: Request):
    return _page(
        request, "motion", pairs=gc.MOTION_PAIRS, conj=gc.MOTION_CONJ, use=gc.MOTION_USE,
        prefixes=gc.MOTION_PREFIXES, core=gc.MOTION_CORE)


@router.get("/grammar/aspect")
def aspect(request: Request):
    return _page(
        request, "aspect", choose=gc.ASPECT_CHOOSE, negation=gc.ASPECT_NEGATION, commands=gc.ASPECT_COMMANDS,
        pairs=gc.ASPECT_PAIRS, formation=gc.ASPECT_FORMATION)


@router.get("/grammar/stress")
def stress(request: Request):
    return _page(request, "stress", patterns=gc.STRESS_PATTERNS, lookup=gc.STRESS_LOOKUP)


@router.get("/grammar/pitfalls")
def pitfalls(request: Request):
    return _page(request, "pitfalls", pitfalls=gc.PITFALLS)

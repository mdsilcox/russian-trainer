import re
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from app import grammar_content as gc
from app.grammar_content import plain
from app.main import app
from app.services.grammar import CATEGORY_SECTION, link_for

ACUTE = "́"
PAGES = ["/grammar", "/grammar/cases", "/grammar/numbers", "/grammar/motion", "/grammar/aspect",
         "/grammar/stress", "/grammar/pitfalls"]


@pytest.fixture(scope="module")
def pages():
    client = TestClient(app)
    out = {}
    for url in PAGES:
        r = client.get(url)
        assert r.status_code == 200, url
        out[url] = r.text
    return out


class _Ids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k == "id":
                self.ids.append(v)


def ids_of(html: str) -> list[str]:
    p = _Ids()
    p.feed(html)
    return p.ids


def para(key):
    return next(p for p in gc.PARADIGMS if p["key"] == key)


def forms(p, number):
    return [plain(f) for f in p[number]]


# ---- key paradigm cells (checked against English Wiktionary) ----

def test_genitive_plural_cells():
    assert plain(para("f-velar")["pl"][1]) == "книг"  # one syllable: no stress mark
    assert plain(para("m-hard")["pl"][1]) == "столо" + ACUTE + "в"
    assert plain(para("m-soft")["pl"][1]) == "рубле" + ACUTE + "й"
    assert plain(para("n-hard")["pl"][1]) == "о" + ACUTE + "кон"
    assert plain(para("n-ie")["pl"][1]) == "зда" + ACUTE + "ний"


def test_singular_cells():
    assert plain(para("f-velar")["sg"][4]) == "кни" + ACUTE + "гой"
    assert plain(para("f-soft")["sg"][3]) == "неде" + ACUTE + "лю"
    assert plain(para("n-hard")["sg"][5]) == "окне" + ACUTE
    assert plain(para("f-soft-sign")["sg"][4]) == "две" + ACUTE + "рью"
    assert plain(para("m-hard")["sg"][5]) == "столе" + ACUTE


def test_prepositional_locative_and_animate():
    rows = {r[0]: r[1] for r in gc.CASE_BY_ID["prepositional"]["subs"][0]["table"]["rows"]}
    assert plain(rows["[[аэропо" + ACUTE + "рт]]"]) == "в аэропорту" + ACUTE
    assert "в саду" + ACUTE in plain(rows["[[сад]]"])
    assert "на мосту" + ACUTE in plain(rows["[[мост]]"])
    animate = {r[1]: r[2] for r in gc.CASE_BY_ID["accusative"]["subs"][0]["table"]["rows"]}
    assert plain(animate["[[брат]]"]) == "бра" + ACUTE + "та"


def test_adjective_tables():
    assert [plain(f) for f in gc.adjective_forms("hard", "genitive")] == ["но" + ACUTE + "вого", "но" + ACUTE + "вого", "но" + ACUTE + "вой", "но" + ACUTE + "вых"]
    acc = [plain(f) for f in gc.adjective_forms("hard", "accusative")]
    assert acc == ["но" + ACUTE + "вый", "но" + ACUTE + "вого", "но" + ACUTE + "вое", "но" + ACUTE + "вую", "но" + ACUTE + "вые", "но" + ACUTE + "вых"]
    assert plain(gc.adjective_forms("soft", "prepositional")[0]) == "си" + ACUTE + "нем"
    assert plain(gc.adjective_forms("mixed", "genitive")[0]) == "хоро" + ACUTE + "шего"
    assert plain(gc.adjective_forms("end", "instrumental")[0]) == "больши" + ACUTE + "м"


def test_pronouns():
    by = {p["w"]: p["forms"] for p in gc.PRONOUNS}
    assert by["я"][1:] == ["меня" + ACUTE, "мне", "меня" + ACUTE, "мно" + ACUTE + "й", "мне"]
    assert by["он / оно" + ACUTE][5] == "нём"
    assert gc.PRON_AFTER["genitive"]["она" + ACUTE] == "у неё"


def test_motion_conjugation():
    rows = {r[0]: r[1:] for r in gc.MOTION_CONJ["rows"]}
    assert rows["я"] == ["иду" + ACUTE, "хожу" + ACUTE, "е" + ACUTE + "ду", "е" + ACUTE + "зжу"]
    assert rows["он / она" + ACUTE][1] == "хо" + ACUTE + "дит"
    assert rows["прошедшее м."][0] == "шёл"
    assert rows["ж."][0] == "шла" + ACUTE


def test_stress_marks_never_follow_yo_and_no_leftover_markers(pages):
    for url, html in pages.items():
        assert "ё" + ACUTE not in html, url
        assert not re.search(r"[аеиоуыэюяАЕИОУЫЭЮЯ]'", html.replace("&#39;", "'")), url
        assert "[[" not in html and "]]" not in html and "**" not in html, url
    for name in dir(gc):
        if name.isupper():
            assert "ё" + ACUTE not in str(getattr(gc, name)), name


# ---- pages ----

def test_every_page_has_subnav_and_unique_ids(pages):
    for url, html in pages.items():
        assert 'class="g-subnav"' in html, url
        for label in ("Cases", "Numbers", "Motion", "Aspect", "Stress", "Pitfalls"):
            assert f">{label}</a>" in html, (url, label)
        ids = ids_of(html)
        dupes = {i for i in ids if ids.count(i) > 1}
        assert not dupes, (url, dupes)
        assert "grammar.css" in html


def test_cases_page_structure(pages):
    html = pages["/grammar/cases"]
    ids = set(ids_of(html))
    for anchor in ["location-direction", "nominative", "genitive", "genitive-plural", "dative", "accusative",
                   "animate-accusative", "instrumental", "prepositional", "prepositional-locative",
                   "prepositions", "prep-v", "prep-na", "prep-iz", "prep-s-gen", "prep-s-instr",
                   "adjectives", "pronouns", "possessives", "spelling-rules", "genitive-nouns",
                   "dative-adjectives", "accusative-pronouns"]:
        assert anchor in ids, anchor
    assert "в аэропорту" + ACUTE in html
    assert 'class="g-table-wrap"' in html
    assert 'data-rise style="--r:' in html
    assert "7-letter rule" in html and "5-letter rule" in html


def test_numbers_page(pages):
    html = pages["/grammar/numbers"]
    ids = set(ids_of(html))
    assert {"numbers-rule", "numbers-money", "numbers-time", "numbers-years"} <= ids
    for form in ["рубле" + ACUTE + "й", "рубля" + ACUTE, "лет", "го" + ACUTE + "да", "одна" + ACUTE]:
        assert form in html, form


def test_other_pages_anchors(pages):
    expect = {
        "/grammar/motion": ["motion-pairs", "motion-conjugation", "motion-use", "motion-prefixes", "motion-aspect", "motion-core"],
        "/grammar/aspect": ["aspect-choose", "aspect-negation", "aspect-commands", "aspect-pairs", "aspect-formation"],
        "/grammar/stress": ["stress-why", "stress-patterns", "stress-yo", "stress-mobile", "stress-past", "stress-verbs", "stress-lookup"],
        "/grammar/pitfalls": ["pitfall-u-menya", "pitfall-svoy", "pitfall-know-can", "pitfall-v-na", "pitfall-ty-vy"],
        "/grammar": ["high-yield", "contents"],
    }
    for url, anchors in expect.items():
        ids = set(ids_of(pages[url]))
        for a in anchors:
            assert a in ids, (url, a)
    stress = pages["/grammar/stress"]
    for link in ["openrussian.org", "en.wiktionary.org", "forvo.com"]:
        assert link in stress


# ---- link_for ----

@pytest.mark.parametrize("category, sub, expected", [
    ("case", "genitive plural", "/grammar/cases#genitive-plural"),
    ("case", "Genitive plural after numerals", "/grammar/numbers#numbers-rule"),
    ("case", "genitive after numerals 5+", "/grammar/numbers#numbers-rule"),
    ("case", "animate accusative", "/grammar/cases#animate-accusative"),
    ("case", "prepositional after в/на", "/grammar/cases#prepositional"),
    ("case", "accusative of direction after в/на", "/grammar/cases#location-direction"),
    ("case", "locative -у", "/grammar/cases#prepositional-locative"),
    ("case", "dative", "/grammar/cases#dative"),
    ("case", "instrumental after с", "/grammar/cases#instrumental"),
    ("case", "genitive after нет", "/grammar/cases#genitive"),
    ("case", None, "/grammar/cases"),
    ("case", "something odd", "/grammar/cases"),
    ("aspect", "perfective for one completed action", "/grammar/aspect#aspect-choose"),
    ("aspect", "imperfective after не надо", "/grammar/aspect#aspect-negation"),
    ("aspect", "polite command", "/grammar/aspect#aspect-commands"),
    ("aspect", None, "/grammar/aspect"),
    ("motion_verb", "идти vs ходить", "/grammar/motion#motion-use"),
    ("motion_verb", "ехать vs идти", "/grammar/motion#motion-use"),
    ("motion_verb", "wrong prefix при-/у-", "/grammar/motion#motion-prefixes"),
    ("motion_verb", None, "/grammar/motion"),
    ("stress", None, "/grammar/stress"),
    ("stress", "past tense feminine", "/grammar/stress#stress-past"),
    ("word_choice", "знать vs уметь", "/grammar/pitfalls#pitfall-know-can"),
    ("word_choice", "ты vs вы", "/grammar/pitfalls#pitfall-ty-vy"),
    ("word_choice", "свой vs мой", "/grammar/pitfalls#pitfall-svoy"),
    ("preposition", "в vs на", "/grammar/cases#location-direction"),
    ("preposition", "wrong preposition из", "/grammar/cases#prep-iz"),
    ("preposition", None, "/grammar/cases#prepositions"),
    ("agreement", "adjective gender", "/grammar/cases#adjectives"),
    ("spelling", None, "/grammar/cases#spelling-rules"),
    ("participle", None, "/grammar"),
    ("word_order", None, "/grammar/pitfalls"),
    ("idiom", None, "/grammar/pitfalls"),
    (None, None, "/grammar"),
    ("unknown-category", "x", "/grammar"),
])
def test_link_for(category, sub, expected):
    assert link_for(category, sub) == expected


def test_link_for_targets_exist(pages):
    """Every URL link_for can produce for the sampled subcategories points at a real anchor."""
    subs = ["", "genitive plural", "genitive after numerals 5+", "animate accusative", "prepositional after в/на",
            "direction", "locative", "dative", "accusative", "instrumental", "nominative", "genitive", "negation",
            "command", "completed", "pair", "идти vs ходить", "prefix", "perfective", "mobile", "past",
            "знать", "свой", "ты", "у меня", "в/на", "из", "по", "с instrumental", "с", "adjective", "pronoun"]
    urls = set()
    for category in list(CATEGORY_SECTION) + [None]:
        for sub in subs:
            urls.add(link_for(category, sub))
    assert len(urls) > 20
    for url in urls:
        path, _, frag = url.partition("#")
        assert path in pages, url
        if frag:
            assert frag in ids_of(pages[path]), url


# ---- living tables and the word-change morph ----

def test_living_table_endings_and_chips(pages):
    html = pages["/grammar/cases"]
    assert 'id="case-table"' in html and "data-living" in html
    for case in gc.CASE_ORDER:
        assert f'<tr data-case="{case}">' in html
        assert f'class="g-cname" data-case="{case}"' in html
        assert f'class="g-chip" data-case="{case}"' in html
    # endings sit in their own spans with a case marker and a stagger index
    assert re.search(r'<span lang="ru">стол<b class="end" data-case="genitive" style="--i:0">а' + ACUTE + r'</b></span>', html)
    assert re.search(r'<b class="end" data-case="genitive" style="--i:3">ы' + ACUTE, html) is None  # gen pl is -ов
    assert re.search(r'книг<b class="end zero" data-case="genitive" style="--i:4">', html)
    assert "zero ending" in html
    assert "grammar.js" in html


def test_morph_panel_forms_and_fallback(pages):
    html = pages["/grammar/cases"]
    assert 'id="word-change"' in html and "Watch the word change" in html and "data-morph-live" in html
    paths = {q["name"]: q["path"] for q in gc.MORPH}
    assert paths["Genitive sg and pl"] == f"стол → стола{ACUTE} → столо{ACUTE}в"
    assert paths["Zero ending"] == f"кни{ACUTE}га → книг"
    assert paths["Inserted vowel and stress shift"] == f"окно{ACUTE} → о{ACUTE}кон"
    assert paths["Mobile stress"] == f"рука{ACUTE} → ру{ACUTE}ку"
    # no-JS fallback lists every form and rule in the HTML
    static = html.split("data-morph-static", 1)[1].split("data-morph-live", 1)[0]
    for text in ("стола" + ACUTE, "столо" + ACUTE + "в", "книг", "о" + ACUTE + "кон", "ру" + ACUTE + "ку"):
        assert text in static
    assert "книг" + ACUTE not in html and "книѓ" not in html
    assert "\u2014" not in static


def test_morph_data_matches_paradigms():
    assert plain(para("m-hard")["sg"][1]) == gc.MORPH[0]["forms"][1]["text"]
    assert plain(para("m-hard")["pl"][1]) == gc.MORPH[0]["forms"][2]["text"]
    assert plain(para("f-velar")["pl"][1]).replace(ACUTE, "") == gc.MORPH[1]["forms"][1]["text"]  # monosyllable: the morph shows no mark
    assert plain(para("n-hard")["pl"][1]) == gc.MORPH[2]["forms"][1]["text"]
    assert plain(para("f-velar")["sg"][0]) == gc.MORPH[1]["forms"][0]["text"]
    assert plain(para("n-hard")["sg"][0]) == gc.MORPH[2]["forms"][0]["text"]

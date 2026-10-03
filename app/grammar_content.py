"""Structured content for the grammar reference (section «Грамматика»).

Authoring conventions (applied by `_finish` at import time):
  * A stress mark is written as an apostrophe straight after the vowel ("кни'га"); it becomes the
    combining acute U+0301. Never write it after ё (ё is always stressed).
  * `[[...]]` marks Russian text (rendered in a lang="ru" span). Inside it, "|" separates a stem
    from its ending ("кни'г|а") so the ending can be highlighted. "**x**" is bold.
Forms were checked against English Wiktionary paradigm tables (see docs in the final report).
"""

import re
from copy import deepcopy

ACUTE = "́"
_STRESS_RE = re.compile("([аеиоуыэюяАЕИОУЫЭЮЯ])'")


def stress(s: str) -> str:
    """'кни'га' -> 'кни́га' (apostrophe after a Cyrillic vowel becomes U+0301)."""
    return _STRESS_RE.sub("\\1" + ACUTE, s)


def plain(s: str) -> str:
    """Strip the stem|ending separator and the markup: handy for tests and search."""
    return stress(s).replace("|", "").replace("[[", "").replace("]]", "").replace("**", "")


def _finish(x):
    if isinstance(x, str):
        return stress(x)
    if isinstance(x, list):
        return [_finish(i) for i in x]
    if isinstance(x, tuple):
        return tuple(_finish(i) for i in x)
    if isinstance(x, dict):
        return {_finish(k): _finish(v) for k, v in x.items()}
    return x


# --------------------------------------------------------------------------------------------
# Navigation
# --------------------------------------------------------------------------------------------

SUBNAV = [
    ("cases", "Cases", "/grammar/cases"),
    ("numbers", "Numbers", "/grammar/numbers"),
    ("motion", "Motion", "/grammar/motion"),
    ("aspect", "Aspect", "/grammar/aspect"),
    ("stress", "Stress", "/grammar/stress"),
    ("pitfalls", "Pitfalls", "/grammar/pitfalls"),
]

SECTIONS = [
    {"key": "cases", "url": "/grammar/cases", "title": "Cases", "ru": "Падежи'",
     "blurb": "What each of the six cases does, which prepositions take it, and compact ending tables for nouns, adjectives and pronouns.",
     "links": [("Location vs direction", "location-direction"), ("Genitive plural", "genitive-plural"),
               ("Animate accusative", "animate-accusative"), ("Preposition lookup", "prepositions")]},
    {"key": "numbers", "url": "/grammar/numbers", "title": "Numbers", "ru": "Числи'тельные",
     "blurb": "The 1 / 2-4 / 5+ rule for prices, times and ages, with один/одна/одно, два/две, год/года/лет.",
     "links": [("The rule", "numbers-rule"), ("Money", "numbers-money"), ("Age and years", "numbers-years")]},
    {"key": "motion", "url": "/grammar/motion", "title": "Verbs of motion", "ru": "Глаго'лы движе'ния",
     "blurb": "Walking vs riding, one way vs round trip, and the prefixes that turn them into arriving, leaving, crossing.",
     "links": [("Pairs", "motion-pairs"), ("Prefix chart", "motion-prefixes"), ("Travel core", "motion-core")]},
    {"key": "aspect", "url": "/grammar/aspect", "title": "Aspect", "ru": "Вид глаго'ла",
     "blurb": "Perfective or imperfective: result against process, plus negation and commands.",
     "links": [("How to choose", "aspect-choose"), ("Common pairs", "aspect-pairs"), ("Commands", "aspect-commands")]},
    {"key": "stress", "url": "/grammar/stress", "title": "Stress", "ru": "Ударе'ние",
     "blurb": "Why it matters, ё, the recurring mobile-stress patterns, and where to look a word up.",
     "links": [("Patterns", "stress-patterns"), ("Look it up", "stress-lookup")]},
    {"key": "pitfalls", "url": "/grammar/pitfalls", "title": "Pitfalls", "ru": "Типи'чные оши'бки",
     "blurb": "Right and wrong pairs for the mistakes English speakers make most.",
     "links": [("у меня' есть", "pitfall-u-menya"), ("в vs на", "pitfall-v-na"), ("ты vs вы", "pitfall-ty-vy")]},
]

HIGH_YIELD = [
    {"n": "1", "title": "Prepositional after в/на", "ru": "в метро', на вокза'ле, в аэропорту'",
     "url": "/grammar/cases#prepositional"},
    {"n": "2", "title": "Accusative for direction, and animate accusative", "ru": "в Москву', на Кра'сную пло'щадь, ви'жу бра'та",
     "url": "/grammar/cases#location-direction"},
    {"n": "3", "title": "Genitive and genitive plural", "ru": "нет биле'та, пять рубле'й, мно'го люде'й",
     "url": "/grammar/cases#genitive-plural"},
    {"n": "4", "title": "Dative: needs, likes, destinations", "ru": "мне ну'жно, мне нра'вится, к врачу'",
     "url": "/grammar/cases#dative"},
    {"n": "5", "title": "Instrumental: with, and professions", "ru": "ко'фе с молоко'м, рабо'таю врачо'м",
     "url": "/grammar/cases#instrumental"},
    {"n": "6", "title": "Numerals: 1 / 2-4 / 5+", "ru": "оди'н рубль, два рубля', пять рубле'й",
     "url": "/grammar/numbers#numbers-rule"},
]

# --------------------------------------------------------------------------------------------
# Paradigms (order of forms: N G D A I P). "|" splits stem and ending; alternatives after ", ".
# Verified against English Wiktionary: стол, книга, окно, тётя (sg), здание, дверь, рубль,
# музей, аэропорт. комната, неделя, станция follow the same patterns (stress fixed on stem
# or pattern b as noted).
# --------------------------------------------------------------------------------------------

CASE_ORDER = ["nominative", "genitive", "dative", "accusative", "instrumental", "prepositional"]

PARADIGMS = [
    {"key": "m-hard", "label": "Masc. hard", "word": "стол", "gloss": "table",
     "sg": ["стол|", "стол|а'", "стол|у'", "стол|", "стол|о'м", "стол|е'"],
     "pl": ["стол|ы'", "стол|о'в", "стол|а'м", "стол|ы'", "стол|а'ми", "стол|а'х"]},
    {"key": "m-hard-stem", "label": "Masc. hard, stem stress", "word": "биле'т", "gloss": "ticket",
     "sg": ["биле'т|", "биле'т|а", "биле'т|у", "биле'т|", "биле'т|ом", "биле'т|е"],
     "pl": ["биле'т|ы", "биле'т|ов", "биле'т|ам", "биле'т|ы", "биле'т|ами", "биле'т|ах"]},
    {"key": "m-soft", "label": "Masc. soft (-ь)", "word": "рубль", "gloss": "rouble",
     "sg": ["ру'бл|ь", "рубл|я'", "рубл|ю'", "ру'бл|ь", "рубл|ём", "рубл|е'"],
     "pl": ["рубл|и'", "рубл|е'й", "рубл|я'м", "рубл|и'", "рубл|я'ми", "рубл|я'х"]},
    {"key": "m-j", "label": "Masc. -й", "word": "музе'й", "gloss": "museum",
     "sg": ["музе'|й", "музе'|я", "музе'|ю", "музе'|й", "музе'|ем", "музе'|е"],
     "pl": ["музе'|и", "музе'|ев", "музе'|ям", "музе'|и", "музе'|ями", "музе'|ях"]},
    {"key": "f-hard", "label": "Fem. hard (-а)", "word": "ко'мната", "gloss": "room",
     "sg": ["ко'мнат|а", "ко'мнат|ы", "ко'мнат|е", "ко'мнат|у", "ко'мнат|ой", "ко'мнат|е"],
     "pl": ["ко'мнат|ы", "ко'мнат|", "ко'мнат|ам", "ко'мнат|ы", "ко'мнат|ами", "ко'мнат|ах"]},
    {"key": "f-velar", "label": "Fem. after г/к/х", "word": "кни'га", "gloss": "book",
     "sg": ["кни'г|а", "кни'г|и", "кни'г|е", "кни'г|у", "кни'г|ой", "кни'г|е"],
     "pl": ["кни'г|и", "книг|", "кни'г|ам", "кни'г|и", "кни'г|ами", "кни'г|ах"]},
    {"key": "f-soft", "label": "Fem. soft (-я)", "word": "неде'ля", "gloss": "week",
     "sg": ["неде'л|я", "неде'л|и", "неде'л|е", "неде'л|ю", "неде'л|ей", "неде'л|е"],
     "pl": ["неде'л|и", "неде'л|ь", "неде'л|ям", "неде'л|и", "неде'л|ями", "неде'л|ях"]},
    {"key": "f-ia", "label": "Fem. -ия", "word": "ста'нция", "gloss": "station",
     "sg": ["ста'нци|я", "ста'нци|и", "ста'нци|и", "ста'нци|ю", "ста'нци|ей", "ста'нци|и"],
     "pl": ["ста'нци|и", "ста'нци|й", "ста'нци|ям", "ста'нци|и", "ста'нци|ями", "ста'нци|ях"]},
    {"key": "f-soft-sign", "label": "Fem. -ь", "word": "дверь", "gloss": "door",
     "sg": ["две'р|ь", "две'р|и", "две'р|и", "две'р|ь", "две'р|ью", "две'р|и"],
     "pl": ["две'р|и", "двер|е'й", "двер|я'м", "две'р|и", "двер|я'ми", "двер|я'х"]},
    {"key": "n-hard", "label": "Neut. hard (-о)", "word": "окно'", "gloss": "window",
     "sg": ["окн|о'", "окн|а'", "окн|у'", "окн|о'", "окн|о'м", "окн|е'"],
     "pl": ["о'кн|а", "о'кон|", "о'кн|ам", "о'кн|а", "о'кн|ами", "о'кн|ах"]},
    {"key": "n-ie", "label": "Neut. -ие", "word": "зда'ние", "gloss": "building",
     "sg": ["зда'ни|е", "зда'ни|я", "зда'ни|ю", "зда'ни|е", "зда'ни|ем", "зда'ни|и"],
     "pl": ["зда'ни|я", "зда'ни|й", "зда'ни|ям", "зда'ни|я", "зда'ни|ями", "зда'ни|ях"]},
]

# Adjectives are generated from stem + ending sets (checked against Wiktionary for новый, синий,
# хороший; большой is the stressed -ой type). Order of nom: m, n, f, pl.
_ADJ_ENDINGS = {
    "hard": {
        "nominative": ["ый", "ое", "ая", "ые"], "genitive": ["ого", "ого", "ой", "ых"],
        "dative": ["ому", "ому", "ой", "ым"], "accusative": ["ый", "ого", "ое", "ую", "ые", "ых"],
        "instrumental": ["ым", "ым", "ой", "ыми"], "prepositional": ["ом", "ом", "ой", "ых"],
    },
    "soft": {
        "nominative": ["ий", "ее", "яя", "ие"], "genitive": ["его", "его", "ей", "их"],
        "dative": ["ему", "ему", "ей", "им"], "accusative": ["ий", "его", "ее", "юю", "ие", "их"],
        "instrumental": ["им", "им", "ей", "ими"], "prepositional": ["ем", "ем", "ей", "их"],
    },
    "mixed": {
        "nominative": ["ий", "ее", "ая", "ие"], "genitive": ["его", "его", "ей", "их"],
        "dative": ["ему", "ему", "ей", "им"], "accusative": ["ий", "его", "ее", "ую", "ие", "их"],
        "instrumental": ["им", "им", "ей", "ими"], "prepositional": ["ем", "ем", "ей", "их"],
    },
    "end": {
        "nominative": ["о'й", "о'е", "а'я", "и'е"], "genitive": ["о'го", "о'го", "о'й", "и'х"],
        "dative": ["о'му", "о'му", "о'й", "и'м"], "accusative": ["о'й", "о'го", "о'е", "у'ю", "и'е", "и'х"],
        "instrumental": ["и'м", "и'м", "о'й", "и'ми"], "prepositional": ["о'м", "о'м", "о'й", "и'х"],
    },
}
ADJECTIVES = [
    {"key": "hard", "label": "Hard", "word": "но'вый", "gloss": "new", "stem": "но'в"},
    {"key": "soft", "label": "Soft", "word": "си'ний", "gloss": "dark blue", "stem": "си'н"},
    {"key": "mixed", "label": "After ш/ж/ч/щ", "word": "хоро'ший", "gloss": "good", "stem": "хоро'ш"},
    {"key": "end", "label": "Stressed ending", "word": "большо'й", "gloss": "big", "stem": "больш"},
]


def adjective_forms(adj_key: str, case: str) -> list[str]:
    stem = next(a["stem"] for a in ADJECTIVES if a["key"] == adj_key)
    return [f"{stem}|{e}" for e in _ADJ_ENDINGS[adj_key][case]]


# Personal pronouns: forms per case, and the н- form used after a preposition (3rd person only).
PRONOUNS = [
    {"w": "я", "forms": ["я", "меня'", "мне", "меня'", "мно'й", "мне"], "after": None},
    {"w": "ты", "forms": ["ты", "тебя'", "тебе'", "тебя'", "тобо'й", "тебе'"], "after": None},
    {"w": "он / оно'", "forms": ["он", "его'", "ему'", "его'", "им", "нём"], "after": "н"},
    {"w": "она'", "forms": ["она'", "её", "ей", "её", "ей", "ней"], "after": "н"},
    {"w": "мы", "forms": ["мы", "нас", "нам", "нас", "на'ми", "нас"], "after": None},
    {"w": "вы", "forms": ["вы", "вас", "вам", "вас", "ва'ми", "вас"], "after": None},
    {"w": "они'", "forms": ["они'", "их", "им", "их", "и'ми", "них"], "after": "н"},
]
# after a preposition, 3rd-person forms starting with a vowel get н- (their prepositional form already has it)
PRON_AFTER = {
    "genitive": {"он / оно'": "у него'", "она'": "у неё", "они'": "у них"},
    "dative": {"он / оно'": "к нему'", "она'": "к ней", "они'": "к ним"},
    "accusative": {"он / оно'": "в него'", "она'": "в неё", "они'": "в них"},
    "instrumental": {"он / оно'": "с ним", "она'": "с ней", "они'": "с ни'ми"},
    "prepositional": {"он / оно'": "о нём", "она'": "о ней", "они'": "о них"},
}

# Possessive мой and demonstrative этот: rows by case, columns M N F Pl.
POSSESSIVES = {
    "мой": {
        "nominative": ["мой", "моё", "моя'", "мои'"],
        "genitive": ["моего'", "моего'", "мое'й", "мои'х"],
        "dative": ["моему'", "моему'", "мое'й", "мои'м"],
        "accusative": ["мой / моего'", "моё", "мою'", "мои' / мои'х"],
        "instrumental": ["мои'м", "мои'м", "мое'й", "мои'ми"],
        "prepositional": ["моём", "моём", "мое'й", "мои'х"],
    },
    "э'тот": {
        "nominative": ["э'тот", "э'то", "э'та", "э'ти"],
        "genitive": ["э'того", "э'того", "э'той", "э'тих"],
        "dative": ["э'тому", "э'тому", "э'той", "э'тим"],
        "accusative": ["э'тот / э'того", "э'то", "э'ту", "э'ти / э'тих"],
        "instrumental": ["э'тим", "э'тим", "э'той", "э'тими"],
        "prepositional": ["э'том", "э'том", "э'той", "э'тих"],
    },
}

# --------------------------------------------------------------------------------------------
# Cases
# --------------------------------------------------------------------------------------------

CASES = [
    {
        "id": "nominative", "name": "Nominative", "ru": "Имени'тельный", "q": "кто? что?",
        "gist": "The dictionary form: who or what does something, or is something.",
        "functions": [
            "**Subject**: [[Москва' большая.]] / [[Мой па'спорт здесь.]]",
            "**Naming and identifying**: [[Меня' зову'т Ми'ша.]] / [[Э'то апте'ка.]]",
            "**The thing described, with no verb in the present**: [[Он врач.]] (no «is»; never [[есть]] here)",
            "**After the number 1** (and 21, 31...): [[оди'н биле'т]]. Numbers 2+ switch to the genitive; see [Numbers](/grammar/numbers).",
            "Signs and lists: [[Вход]], [[Вы'ход]], [[Метро']].",
            "**Not** after [[нет]]: «there is no ticket» is [[нет биле'та]] (genitive).",
        ],
        "preps": [],
        "examples": [
            ("Э'то мой па'спорт.", "This is my passport."),
            ("Москва' — столи'ца Росси'и.", "Moscow is the capital of Russia."),
            ("Вот апте'ка.", "Here is a pharmacy."),
            ("Мой брат — студе'нт.", "My brother is a student."),
        ],
        "subs": [
            {"id": "nominative-plural", "title": "Nominative plural", "ru": "Мно'жественное число'",
             "intro": [
                 "Most nouns take **-ы** or **-и** ([[стол → столы']], [[кни'га → кни'ги]]); after г к х ж ч ш щ and for soft nouns it is **-и**.",
                 "Neuter nouns take **-а/-я**: [[окно' → о'кна]], [[зда'ние → зда'ния]].",
                 "A group of common masculine nouns take stressed **-а'/-я'** in the plural. Learn these as vocabulary: [[дом → дома']], [[го'род → города']], [[па'спорт → паспорта']], [[а'дрес → адреса']], [[но'мер → номера']], [[учи'тель → учителя']], [[глаз → глаза']].",
             ]},
        ],
    },
    {
        "id": "genitive", "name": "Genitive", "ru": "Роди'тельный", "q": "кого'? чего'?",
        "gist": "The busiest case: of, absence, quantity, from, and after numbers 5 and up.",
        "functions": [
            "**Possession and «of»**: [[кни'га бра'та]] (my brother's book), [[ста'нция метро']] (a metro station).",
            "**Absence**: [[нет]] + genitive: [[нет биле'та]], [[нет вре'мени]]. Past: [[не' было вре'мени]].",
            "**Having**: [[у меня' есть]] + nominative thing, with [[у]] + genitive of the owner: [[у вас есть ка'рта?]]",
            "**Quantity**: [[ско'лько]], [[мно'го]], [[ма'ло]], [[не'сколько]], [[буты'лка воды']], [[кусо'к хле'ба]].",
            "**Numbers**: 2-4 take genitive singular, 5+ genitive plural; see [Numbers](/grammar/numbers).",
            "**From / away from**: [[из]] (out of), [[с]] (off, from a [[на]] place), [[от]] (from a person or object).",
            "**Dates**: [[пя'тое сентября']] (the fifth of September).",
        ],
        "preps": [
            ("у", "at, by; owner of", "У меня' есть биле'т.", "I have a ticket."),
            ("от", "from (a person or thing), away from", "От гости'ницы до метро' — де'сять мину'т.", "From the hotel to the metro is ten minutes."),
            ("до", "until, as far as", "Как дойти' до Кра'сной пло'щади?", "How do I get to Red Square?"),
            ("из", "out of, from (the opposite of в)", "Я из Аме'рики.", "I am from America."),
            ("с", "off, from (the opposite of на)", "Мы прие'хали с вокза'ла.", "We came from the station."),
            ("без", "without", "Ко'фе без са'хара, пожа'луйста.", "Coffee without sugar, please."),
            ("для", "for (the benefit of)", "Э'то для вас.", "This is for you."),
            ("о'коло", "near, about", "О'коло вокза'ла есть апте'ка.", "There is a pharmacy near the station."),
            ("напро'тив", "opposite", "Магази'н напро'тив гости'ницы.", "The shop is opposite the hotel."),
            ("ми'мо", "past", "Иди'те ми'мо апте'ки.", "Walk past the pharmacy."),
            ("по'сле", "after", "По'сле у'жина мы идём в теа'тр.", "After dinner we go to the theater."),
            ("вокру'г", "around", "Вокру'г Кремля' мно'го тури'стов.", "There are many tourists around the Kremlin."),
        ],
        "examples": [
            ("У меня' нет вре'мени.", "I have no time."),
            ("Здесь нет метро'.", "There is no metro here."),
            ("Стака'н воды', пожа'луйста.", "A glass of water, please."),
            ("Ско'лько у вас дете'й?", "How many children do you have?"),
        ],
        "subs": [
            {"id": "genitive-plural", "title": "Genitive plural", "ru": "Роди'тельный мно'жественного числа'",
             "intro": [
                 "The hardest set of endings, and the one you need most: after **5 and up**, after [[мно'го]], [[ма'ло]], [[ско'лько]], [[не'сколько]], and for «none of»: [[нет биле'тов]].",
                 "Choose by the ending of the nominative **singular**. Many feminine and neuter nouns have a **zero ending**: the plural genitive is just the bare stem, often with a vowel inserted between two consonants.",
             ],
             "table": {
                 "id": "genitive-plural-table", "caption": "Genitive plural by noun type",
                 "head": ["Nominative singular ends in", "Genitive plural", "Examples"],
                 "rows": [
                     ["a hard consonant", "**-ов** (stress may move to the ending)", "[[биле'т → биле'тов]] · [[стол → столо'в]] · [[па'спорт → па'спортов]]"],
                     ["-ь, or ж ч ш щ", "**-ей**", "[[рубль → рубле'й]] · [[врач → враче'й]] · [[нож → ноже'й]] · [[день → дней]]"],
                     ["-й", "**-ев** (-ёв if the ending is stressed)", "[[музе'й → музе'ев]] · [[трамва'й → трамва'ев]]"],
                     ["-а, -о (hard)", "**zero**: the bare stem, with a vowel inserted if needed", "[[кни'га → книг]] · [[страна' → стран]] · [[ко'мната → ко'мнат]] · [[сло'во → слов]] · [[окно' → о'кон]]"],
                     ["-ка, -ок clusters", "zero ending with **о** or **е** inserted", "[[де'вушка → де'вушек]] · [[студе'нтка → студе'нток]] · [[копе'йка → копе'ек]] · [[письмо' → пи'сем]] · [[сестра' → сестёр]]"],
                     ["-я (soft)", "**-ь** (or -й after a vowel)", "[[неде'ля → неде'ль]] · [[семья' → семе'й]]"],
                     ["-ия, -ие", "**-ий**", "[[ста'нция → ста'нций]] · [[зда'ние → зда'ний]]"],
                     ["-ь (feminine)", "**-ей**", "[[дверь → двере'й]] · [[ночь → ноче'й]] · [[пло'щадь → площаде'й]]"],
                 ],
             },
             "table2": {
                 "id": "genitive-plural-irregular", "caption": "Irregular genitive plurals worth memorizing",
                 "head": ["Nominative", "Genitive plural", "Travel use"],
                 "rows": [
                     ["[[челове'к]] (person)", "[[люде'й]] after [[мно'го]], [[ма'ло]]; [[челове'к]] after numbers", "[[мно'го люде'й]] · [[пять челове'к]]"],
                     ["[[год]] (year)", "[[лет]] (after 5+, мно'го, не'сколько)", "[[пять лет]] · [[мно'го лет]]"],
                     ["[[ребёнок / де'ти]]", "[[дете'й]]", "[[дво'е дете'й]] (two children)"],
                     ["[[друг]]", "[[друзе'й]]", "[[мно'го друзе'й]]"],
                     ["[[раз]] (time, occasion)", "[[раз]] (unchanged)", "[[пять раз]]"],
                     ["[[де'ньги]] (money)", "[[де'нег]]", "[[нет де'нег]]"],
                     ["[[брат]], [[сын]], [[мать]]", "[[бра'тьев]], [[сынове'й]], [[матере'й]]", "[[нет бра'тьев]]"],
                 ],
             }},
        ],
    },
    {
        "id": "dative", "name": "Dative", "ru": "Да'тельный", "q": "кому'? чему'?",
        "gist": "The receiver and the one who feels or needs; also «toward» a person and «along».",
        "functions": [
            "**Receiver (to / for)**: [[Позвони'те мне.]] / [[Я дал ключ дру'гу.]]",
            "**Needs, likes, feelings**: [[Мне ну'жно...]], [[Мне нра'вится...]], [[Мне хо'лодно.]], [[Мне ну'жен врач.]]",
            "**Age**: [[Мне три'дцать пять лет.]] (numbers follow the 1 / 2-4 / 5+ rule).",
            "**Toward a person or place** with [[к]]: [[к врачу']], [[к метро']].",
            "**Along / by / on schedule** with [[по]]: [[по у'лице]], [[по телефо'ну]], [[по расписа'нию]].",
            "Mind the structure: [[Мне ну'жна ка'рта]]: the thing needed is the nominative subject, and agrees with the adjective [[ну'жен / нужна' / ну'жно / нужны']].",
        ],
        "preps": [
            ("к", "to, toward (a person or place), up to", "Мы идём к друзья'м.", "We are going to our friends'."),
            ("по", "along, around; by (phone); according to", "Мы идём по у'лице.", "We are walking along the street."),
            ("благодаря'", "thanks to", "Благодаря' вам мы нашли' гости'ницу.", "Thanks to you we found the hotel."),
        ],
        "examples": [
            ("Мне нра'вится Москва'.", "I like Moscow."),
            ("Мне ну'жно купи'ть биле'т.", "I need to buy a ticket."),
            ("Как пройти' к метро'?", "How do I get to the metro?"),
            ("Позвони'те мне, пожа'луйста.", "Please call me."),
        ],
    },
    {
        "id": "accusative", "name": "Accusative", "ru": "Вини'тельный", "q": "кого'? что?",
        "gist": "The thing you act on, and the place you are going to.",
        "functions": [
            "**Direct object**: [[Я покупа'ю биле'т.]] / [[Я ви'жу ма'му.]]",
            "**Direction** (куда'?) with [[в]] / [[на]]: [[Я е'ду в Москву'.]] / [[Мы идём на Кра'сную пло'щадь.]]",
            "**Time**: [[в пя'тницу]] (on Friday), [[на неде'лю]] (for a week, planned), [[че'рез час]] (in an hour), [[в три часа']].",
            "**For / in exchange**: [[Спаси'бо за по'мощь.]], [[биле'т на по'езд]] (a ticket for the train), [[плати'ть за ко'фе]].",
            "**Animate masculine and all animate plurals = genitive**: [[Я ви'жу бра'та.]] See the subsection below.",
            "Feminine -а/-я nouns change visibly: [[кни'га → кни'гу]], [[неде'ля → неде'лю]]. Masculine inanimate and neuter nouns stay the same as the nominative.",
        ],
        "preps": [
            ("в", "into (direction); at a time", "Я е'ду в Москву'.", "I am going to Moscow."),
            ("на", "onto, to (direction); for; at a time", "Мы идём на вокза'л.", "We are going to the station."),
            ("за", "for, in exchange for; behind (direction)", "Спаси'бо за по'мощь.", "Thanks for the help."),
            ("че'рез", "through; in (after a time)", "Авто'бус придёт че'рез пять мину'т.", "The bus will come in five minutes."),
            ("под", "under (direction: куда'?)", "Положи'те су'мку под стол.", "Put the bag under the table."),
            ("про", "about (informal)", "Расскажи' про Москву'.", "Tell me about Moscow."),
        ],
        "examples": [
            ("Я ви'жу ма'му.", "I see Mum."),
            ("Мы е'дем в Москву'.", "We are going to Moscow."),
            ("Мне ну'жен биле'т на по'езд.", "I need a train ticket."),
            ("Я хочу' ко'фе.", "I would like a coffee."),
        ],
        "subs": [
            {"id": "animate-accusative", "title": "Animate accusative", "ru": "Одушевлённый вини'тельный",
             "intro": [
                 "**Rule**: for **masculine singular** nouns that name people or animals, and for **all animate plurals**, the accusative is the same as the **genitive**. Inanimate nouns keep accusative = nominative. Feminine singular animates take the ordinary -у/-ю.",
                 "Adjectives, [[э'тот]], [[мой]] and [[кто]] follow: [[Я зна'ю э'того студе'нта.]] / [[Я ви'жу моего' бра'та.]] / [[Кого' вы ждёте?]]",
             ],
             "table": {
                 "id": "animate-accusative-table", "caption": "Nominative against accusative",
                 "head": ["Type", "Nominative", "Accusative", "Example"],
                 "rows": [
                     ["masc. sg. animate", "[[брат]]", "[[бра'та]]", "[[Я ви'жу бра'та.]]"],
                     ["masc. sg. animate", "[[студе'нт]]", "[[студе'нта]]", "[[Я зна'ю студе'нта.]]"],
                     ["masc. sg., name in -й", "[[Серге'й]]", "[[Серге'я]]", "[[Я жду Серге'я.]]"],
                     ["fem. sg. animate (ordinary)", "[[ма'ма]]", "[[ма'му]]", "[[Я ви'жу ма'му.]]"],
                     ["pl. animate masc.", "[[студе'нты]]", "[[студе'нтов]]", "[[Я зна'ю студе'нтов.]]"],
                     ["pl. animate fem.", "[[де'вушки]]", "[[де'вушек]]", "[[Я ви'жу де'вушек.]]"],
                     ["pl. irregular", "[[друзья']]", "[[друзе'й]]", "[[Я зна'ю э'тих друзе'й.]]"],
                     ["inanimate (no change)", "[[стол]] · [[столы']]", "[[стол]] · [[столы']]", "[[Я ви'жу стол.]]"],
                 ],
             }},
        ],
    },
    {
        "id": "instrumental", "name": "Instrumental", "ru": "Твори'тельный", "q": "кем? чем?",
        "gist": "With, by means of, and what someone works as or becomes.",
        "functions": [
            "**Accompaniment (with)**: [[с]] + instrumental: [[ко'фе с молоко'м]], [[Я е'ду с семьёй.]]",
            "**Means or tool**: [[запла'тить ка'ртой]] (pay by card), [[писа'ть ру'чкой]]. No preposition.",
            "**Profession, state, becoming** after [[быть]], [[стать]], [[рабо'тать]]: [[Я рабо'таю врачо'м.]] / [[Он стал инжене'ром.]]",
            "**Interests and activities**: [[интересова'ться му'зыкой]], [[занима'ться спо'ртом]].",
            "**Position (где?)**: [[пе'ред]] (in front of), [[за]] (behind), [[под]] (under), [[над]] (above), [[ме'жду]] (between), [[ря'дом с]] (next to).",
            "[[Меня' зову'т Ми'ша]]: the name stays nominative. [[с]] also takes genitive («off») and accusative («about»), so the case after it tells you which.",
        ],
        "preps": [
            ("с", "with", "Ко'фе с молоко'м, пожа'луйста.", "Coffee with milk, please."),
            ("пе'ред", "in front of; before", "Встре'тимся пе'ред теа'тром.", "Let's meet in front of the theater."),
            ("за", "behind, beyond (where?)", "Магази'н за угло'м.", "The shop is round the corner."),
            ("под", "under (where?)", "Су'мка под столо'м.", "The bag is under the table."),
            ("над", "above", "Над вхо'дом есть часы'.", "There is a clock above the entrance."),
            ("ме'жду", "between", "Апте'ка ме'жду ба'нком и магази'ном.", "The pharmacy is between the bank and the shop."),
            ("ря'дом с", "next to", "Мы живём ря'дом с метро'.", "We live next to the metro."),
        ],
        "examples": [
            ("Я рабо'таю врачо'м.", "I work as a doctor."),
            ("Мо'жно запла'тить ка'ртой?", "Can I pay by card?"),
            ("Ко'фе с молоко'м, пожа'луйста.", "Coffee with milk, please."),
            ("Мы идём с детьми'.", "We are going with the children."),
        ],
    },
    {
        "id": "prepositional", "name": "Prepositional", "ru": "Предло'жный", "q": "о ком? о чём?",
        "gist": "Where something is (with в or на), and what you talk or think about (with о). Never used without a preposition.",
        "functions": [
            "**Location (где?)** with [[в]] (inside) or [[на]] (on, at an open place or event): [[в метро']], [[на вокза'ле]], [[в гости'нице]].",
            "**About** with [[о / об / обо]]: [[Мы говори'м о Москве'.]] ([[об]] before a vowel: [[об Аме'рике]]; [[обо мне']]).",
            "**Stressed -у' form for some masculine nouns** after в/на: [[в аэропорту']], [[в саду']], [[на мосту']]; see the box below.",
            "Most nouns end in **-е**; nouns in -ие/-ия/-ий and feminine -ь take **-и**: [[в зда'нии]], [[в Росси'и]], [[на пло'щади]].",
            "Plural: **-ах / -ях**: [[в магази'нах]], [[на ста'нциях]].",
        ],
        "preps": [
            ("в", "in, inside; at", "Мы в гости'нице.", "We are in the hotel."),
            ("на", "on; at (open places, events, transport)", "Где ты? — На вокза'ле.", "Where are you? At the station."),
            ("о / об / обо", "about", "Мы говори'м о Москве'.", "We are talking about Moscow."),
            ("при", "in the presence of; attached to", "При гости'нице есть рестора'н.", "The hotel has a restaurant (attached)."),
        ],
        "examples": [
            ("Я живу' в Москве'.", "I live in Moscow."),
            ("Ваш биле'т на столе'.", "Your ticket is on the table."),
            ("Мы встре'тились в аэропорту'.", "We met at the airport."),
            ("Расскажи'те мне о го'роде.", "Tell me about the city."),
        ],
        "subs": [
            {"id": "prepositional-locative", "title": "The locative -у' forms", "ru": "Второ'й предло'жный",
             "intro": [
                 "About thirty common masculine nouns have a second prepositional ending, **stressed -у'/-ю'**, used **only after в or на for location**. With [[о]] you use the ordinary -е: [[в саду']] but [[о са'де]].",
                 "In speech some of them (for example [[аэропорт]]) are sometimes heard with -е, but the -у' form is the safe default for a traveler.",
             ],
             "table": {
                 "id": "prepositional-locative-table", "caption": "Common locative forms",
                 "head": ["Noun", "Location (в / на)", "Meaning"],
                 "rows": [
                     ["[[аэропо'рт]]", "[[в аэропорту']]", "at the airport"],
                     ["[[сад]]", "[[в саду']]", "in the garden"],
                     ["[[мост]]", "[[на мосту']]", "on the bridge"],
                     ["[[лес]]", "[[в лесу']]", "in the forest"],
                     ["[[у'гол]]", "[[в углу']] · [[на углу']]", "in the corner · on the corner"],
                     ["[[шкаф]]", "[[в шкафу']]", "in the wardrobe"],
                     ["[[пол]]", "[[на полу']]", "on the floor"],
                     ["[[бе'рег]]", "[[на берегу']]", "on the shore"],
                     ["[[год]]", "[[в году']]", "in the year: [[в э'том году']] (this year)"],
                     ["[[снег]]", "[[в снегу']]", "in the snow"],
                 ],
             }},
        ],
    },
]

# --------------------------------------------------------------------------------------------
# Location vs direction
# --------------------------------------------------------------------------------------------

LOCATION_DIRECTION = {
    "head": ["Question", "Meaning", "Pattern", "Example"],
    "rows": [
        ["[[где?]]", "where (at)", "в / на + prepositional", "[[Я в Москве'. / Я на вокза'ле.]]"],
        ["[[куда'?]]", "where to", "в / на + accusative", "[[Я е'ду в Москву'. / Я иду' на вокза'л.]]"],
        ["[[отку'да?]]", "where from", "из (for в) · с (for на) + genitive", "[[Я из Москвы'. / Я с вокза'ла.]]"],
        ["[[у кого'?]]", "at someone's", "у + genitive", "[[Я у врача'.]]"],
        ["[[к кому'?]]", "to someone's", "к + dative", "[[Я иду' к врачу'.]]"],
        ["[[от кого'?]]", "from someone's", "от + genitive", "[[Я иду' от врача'.]]"],
    ],
    "rule": [
        "**Pairs that go together:** в → в → из; на → на → с. If you say [[в Москве']] and [[в Москву']], you leave with [[из Москвы']]. If you say [[на вокза'ле]] and [[на вокза'л]], you leave with [[с вокза'ла]].",
        "**For people, use к / у / от**, never в: [[к врачу']], [[у врача']], [[от врача']].",
    ],
    "v_na": {
        "head": ["В (inside, enclosed, countries and cities)", "На (open spaces, surfaces, events, institutions-as-activity)"],
        "rows": [
            ["[[в гости'нице]] hotel", "[[на вокза'ле]] station"],
            ["[[в магази'не]] shop", "[[на по'чте]] post office"],
            ["[[в апте'ке]] pharmacy", "[[на рабо'те]] at work"],
            ["[[в рестора'не]] restaurant", "[[на ста'нции]] station (metro/train)"],
            ["[[в метро']] in the metro", "[[на остано'вке]] bus stop"],
            ["[[в аэропорту']] airport", "[[на у'лице]] street · [[на пло'щади]] square"],
            ["[[в теа'тре]] · [[в музе'е]]", "[[на ры'нке]] market · [[на конце'рте]] concert"],
            ["[[в го'роде]] · [[в стране']]", "[[на ку'хне]] kitchen · [[на ю'ге]] south"],
        ],
        "note": "There is no deep logic: learn the common «на» places as chunks. Transport: [[на метро']] / [[на авто'бусе]] means «by» it; [[в метро']] means «inside».",
    },
}

# --------------------------------------------------------------------------------------------
# Preposition lookup (anchors are stable ids)
# --------------------------------------------------------------------------------------------

PREPOSITIONS = [
    # (id, prep, cases, meaning, example ru, example en)
    ("prep-v", "в", "Acc. · Prep.", "into (куда'?) · in (где?)", "в Москву' · в Москве'", "to Moscow · in Moscow"),
    ("prep-na", "на", "Acc. · Prep.", "onto/to (куда'?) · on/at (где?)", "на вокза'л · на вокза'ле", "to the station · at the station"),
    ("prep-iz", "из", "Gen.", "out of, from", "из Москвы'", "from Moscow"),
    ("prep-s-gen", "с", "Gen.", "off, from (opposite of на)", "с вокза'ла", "from the station"),
    ("prep-s-instr", "с", "Instr.", "with", "с молоко'м", "with milk"),
    ("prep-ot", "от", "Gen.", "from (a person/thing), away from", "от гости'ницы", "from the hotel"),
    ("prep-do", "до", "Gen.", "until, as far as", "до метро'", "as far as the metro"),
    ("prep-u", "у", "Gen.", "at, by; owner", "у меня' есть", "I have"),
    ("prep-bez", "без", "Gen.", "without", "без са'хара", "without sugar"),
    ("prep-dlya", "для", "Gen.", "for", "для вас", "for you"),
    ("prep-okolo", "о'коло", "Gen.", "near; about", "о'коло вокза'ла", "near the station"),
    ("prep-posle", "по'сле", "Gen.", "after", "по'сле у'жина", "after dinner"),
    ("prep-mimo", "ми'мо", "Gen.", "past", "ми'мо апте'ки", "past the pharmacy"),
    ("prep-k", "к", "Dat.", "to, toward (a person/place)", "к врачу'", "to the doctor"),
    ("prep-po", "по", "Dat.", "along; by; according to", "по у'лице", "along the street"),
    ("prep-za-acc", "за", "Acc.", "for, in exchange; behind (куда'?)", "спаси'бо за по'мощь", "thanks for the help"),
    ("prep-za-instr", "за", "Instr.", "behind (где?)", "за угло'м", "round the corner"),
    ("prep-cherez", "че'рез", "Acc.", "through; in (a time)", "че'рез час", "in an hour"),
    ("prep-pod", "под", "Acc. · Instr.", "under (куда'? · где?)", "под стол · под столо'м", "under the table"),
    ("prep-pered", "пе'ред", "Instr.", "in front of; before", "пе'ред теа'тром", "in front of the theater"),
    ("prep-nad", "над", "Instr.", "above", "над вхо'дом", "above the entrance"),
    ("prep-mezhdu", "ме'жду", "Instr.", "between", "ме'жду ба'нком и магази'ном", "between the bank and the shop"),
    ("prep-o", "о / об / обо", "Prep.", "about", "о Москве'", "about Moscow"),
]

SPELLING_RULES = [
    ("7-letter rule", "After **г к х ж ч ш щ** write **и**, never ы.",
     "[[кни'га → кни'ги]] (not кни'гы) · [[ру'чка → ру'чки]] · [[хоро'шие]] (not хоро'шые) · [[больши'е]]"),
    ("Vowel after ж ч ш щ", "After **ж ч ш щ** write **а** and **у**, never я and ю.",
     "[[врач → врачу']] (not врачю') · [[хочу']] · [[пишу']]"),
    ("5-letter rule (unstressed о)", "After **ж ч ш щ ц**, an **unstressed о** is written **е**. A stressed ending keeps о.",
     "[[това'рищ → с това'рищем]] · [[у'лица → у'лицей]] · [[хоро'шее]] · but stressed: [[с врачо'м]], [[с отцо'м]]"),
]

# --------------------------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------------------------

NUMBERS_RULE = {
    "head": ["Number ends in", "Noun form", "Examples"],
    "rows": [
        ["**1** (also 21, 31, 101; not 11)", "nominative **singular**",
         "[[оди'н рубль]] · [[два'дцать оди'н рубль]] · [[сто оди'н рубль]]"],
        ["**2, 3, 4** (also 22, 33, 104; not 12-14)", "genitive **singular**",
         "[[два рубля']] · [[три биле'та]] · [[четы'ре часа']] · [[два'дцать два рубля']]"],
        ["**5-20** (also 25, 30, 100, **11-14**)", "genitive **plural**",
         "[[пять рубле'й]] · [[оди'ннадцать часо'в]] · [[два'дцать пять рубле'й]] · [[сто рубле'й]]"],
    ],
    "notes": [
        "**The last word of the number decides**: [[два'дцать оди'н]] behaves like 1, [[два'дцать два]] like 2, [[два'дцать пять]] like 5. The exception: 11-14 always take the genitive plural, so [[сто оди'ннадцать рубле'й]].",
        "**Adjectives** after 2-4: genitive plural for masculine and neuter ([[два но'вых биле'та]]); feminine nouns allow nominative or genitive plural ([[две но'вые ко'мнаты]]).",
        "**Questions and quantity words**: [[ско'лько]] / [[мно'го]] / [[ма'ло]] / [[не'сколько]] + genitive plural for countable things ([[мно'го люде'й]]), genitive singular for mass nouns ([[мно'го воды']]).",
    ],
}

NUMBER_GENDER = {
    "head": ["", "Masculine", "Feminine", "Neuter", "Plural"],
    "rows": [
        ["1", "[[оди'н биле'т]]", "[[одна' ночь]]", "[[одно' ме'сто]]", "[[одни' су'тки]] (pl. only nouns)"],
        ["2", "[[два биле'та]]", "[[две но'чи]]", "[[два ме'ста]]", ""],
        ["3, 4", "[[три / четы'ре биле'та]]", "[[три / четы'ре но'чи]]", "[[три / четы'ре ме'ста]]", ""],
    ],
    "note": "Only **один** and **два** change by gender. 21 and 22 follow: [[два'дцать одна' ночь]], [[два'дцать две но'чи]].",
}

NUMBER_NOUNS = {
    "head": ["Noun", "1", "2-4", "5-20", "Context"],
    "rows": [
        ["[[рубль]]", "[[рубль]]", "[[рубля']]", "[[рубле'й]]", "prices"],
        ["[[копе'йка]]", "[[копе'йка]]", "[[копе'йки]]", "[[копе'ек]]", "change"],
        ["[[час]]", "[[час]]", "[[часа']]", "[[часо'в]]", "time, duration"],
        ["[[мину'та]]", "[[мину'та]]", "[[мину'ты]]", "[[мину'т]]", "time, travel"],
        ["[[день]]", "[[день]]", "[[дня]]", "[[дней]]", "days"],
        ["[[неде'ля]]", "[[неде'ля]]", "[[неде'ли]]", "[[неде'ль]]", "weeks"],
        ["[[год]]", "[[год]]", "[[го'да]]", "[[лет]]", "years, age"],
        ["[[челове'к]]", "[[челове'к]]", "[[челове'ка]]", "[[челове'к]]", "people"],
        ["[[биле'т]]", "[[биле'т]]", "[[биле'та]]", "[[биле'тов]]", "tickets"],
    ],
}

NUMBER_EXAMPLES = {
    "money": {
        "id": "numbers-money", "title": "Prices and money", "ru": "Це'ны",
        "intro": "[[Ско'лько сто'ит?]] takes a nominative number, and the unit follows the rule. Remember [[рубль]] is stressed on the stem in the nominative singular and on the ending elsewhere.",
        "examples": [
            ("Оди'н биле'т сто'ит со'рок оди'н рубль.", "One ticket costs 41 roubles."),
            ("Два биле'та, пожа'луйста.", "Two tickets, please."),
            ("Э'то сто'ит три'ста пятьдеся'т рубле'й.", "This costs 350 roubles."),
            ("У меня' нет пяти' рубле'й.", "I do not have five roubles. (Numbers are declined after нет: пяти' is genitive.)"),
        ],
    },
    "time": {
        "id": "numbers-time", "title": "Time and duration", "ru": "Вре'мя",
        "intro": "Clock times use [[час]] with the same rule. [[в три часа']] = at three o'clock; [[в пять часо'в]] = at five.",
        "examples": [
            ("Сейча'с пять часо'в.", "It is five o'clock."),
            ("По'езд отхо'дит в три часа'.", "The train leaves at three."),
            ("До вокза'ла де'сять мину'т.", "It is ten minutes to the station."),
            ("Мы в Москве' на две неде'ли.", "We are in Moscow for two weeks."),
            ("Я бу'ду здесь пять дней.", "I will be here for five days."),
        ],
    },
    "years": {
        "id": "numbers-years", "title": "Age and years", "ru": "Во'зраст",
        "intro": "Age uses the dative for the person and the 1 / 2-4 / 5+ rule for [[год]]: 1 [[год]], 2-4 [[го'да]], 5-20 [[лет]]; 21 [[год]], 22 [[го'да]], 25 [[лет]].",
        "examples": [
            ("Мне три'дцать оди'н год.", "I am 31."),
            ("Ей два'дцать два го'да.", "She is 22."),
            ("Ско'лько вам лет?", "How old are you?"),
            ("Мы здесь пять лет.", "We have been here five years."),
        ],
    },
}

NUMBER_WORDS = [
    ("1", "оди'н / одна' / одно'"), ("2", "два / две"), ("3", "три"), ("4", "четы'ре"), ("5", "пять"),
    ("6", "шесть"), ("7", "семь"), ("8", "во'семь"), ("9", "де'вять"), ("10", "де'сять"),
    ("11", "оди'ннадцать"), ("12", "двена'дцать"), ("13", "трина'дцать"), ("14", "четы'рнадцать"),
    ("15", "пятна'дцать"), ("16", "шестна'дцать"), ("17", "семна'дцать"), ("18", "восемна'дцать"),
    ("19", "девятна'дцать"), ("20", "два'дцать"), ("30", "три'дцать"), ("40", "со'рок"),
    ("50", "пятьдеся'т"), ("60", "шестьдеся'т"), ("70", "се'мьдесят"), ("80", "во'семьдесят"),
    ("90", "девяно'сто"), ("100", "сто"), ("200", "две'сти"), ("300", "три'ста"),
    ("400", "четы'реста"), ("500", "пятьсо'т"), ("1000", "ты'сяча"),
]

# --------------------------------------------------------------------------------------------
# Verbs of motion
# --------------------------------------------------------------------------------------------

MOTION_PAIRS = [
    # uni, multi, meaning, perfective of uni, 1sg / 3sg / past m of uni, 1sg / 3sg of multi
    {"uni": "идти'", "multi": "ходи'ть", "en": "go on foot", "pf": "пойти'",
     "uni_f": "иду' · идёт · шёл", "multi_f": "хожу' · хо'дит"},
    {"uni": "е'хать", "multi": "е'здить", "en": "go by vehicle", "pf": "пое'хать",
     "uni_f": "е'ду · е'дет · е'хал", "multi_f": "е'зжу · е'здит"},
    {"uni": "лете'ть", "multi": "лета'ть", "en": "fly", "pf": "полете'ть",
     "uni_f": "лечу' · лети'т · лете'л", "multi_f": "лета'ю · лета'ет"},
    {"uni": "бежа'ть", "multi": "бе'гать", "en": "run", "pf": "побежа'ть",
     "uni_f": "бегу' · бежи'т · бежа'л", "multi_f": "бе'гаю · бе'гает"},
    {"uni": "плыть", "multi": "пла'вать", "en": "swim, sail", "pf": "поплы'ть",
     "uni_f": "плыву' · плывёт · плы'л", "multi_f": "пла'ваю · пла'вает"},
    {"uni": "нести'", "multi": "носи'ть", "en": "carry (on foot); wear", "pf": "понести'",
     "uni_f": "несу' · несёт · нёс", "multi_f": "ношу' · но'сит"},
    {"uni": "вести'", "multi": "води'ть", "en": "lead, take (on foot); drive", "pf": "повести'",
     "uni_f": "веду' · ведёт · вёл", "multi_f": "вожу' · во'дит"},
    {"uni": "везти'", "multi": "вози'ть", "en": "transport (by vehicle)", "pf": "повезти'",
     "uni_f": "везу' · везёт · вёз", "multi_f": "вожу' · во'зит"},
]

# Full conjugations of the four core verbs (Wiktionary).
MOTION_CONJ = {
    "head": ["", "идти'", "ходи'ть", "е'хать", "е'здить"],
    "rows": [
        ["я", "иду'", "хожу'", "е'ду", "е'зжу"],
        ["ты", "идёшь", "хо'дишь", "е'дешь", "е'здишь"],
        ["он / она'", "идёт", "хо'дит", "е'дет", "е'здит"],
        ["мы", "идём", "хо'дим", "е'дем", "е'здим"],
        ["вы", "идёте", "хо'дите", "е'дете", "е'здите"],
        ["они'", "иду'т", "хо'дят", "е'дут", "е'здят"],
        ["прошедшее м.", "шёл", "ходи'л", "е'хал", "е'здил"],
        ["ж.", "шла'", "ходи'ла", "е'хала", "е'здила"],
        ["ср.", "шло'", "ходи'ло", "е'хало", "е'здило"],
        ["мн.", "шли", "ходи'ли", "е'хали", "е'здили"],
        ["императив", "иди' · иди'те", "ходи'(те)", "поезжа'й(те)", "е'зди(те)"],
    ],
}

MOTION_USE = {
    "head": ["Unidirectional (идти', е'хать...)", "Multidirectional (ходи'ть, е'здить...)"],
    "rows": [
        ["**One direction, right now**: [[Я иду' в магази'н.]]", "**Habit, repetition**: [[Я хожу' в магази'н ка'ждый день.]]"],
        ["**A single trip in progress**: [[Мы е'дем в Москву'.]]", "**General ability or fact**: [[Он уже' хо'дит.]] (He can already walk.)"],
        ["**Future: one planned trip** uses the perfective [[пое'хать]]: [[За'втра мы пое'дем в Москву'.]]", "**Round trip, past tense**: [[Вчера' я ходи'л в музе'й.]] (I went and came back.)"],
        ["**Past: set off / were en route**: [[Он пошёл в магази'н.]] (He has gone and is not back yet.)", "**Experience («have you ever...»)**: [[Вы е'здили в Москву'?]] (Have you been to Moscow?)"],
    ],
}

MOTION_PREFIXES = {
    "head": ["Prefix", "Meaning", "Perfective (prefix + uni)", "Imperfective (prefix + multi)", "Example"],
    "rows": [
        ["**по-**", "set off; start", "[[пойти']] · [[пое'хать]] · [[полете'ть]]", "(none: по- + multi = a short while, [[походи'ть]])", "[[Мы пое'дем в Москву'.]]"],
        ["**при-**", "arrive", "[[прийти']] · [[прие'хать]] · [[прилете'ть]]", "[[приходи'ть]] · [[приезжа'ть]] · [[прилета'ть]]", "[[Мы прилета'ем в пять часо'в.]]"],
        ["**у-**", "leave, go away", "[[уйти']] · [[уе'хать]] · [[улете'ть]]", "[[уходи'ть]] · [[уезжа'ть]] · [[улета'ть]]", "[[По'езд уезжа'ет в шесть.]]"],
        ["**в- / во-**", "go in, enter", "[[войти']] · [[въе'хать]]", "[[входи'ть]] · [[въезжа'ть]]", "[[Входи'те!]] (Come in!)"],
        ["**вы-**", "go out, exit", "[[вы'йти]] · [[вы'ехать]] (stress on prefix)", "[[выходи'ть]] · [[выезжа'ть]]", "[[Вы выхо'дите на сле'дующей?]]"],
        ["**пере-**", "cross; change (transport)", "[[перейти']] · [[перее'хать]]", "[[переходи'ть]] · [[переезжа'ть]]", "[[Перейди'те у'лицу.]]"],
        ["**за-**", "drop in; stop by; go behind", "[[зайти']] · [[зае'хать]]", "[[заходи'ть]] · [[заезжа'ть]]", "[[Я зайду' в апте'ку.]]"],
        ["**до-**", "as far as", "[[дойти']] · [[дое'хать]]", "[[доходи'ть]] · [[доезжа'ть]]", "[[Как дое'хать до Кремля'?]]"],
        ["**про-**", "go past or through; cover a distance", "[[пройти']] · [[прое'хать]]", "[[проходи'ть]] · [[проезжа'ть]]", "[[Как пройти' к метро'?]]"],
        ["**под-**", "approach", "[[подойти']] · [[подъе'хать]]", "[[подходи'ть]] · [[подъезжа'ть]]", "[[Подойди'те к ка'ссе.]]"],
        ["**от-**", "move away from", "[[отойти']] · [[отъе'хать]]", "[[отходи'ть]] · [[отъезжа'ть]]", "[[По'езд отхо'дит.]]"],
        ["**об-**", "go round", "[[обойти']] · [[объе'хать]]", "[[обходи'ть]] · [[объезжа'ть]]", "[[Обойди'те зда'ние.]]"],
        ["**с-**", "go and come back (colloquial); go down/get off", "[[сходи'ть]] (there and back) · [[сойти']] (get off)", "[[сходи'ть]] (get off, step down)", "[[Я схожу' в магази'н.]]"],
    ],
}

MOTION_CORE = [
    ("идти' / ходи'ть", "go on foot", "Я иду' домо'й.", "I am walking home."),
    ("е'хать / е'здить", "go by vehicle", "Мы е'дем на метро'.", "We are going by metro."),
    ("пойти' / пое'хать", "set off", "Мы пое'дем в Москву' в сентябре'.", "We will go to Moscow in September."),
    ("прийти' / прие'хать", "arrive", "Мы прие'хали вчера'.", "We arrived yesterday."),
    ("вы'йти", "get out, leave a building", "Вы выхо'дите?", "Are you getting off?"),
    ("перейти'", "cross, change lines", "Как перейти' на другу'ю ли'нию?", "How do I change to another line?"),
    ("дое'хать", "get to, as far as", "Как дое'хать до Кра'сной пло'щади?", "How do I get to Red Square?"),
    ("зайти'", "pop in", "Я зайду' в апте'ку.", "I will pop into the pharmacy."),
]

# --------------------------------------------------------------------------------------------
# Aspect
# --------------------------------------------------------------------------------------------

ASPECT_CHOOSE = {
    "head": ["Use the PERFECTIVE for...", "Use the IMPERFECTIVE for..."],
    "rows": [
        ["**One completed action with a result**: [[Я купи'л биле'т.]] (I have the ticket.)", "**The process, or no result implied**: [[Я покупа'л биле'т це'лый час.]] (I was buying a ticket for an hour.)"],
        ["**A sequence of events**: [[Я купи'л биле'т и вошёл в метро'.]]", "**Repetition and habit**: [[Я ка'ждый день покупа'ю биле'т.]]"],
        ["**A specific, single request**: [[Скажи'те, пожа'луйста, где касса?]]", "**«Did it ever happen?» (a fact)**: [[Вы покупа'ли биле'ты?]]"],
        ["**Future with a definite result**: [[За'втра я куплю' биле'т.]]", "**Duration, ongoing**: [[Я чита'л весь ве'чер.]]"],
        ["**Future, completed: no «будет»**: [[Я напишу'.]]", "**Future, process: with «бу'ду»**: [[Я бу'ду писа'ть.]]"],
    ],
    "extra": [
        "After **начина'ть, продолжа'ть, конча'ть, переста'ть** use the imperfective infinitive: [[Он на'чал чита'ть.]]",
        "**Present tense is always imperfective.** A perfective verb conjugated in the present form has future meaning: [[куплю']] = I will buy.",
    ],
}

ASPECT_NEGATION = {
    "id": "aspect-negation", "title": "Negation and «не на'до»", "ru": "Отрица'ние",
    "intro": "Negated suggestions and prohibitions take the **imperfective**. A negated perfective means «did not manage to» or «will not do it once»: it is rarer.",
    "rows": [
        ["[[Не на'до покупа'ть э'то.]]", "No need to buy this.", "imperfective"],
        ["[[Не ну'жно открыва'ть окно'.]]", "There is no need to open the window.", "imperfective"],
        ["[[Нельзя' открыва'ть окно'.]]", "You must not open the window.", "imperfective = forbidden"],
        ["[[Нельзя' откры'ть окно'.]]", "It is impossible to open the window.", "perfective = cannot"],
        ["[[Я не купи'л биле'т.]]", "I did not buy a ticket (the result is missing).", "perfective"],
    ],
}

ASPECT_COMMANDS = {
    "id": "aspect-commands", "title": "Commands and requests", "ru": "Императи'в",
    "intro": "A general invitation or a repeated instruction is imperfective; a specific request for one result is perfective. The imperfective is warmer when you invite someone in; the perfective is natural when you ask for a thing.",
    "rows": [
        ["[[Сади'тесь!]] / [[Проходи'те!]]", "Sit down! / Come in!", "inviting: imperfective"],
        ["[[Не открыва'йте окно'!]]", "Do not open the window!", "negative command: imperfective"],
        ["[[Откро'йте окно', пожа'луйста.]]", "Open the window, please.", "one specific result: perfective"],
        ["[[Скажи'те, пожа'луйста, где метро'?]]", "Tell me, please, where the metro is.", "perfective"],
        ["[[Дай мне, пожа'луйста, ключ.]]", "Give me the key, please.", "perfective"],
    ],
}

ASPECT_PAIRS = [
    ("де'лать", "сде'лать", "do, make"),
    ("чита'ть", "прочита'ть", "read"),
    ("писа'ть", "написа'ть", "write"),
    ("покупа'ть", "купи'ть", "buy"),
    ("брать", "взять", "take"),
    ("говори'ть", "сказа'ть", "say, tell"),
    ("спра'шивать", "спроси'ть", "ask"),
    ("отвеча'ть", "отве'тить", "answer"),
    ("звони'ть", "позвони'ть", "call"),
    ("ждать", "подожда'ть", "wait"),
    ("помога'ть", "помо'чь", "help"),
    ("открыва'ть", "откры'ть", "open"),
    ("закрыва'ть", "закры'ть", "close"),
    ("начина'ть", "нача'ть", "begin"),
    ("зака'зывать", "заказа'ть", "order"),
    ("плати'ть", "заплати'ть", "pay"),
    ("смотре'ть", "посмотре'ть", "look, watch"),
    ("встреча'ть", "встре'тить", "meet"),
    ("находи'ть", "найти'", "find"),
    ("дава'ть", "дать", "give"),
    ("забыва'ть", "забы'ть", "forget"),
    ("понима'ть", "поня'ть", "understand"),
    ("входи'ть", "войти'", "enter"),
    ("выходи'ть", "вы'йти", "exit"),
]

ASPECT_FORMATION = {
    "head": ["How the pair is formed", "Imperfective", "Perfective"],
    "rows": [
        ["**Prefix on the imperfective** (most common)", "[[чита'ть]] · [[писа'ть]] · [[де'лать]] · [[звони'ть]] · [[плати'ть]]", "[[прочита'ть]] · [[написа'ть]] · [[сде'лать]] · [[позвони'ть]] · [[заплати'ть]]"],
        ["**Suffix on the perfective** (-а-, -ыва-/-ива-, -ва-)", "[[покупа'ть]] · [[открыва'ть]] · [[забыва'ть]]", "[[купи'ть]] · [[откры'ть]] · [[забы'ть]]"],
        ["**Consonant change** (-ить → -ать)", "[[отвеча'ть]] · [[встреча'ть]]", "[[отве'тить]] · [[встре'тить]]"],
        ["**Different words**", "[[говори'ть]] · [[брать]] · [[класть]]", "[[сказа'ть]] · [[взять]] · [[положи'ть]]"],
    ],
    "note": "Learn each verb as a pair, imperfective first. The perfective has no present tense: its conjugated forms mean the future ([[куплю', ку'пишь]]).",
}

# --------------------------------------------------------------------------------------------
# Stress
# --------------------------------------------------------------------------------------------

STRESS_PATTERNS = [
    {"id": "stress-yo", "title": "ё is always stressed; unstressed vowels shrink", "body": [
        "**ё** is always stressed, so it never gets an accent mark. Everyday texts print it as plain е, so a е that you hear as ё is one more thing to remember: [[мёд]], [[всё]], [[идёшь]], [[её]].",
        "In unstressed syllables **о sounds like а** and **е like и**: [[Москва']] is pronounced «maskvá». Wrong stress makes a word hard to recognize, which is why every example here carries the mark.",
    ]},
    {"id": "stress-fixed", "title": "Fixed stress (most words)", "body": [
        "Most nouns keep stress on the same syllable in every form: [[кни'га, кни'ги, кни'гу, кни'гой, о кни'ге]]; [[биле'т, биле'та, биле'ты]]; [[Москва', Москвы', в Москве', в Москву']]."]},
    {"id": "stress-mobile", "title": "Mobile stress: the common patterns", "table": {
        "id": "stress-mobile-table", "caption": "Mobile-stress nouns",
        "head": ["Pattern", "What moves", "Examples"],
        "rows": [
            ["Stem in singular, ending in plural", "[[го'род → города']], [[дом → дома']], [[паспорт → паспорта']], [[но'мер → номера']]", "Learn the plural nominative; the rest follows the ending."],
            ["Ending in singular, stem in plural (neuter)", "[[окно' → о'кна]], [[число' → чи'сла]], [[лицо' → ли'ца]], [[письмо' → пи'сьма]]", "The genitive plural also moves: [[о'кон]], [[пи'сем]]."],
            ["Feminine: accusative singular and plural take the stem", "[[рука' → ру'ку, ру'ки]], [[нога' → но'гу, но'ги]], [[голова' → го'лову]], [[вода' → во'ду]], [[стена' → сте'ну]]", "Other forms stay on the ending: [[руки', руке', руко'й]]."],
            ["Ending in all forms", "[[стол → стола', столу', столо'м]], [[рубль → рубля', рублю']], [[Москва' → Москву']]", "Monosyllables in the nominative are often this type."],
        ],
    }},
    {"id": "stress-past", "title": "Past tense: the feminine goes to the ending", "table": {
        "id": "stress-past-table", "caption": "Common verbs whose feminine moves",
        "head": ["Infinitive", "Masc.", "Fem.", "Neut.", "Plural"],
        "rows": [
            ["[[быть]]", "[[был]]", "[[была']]", "[[бы'ло]]", "[[бы'ли]]"],
            ["[[жить]]", "[[жил]]", "[[жила']]", "[[жи'ло]]", "[[жи'ли]]"],
            ["[[пить]]", "[[пил]]", "[[пила']]", "[[пи'ло]]", "[[пи'ли]]"],
            ["[[дать]]", "[[дал]]", "[[дала']]", "[[да'ло]]", "[[да'ли]]"],
            ["[[взять]]", "[[взял]]", "[[взяла']]", "[[взя'ло]]", "[[взя'ли]]"],
            ["[[нача'ть]]", "[[на'чал]]", "[[начала']]", "[[на'чало]]", "[[на'чали]]"],
        ],
    }, "after": ["The same shift is a way to remember: [[Она' была' в Москве'.]] against [[Он был в Москве'.]]"]},
    {"id": "stress-verbs", "title": "Present tense: end-stressed first person", "body": [
        "A big group of verbs stress the ending in the first person and the stem in all other forms: [[хожу', хо'дишь, хо'дят]], [[люблю', лю'бишь, лю'бят]], [[плачу', пла'тишь, пла'тят]], [[смотрю', смо'тришь]].",
        "Compare with [[говорю', говори'шь, говоря'т]], where the ending is stressed throughout.",
    ]},
    {"id": "stress-pairs", "title": "Stress changes the word", "table": {
        "id": "stress-pairs-table", "caption": "Pairs that differ only in stress",
        "head": ["Stress here", "Stress there"],
        "rows": [
            ["[[за'мок]] castle", "[[замо'к]] lock"],
            ["[[му'ка]] torment", "[[мука']] flour"],
            ["[[пла'чу]] I cry", "[[плачу']] I pay"],
            ["[[а'тлас]] atlas (maps)", "[[атла'с]] satin"],
        ],
    }},
]

STRESS_LOOKUP = [
    ("OpenRussian", "https://en.openrussian.org/", "Dictionary with stress marks, full declension and conjugation tables, audio, and example sentences."),
    ("English Wiktionary", "https://en.wiktionary.org/", "Declension and conjugation tables with stress and the pattern letter for every Russian word."),
    ("Forvo", "https://forvo.com/languages/ru/", "Recordings of Russian words by native speakers: hear the stress, not just read it."),
    ("Gramota.ru", "https://gramota.ru/", "The official Russian reference dictionary portal (in Russian)."),
    ("stress-russian-books", "https://github.com/FreeLanguageTools/stress-russian-books", "A tool that adds stress marks to e-book text."),
]

# --------------------------------------------------------------------------------------------
# Pitfalls
# --------------------------------------------------------------------------------------------

PITFALLS = [
    {"id": "pitfall-u-menya", "title": "Having something: у меня' есть", "ru": "У меня' есть...",
     "why": "Russian has no verb «to have» for owning things. The owner goes in the genitive after [[у]], and the thing is the grammatical subject.",
     "wrong": "Я име'ю биле'т.", "right": "У меня' есть биле'т.",
     "note": "Past: [[У меня' был биле'т]] (agrees with the thing). Absence: [[У меня' нет биле'та]]. Leave out [[есть]] when the point is a quality: [[У меня' больша'я семья'.]]"},
    {"id": "pitfall-svoy", "title": "свой and мой / его' / её", "ru": "свой",
     "why": "[[свой]] refers back to the subject of the clause (his own, her own). [[его']] and [[её]] mean someone else's.",
     "wrong": "Она' лю'бит её ма'му.", "right": "Она' лю'бит свою' ма'му.",
     "note": "The first sentence means she loves somebody else's mother; the second, her own. [[Я люблю' мою' ма'му]] and [[Я люблю' свою' ма'му]] are both fine in the first and second person, but in the third person the difference matters. [[свой]] is never the subject itself."},
    {"id": "pitfall-know-can", "title": "знать · уметь · мочь", "ru": "знать / уметь / мочь",
     "why": "English «know» and «can» each split into several Russian verbs.",
     "wrong": "Я зна'ю пла'вать.", "right": "Я уме'ю пла'вать.",
     "note": "[[знать]] = know a fact or a person (+ что, где, кого): [[Я не зна'ю, где метро'.]] [[уме'ть]] = know how, a learned skill. [[мочь]] = be able or allowed, circumstances: [[Я могу' прийти' в пять.]] [[Вы мо'жете мне помо'чь?]]"},
    {"id": "pitfall-v-na", "title": "в or на with places", "ru": "в / на",
     "why": "English «in/at» does not tell you which one. Learn the common «на» places as chunks.",
     "wrong": "Я в по'чте. / Я в вокза'ле. / Я в рабо'те.", "right": "Я на по'чте. / Я на вокза'ле. / Я на рабо'те.",
     "note": "Also «на»: [[на у'лице]], [[на остано'вке]], [[на ста'нции]], [[на ры'нке]], [[на пло'щади]], [[на конце'рте]]. «В»: [[в гости'нице]], [[в магази'не]], [[в апте'ке]], [[в аэропорту']], [[в метро']]. See the table in Cases."},
    {"id": "pitfall-ty-vy", "title": "ты or вы", "ru": "ты / вы",
     "why": "[[вы]] is plural and also the polite singular. [[ты]] is for friends, family, children, and people your own age who invite it.",
     "wrong": "Ты не могла' бы мне помо'чь?", "right": "Вы не могли' бы мне помо'чь?",
     "note": "Imagine asking a waiter. With waiters, shop assistants, staff, officials and strangers, use [[вы]]. Verbs agree in the plural even for one person: [[Вы говори'те по-англи'йски?]] A person who says [[Дава'йте на «ты»]] is inviting you to switch."},
    {"id": "pitfall-numerals-negation", "title": "Numbers and negation take genitive", "ru": "нет + родительный",
     "why": "The nominative looks like the dictionary form, but after [[нет]] and after 2+ the noun changes.",
     "wrong": "У меня' нет биле'т. / два рубль.", "right": "У меня' нет биле'та. / два рубля'.",
     "note": "See the [Numbers](/grammar/numbers) page."},
    {"id": "pitfall-animate", "title": "Animate accusative", "ru": "Я ви'жу бра'та",
     "why": "Masculine people and animals add -а/-я in the accusative.",
     "wrong": "Я ви'жу брат.", "right": "Я ви'жу бра'та.",
     "note": "Applies to all animate plurals too: [[Я ви'жу студе'нтов.]] See [Animate accusative](/grammar/cases#animate-accusative)."},
    {"id": "pitfall-nravitsya", "title": "Liking and needing: the dative", "ru": "Мне нра'вится",
     "why": "The person who likes or needs is in the dative; the thing liked is the subject.",
     "wrong": "Я нра'вится Москва'. / Я 25 лет.", "right": "Мне нра'вится Москва'. / Мне 25 лет.",
     "note": "The verb agrees with the thing: [[Мне нра'вятся музе'и.]] (I like museums)."},
    {"id": "pitfall-no-byt", "title": "No «is» in the present", "ru": "Он врач",
     "why": "[[быть]] drops out in the present tense.",
     "wrong": "Я есть студе'нт.", "right": "Я студе'нт.",
     "note": "[[есть]] only appears in «have» sentences ([[у меня' есть]]) and in a few stock phrases."},
    {"id": "pitfall-pronouns", "title": "Too many pronouns", "ru": "Лишние местоимения",
     "why": "The verb ending already shows the person, so drop the pronoun unless you need emphasis.",
     "wrong": "Я иду' в магази'н, а я пото'м я куплю' ко'фе.", "right": "Иду' в магази'н, пото'м куплю' ко'фе.",
     "note": "Keep [[я]] and [[ты]] for contrast, or at the start of a conversation."},
]

# --------------------------------------------------------------------------------------------
# Finish: convert stress markers once.
# --------------------------------------------------------------------------------------------

for _name in ("SECTIONS", "HIGH_YIELD", "PARADIGMS", "ADJECTIVES", "PRONOUNS", "PRON_AFTER", "POSSESSIVES",
              "CASES", "LOCATION_DIRECTION", "PREPOSITIONS", "SPELLING_RULES", "NUMBERS_RULE", "NUMBER_GENDER",
              "NUMBER_NOUNS", "NUMBER_EXAMPLES", "NUMBER_WORDS", "MOTION_PAIRS", "MOTION_CONJ", "MOTION_USE",
              "MOTION_PREFIXES", "MOTION_CORE", "ASPECT_CHOOSE", "ASPECT_NEGATION", "ASPECT_COMMANDS",
              "ASPECT_PAIRS", "ASPECT_FORMATION", "STRESS_PATTERNS", "STRESS_LOOKUP", "PITFALLS"):
    globals()[_name] = _finish(globals()[_name])
del _name

CASE_BY_ID = {c["id"]: c for c in CASES}


# --------------------------------------------------------------------------------------------
# Living case table and word-change morph (rendered by templates/grammar/cases.html, animated by
# static/grammar.js). Added after the stress conversion above, so stress() is applied here.
# --------------------------------------------------------------------------------------------

# Chip label and the one-line purpose shown under the living table (order N G D A I P).
CASE_BRIEF = {
    "nominative": {"ab": "Nom", "q": "кто? что?", "use": "Who or what does it: the subject, and the dictionary form."},
    "genitive": {"ab": "Gen", "q": "кого? чего?", "use": "Of, none of, quantities, and after из, до, у, без."},
    "dative": {"ab": "Dat", "q": "кому? чему?", "use": "To or for someone: the receiver. Also after к and по."},
    "accusative": {"ab": "Acc", "q": "кого? что?", "use": "The direct object; also direction after в and на (into, onto)."},
    "instrumental": {"ab": "Ins", "q": "кем? чем?", "use": "With, by means of; also after с, над, перед, за."},
    "prepositional": {"ab": "Prep", "q": "о ком? о чём?", "use": "About, in, on: only ever after a preposition, mostly в, на, о, при."},
}
# Paradigm keys (see PARADIGMS) shown as the columns of the living table.
LIVING_NOUNS = ["m-hard", "f-velar", "n-hard"]


def _morph_text(f: dict) -> str:
    """Display form with the stress mark: 'окно́'. st indexes the letters of stem + ending."""
    hid = f.get("hid")
    vis = "".join(ch for i, ch in enumerate(f["stem"]) if i != hid) + f["end"]
    if f["st"] < 0:
        return vis
    idx = f["st"] - 1 if hid is not None and f["st"] > hid else f["st"]
    return vis[: idx + 1] + ACUTE + vis[idx + 1:]


def _mf(stem, end, st, label, sn, rule, **kw):
    return {"stem": stem, "end": end, "st": st, "label": label, "sn": sn, "rule": stress(rule), **kw}


# st = index of the stressed letter counting the stem letters first, then the ending (-1: no mark,
# the word has a single syllable). hid = stem letter that is not shown yet; grow = letter that appears.
MORPH = [
    {"name": "Genitive sg and pl", "forms": [
        _mf("стол", "", -1, "Nominative sg", "none",
            "Nominative is the bare stem. A hard masculine noun ends in a consonant, so its ending is zero (∅): стол. One syllable, so no stress mark."),
        _mf("стол", "а", 4, "Genitive sg", "ending",
            "Genitive singular adds -а. The stem стол- stays put, and the stress moves onto the new ending: стола'."),
        _mf("стол", "ов", 4, "Genitive pl", "ending",
            "Genitive plural of a hard masculine noun takes -ов. Same stem, stress on the ending: столо'в."),
    ]},
    {"name": "Zero ending", "forms": [
        _mf("книг", "а", 2, "Nominative sg", "stem",
            "Nominative: the stem кни'г- plus the feminine ending -а."),
        _mf("книг", "", -1, "Genitive pl", "none",
            "Genitive plural drops -а altogether. The zero ending (∅) leaves the bare stem: книг. With one syllable left, "
            "the stress mark disappears."),
    ]},
    {"name": "Inserted vowel and stress shift", "forms": [
        _mf("окон", "о", 4, "Nominative sg", "ending",
            "Nominative: the stem окн- plus the neuter ending -о, with the stress on that ending: окно'.", hid=2),
        _mf("окон", "", 0, "Genitive pl", "stem",
            "Genitive plural drops -о, and the bare stem окн- would be a clump of consonants, so a vowel о is inserted "
            "between к and н. The stress travels from the last syllable to the first: о'кон.", grow=2),
    ]},
    {"name": "Mobile stress", "forms": [
        _mf("рук", "а", 3, "Nominative sg", "ending",
            "Nominative: the stem рук- plus -а, with the stress sitting on the ending: рука'."),
        _mf("рук", "у", 1, "Accusative sg", "stem",
            "Accusative singular: the ending changes -а to -у, and the stress jumps back onto the stem: ру'ку. "
            "Both change at once. That is mobile stress."),
    ]},
]
for _q in MORPH:
    for _f in _q["forms"]:
        _f["text"] = _morph_text(_f)
    _q["path"] = " → ".join(_f["text"] for _f in _q["forms"])
del _q, _f

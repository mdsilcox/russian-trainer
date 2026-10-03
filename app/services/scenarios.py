"""Role-play scenario library: the seed data and an idempotent loader.

Russian text below is written with an apostrophe right after the stressed vowel
(Здра'вствуйте); `_st` turns it into the combining acute (U+0301) used everywhere else.
"""

import re

from sqlmodel import Session, select

from app.models import Scenario

LEVEL_LABELS = {1: "Slow and clear", 2: "Everyday", 3: "Natural speed"}

_MARK = re.compile("([аеёиоуыэюяАЕЁИОУЫЭЮЯ])'")


def _st(text: str) -> str:
    return _MARK.sub("\\1\u0301", text)


# Cloud voice per scenario, matching the persona (Dmitry is male; Svetlana and Dariya are female).
VOICES = {
    "taxi": "Dmitry",
    "directions": "Svetlana",
    "metro": "Dariya",
    "train": "Dmitry",
    "restaurant": "Dmitry",
    "cafe": "Dariya",
    "hotel-checkin": "Svetlana",
    "hotel-problem": "Dmitry",
    "pharmacy": "Dariya",
    "market": "Dmitry",
    "souvenirs": "Svetlana",
    "small-talk": "Dariya",
    "relatives": "Svetlana",
    "lost-bag": "Dariya",
    "wrong-order": "Dmitry",
}


def _vocab(pairs: list[tuple[str, str]]) -> list[dict]:
    return [{"ru": _st(ru), "en": en} for ru, en in pairs]


def _s(slug, group, title, partner_role, setting, persona, opening, goals, vocab, level) -> dict:
    return {
        "slug": slug, "group": group, "title": title, "partner_role": partner_role, "setting": setting,
        "persona": persona, "opening_ru": _st(opening), "goals_json": goals, "vocab_json": _vocab(vocab), "level": level,
        "voice": f"ru-RU-{VOICES[slug]}Neural",
    }


SCENARIOS: list[dict] = [
    _s(
        "taxi", "Getting around", "Taxi or Yandex Go", "taxi driver",
        "You ordered a car in Yandex Go outside your hotel. The driver has arrived and checks who you are and where you are going.",
        "Dmitry, in his fifties, drives for Yandex Go. Friendly but brisk, he likes to comment on the traffic and asks where you are from. "
        "He speaks in short sentences and gets a little impatient if you hesitate for long.",
        "Здра'вствуйте! Вы заказа'ли такси'? Куда' е'дем?",
        ["Confirm that this is your car", "Tell the driver the address", "Ask how long the trip will take",
         "Ask about the price or how to pay", "Ask him to stop at the right place"],
        [("Мы заказа'ли такси'", "We ordered a taxi"), ("Нам ну'жно по э'тому а'дресу", "We need to go to this address"),
         ("Ско'лько мину'т е'хать?", "How many minutes is the ride?"), ("Останови'те здесь, пожа'луйста", "Stop here, please"),
         ("Мо'жно оплати'ть ка'ртой?", "Can I pay by card?"), ("Подожди'те нас пять мину'т", "Wait for us five minutes"),
         ("Сда'чи не на'до", "Keep the change"), ("Откро'йте, пожа'луйста, бага'жник", "Open the boot, please")],
        1,
    ),
    _s(
        "directions", "Getting around", "Asking the way", "passer-by",
        "You are lost on a street in central Moscow and need the nearest metro station. You stop a passer-by.",
        "Anna, in her thirties, is walking to a meeting and is a little rushed. She is kind and helpful but talks fast, "
        "points a lot, and gives directions using landmarks, traffic lights and left and right turns.",
        "Да, слу'шаю вас.",
        ["Politely get her attention and ask where the metro is", "Find out whether it is near or far",
         "Understand which way to go and where to turn", "Repeat the directions back to check them", "Thank her"],
        [("Извини'те, как пройти' к метро'?", "Excuse me, how do I get to the metro?"),
         ("Где здесь ближа'йшее метро'?", "Where is the nearest metro here?"), ("Э'то далеко'?", "Is it far?"),
         ("Идти' пря'мо", "Go straight on"), ("Нале'во / напра'во", "To the left / to the right"),
         ("Поверни'те нале'во на перекрёстке", "Turn left at the crossroads"),
         ("Повтори'те, пожа'луйста, ме'дленнее", "Please repeat that more slowly"), ("На светофо'ре", "At the traffic lights"),
         ("Спаси'бо большо'е!", "Thank you very much!")],
        2,
    ),
    _s(
        "metro", "Getting around", "Metro tickets and the Troika card", "ticket office clerk",
        "You are at the ticket window in a Moscow metro station. The family needs tickets, and you have heard about a card called Troika.",
        "Elena, in her forties, has worked behind the glass for years. Her answers are short and flat, she speaks quickly "
        "and a little muffled through the window, and she asks a clarifying question rather than guessing.",
        "Здра'вствуйте. Что вы хоти'те?",
        ["Say how many tickets you need for the family", "Ask what the Troika card is and what it costs",
         "Ask how to top the card up", "Ask how to get to a station", "Pay and check your change"],
        [("Мне нужны' четы'ре биле'та", "I need four tickets"), ("Что тако'е «Тро'йка»?", "What is a Troika?"),
         ("Ско'лько сто'ит ка'рта «Тро'йка»?", "How much is a Troika card?"), ("Мне ну'жно пополни'ть ка'рту", "I need to top up my card"),
         ("На ско'лько пое'здок?", "For how many trips?"), ("Как прое'хать до ста'нции «Арба'тская»?", "How do I get to Arbatskaya station?"),
         ("Где мо'жно купи'ть биле'ты?", "Where can I buy tickets?"), ("Вот ва'ша сда'ча", "Here is your change")],
        2,
    ),
    _s(
        "train", "Getting around", "Long-distance train tickets", "ticket office clerk",
        "You are at the long-distance ticket office at Leningradsky station. The family wants to go to Saint Petersburg next Saturday.",
        "Viktor, in his late fifties, is formal and patient. He speaks clearly and politely, repeats key numbers, "
        "and expects you to have your passports ready. He enjoys explaining the different train types.",
        "До'брый день. Куда' вам ну'жно?",
        ["Say where and when you want to travel", "Ask what time the train leaves and how long it takes",
         "Choose a class or compartment", "Ask the price", "Show your passports and confirm the booking"],
        [("Четы'ре биле'та до Санкт-Петербу'рга", "Four tickets to Saint Petersburg"), ("На суббо'ту", "For Saturday"),
         ("Во ско'лько отправле'ние?", "What time does it depart?"), ("Ско'лько вре'мени в пути'?", "How long is the journey?"),
         ("Есть биле'ты в купе'?", "Are there tickets in a compartment?"), ("Како'й э'то ваго'н?", "Which carriage is this?"),
         ("С како'й платфо'рмы отправля'ется по'езд?", "Which platform does the train leave from?"),
         ("Вот на'ши па'спорта", "Here are our passports")],
        2,
    ),
    _s(
        "restaurant", "Food and drink", "Dinner at a restaurant", "waiter",
        "You are at a mid-range restaurant in Moscow with your family. The waiter has just shown you to a table.",
        "Artyom, in his twenties, is quick and relaxed. He speaks fast and casually, says the names of dishes without explaining them, "
        "and is happy to recommend things if you ask.",
        "До'брый ве'чер! Проходи'те, пожа'луйста, вот ваш сто'лик. Я принесу' меню'.",
        ["Ask for the menu and a recommendation", "Order drinks", "Order a starter and a main course", "Ask about an ingredient or an allergy",
         "Ask for the bill and pay"],
        [("Мо'жно меню', пожа'луйста?", "Could we have the menu, please?"), ("Что вы посове'туете?", "What do you recommend?"),
         ("Мы бы хоте'ли заказа'ть", "We would like to order"), ("У меня' аллерги'я на оре'хи", "I am allergic to nuts"),
         ("Есть блю'да без мя'са?", "Are there dishes without meat?"), ("Принеси'те, пожа'луйста, во'ду", "Please bring some water"),
         ("Всё о'чень вку'сно", "Everything is very tasty"), ("Счёт, пожа'луйста", "The bill, please")],
        2,
    ),
    _s(
        "cafe", "Food and drink", "Breakfast at a café", "barista",
        "A small coffee shop near the hotel. You order breakfast for the family at the counter.",
        "Katya, in her early twenties, works the morning shift. She is friendly but speaks quickly and a bit quietly over the coffee machine, "
        "and she asks whether it is to eat here or to take away.",
        "Здра'вствуйте! Что бу'дете зака'зывать?",
        ["Order coffee and tea for the family", "Order something to eat", "Say whether it is to eat here or to take away", "Pay"],
        [("Капучи'но, пожа'луйста", "A cappuccino, please"), ("Чёрный чай с лимо'ном", "Black tea with lemon"),
         ("Два сы'рника", "Two syrniki (curd pancakes)"), ("Что у вас есть на за'втрак?", "What do you have for breakfast?"),
         ("Здесь и'ли с собо'й?", "Eat here or take away?"), ("Мо'жно с молоко'м?", "Could I have it with milk?"),
         ("Мо'жно ещё одно' пиро'жное?", "Could I have one more pastry?"), ("Мо'жно ка'ртой?", "Can I pay by card?")],
        1,
    ),
    _s(
        "hotel-checkin", "Staying", "Hotel check-in", "receptionist",
        "You arrive at your Moscow hotel in the afternoon with your luggage. There is a booking for four nights.",
        "Olga, in her thirties, is a polished and professional receptionist. She speaks clearly and politely, "
        "uses formal phrases, and goes through the check-in steps in order.",
        "Здра'вствуйте! Добро' пожа'ловать. У вас есть бронь?",
        ["Say you have a booking and give the surname", "Confirm the dates and the number of guests", "Ask about breakfast times",
         "Ask how to connect to the internet", "Ask about luggage or the floor of your room"],
        [("У нас заброни'рован но'мер", "We have a room booked"), ("Бронь на фами'лию Смит", "The booking is under the name Smith"),
         ("Мы остаёмся на четы'ре но'чи", "We are staying four nights"), ("Во ско'лько за'втрак?", "What time is breakfast?"),
         ("Как подключи'ться к интерне'ту?", "How do I connect to the internet?"), ("Мо'жно оста'вить бага'ж?", "Can we leave our luggage?"),
         ("На како'м этаже' наш но'мер?", "Which floor is our room on?"), ("Вот на'ши докуме'нты", "Here are our documents")],
        1,
    ),
    _s(
        "hotel-problem", "Staying", "A problem in the room", "night receptionist",
        "It is late evening. There is no hot water in your room and the air conditioning is not working, so you go down to reception.",
        "Sergey, in his forties, is on the night shift. He is tired but apologetic, speaks quietly and fairly fast, "
        "and promises to send someone, but you may need to ask for a concrete time or another room.",
        "Слу'шаю вас. Что случи'лось?",
        ["Explain what the problem is", "Give your room number", "Ask when it will be fixed", "Ask for another room or an alternative", "Thank him"],
        [("В но'мере нет горя'чей воды'", "There is no hot water in the room"), ("Не рабо'тает кондиционе'р", "The air conditioning does not work"),
         ("Наш но'мер три'ста пять", "Our room is three hundred and five"), ("Когда' э'то испра'вят?", "When will it be fixed?"),
         ("Мо'жно перейти' в друго'й но'мер?", "Can we move to another room?"),
         ("Принеси'те, пожа'луйста, ещё одея'ло", "Please bring one more blanket"), ("Здесь о'чень шу'мно", "It is very noisy here"),
         ("Спаси'бо за по'мощь", "Thank you for your help")],
        2,
    ),
    _s(
        "pharmacy", "Shopping", "At the pharmacy", "pharmacist",
        "Someone in the family has a sore throat and a headache, so you go to a pharmacy near the hotel.",
        "Tamara, in her fifties, has seen it all. She is brisk but motherly, asks several short questions in a row "
        "(how long, any fever, any allergies), and explains how to take the medicine.",
        "До'брый день. Чем могу' вам помо'чь?",
        ["Describe the symptoms", "Ask for medicine for a sore throat or a headache", "Ask how to take it", "Mention an allergy", "Pay"],
        [("У меня' боли'т го'рло", "I have a sore throat"), ("У меня' боли'т голова'", "I have a headache"),
         ("У ребёнка температу'ра", "The child has a temperature"), ("Что-нибу'дь от ка'шля", "Something for a cough"),
         ("Для э'того ну'жен реце'пт?", "Do I need a prescription for this?"), ("Как принима'ть э'то лека'рство?", "How do I take this medicine?"),
         ("Ско'лько раз в день?", "How many times a day?"), ("У меня' аллерги'я на антибио'тики", "I am allergic to antibiotics")],
        2,
    ),
    _s(
        "market", "Shopping", "At the market", "stall holder",
        "You are at a covered market buying fruit, honey and pickles to bring to relatives. The seller loves to chat and to bargain.",
        "Rashid, in his sixties, runs a stall and calls out to every passer-by. He talks very fast, jokes, uses market slang "
        "and affectionate words, offers tastes, and will drop the price a little if you are polite.",
        "Подходи'те, подходи'те! Пробу'йте, не стесня'йтесь! Всё све'жее, сего'дняшнее!",
        ["Ask the price per kilo", "Ask to taste something", "Say how much you want", "Politely ask for a lower price", "Pay and say goodbye"],
        [("Ско'лько сто'ит килогра'мм?", "How much is a kilo?"), ("Мо'жно попро'бовать?", "May I try some?"),
         ("Да'йте, пожа'луйста, полкило'", "Give me half a kilo, please"), ("Э'то дома'шний мёд?", "Is this homemade honey?"),
         ("Почём огурцы'?", "How much are the cucumbers?"), ("Нельзя' ли немно'го деше'вле?", "Could it be a bit cheaper?"),
         ("Возьму' вот э'то", "I will take this one"), ("Положи'те в паке'т", "Put it in a bag, please"),
         ("Спаси'бо, до свида'ния", "Thank you, goodbye")],
        3,
    ),
    _s(
        "souvenirs", "Shopping", "Souvenir shop", "shop assistant",
        "A souvenir shop near Red Square. You want gifts to take home: a matryoshka, tea, chocolate, maybe a shawl.",
        "Polina, in her early twenties, is polite and eager to help. She speaks clearly, suggests items, "
        "and mentions sizes and prices without being pushy.",
        "До'брый день! Смотри'те, не стесня'йтесь. Е'сли что, спра'шивайте.",
        ["Ask whether they have matryoshka dolls", "Ask for the price", "Ask for a gift suggestion", "Ask for a cheaper option", "Ask for gift wrapping and pay"],
        [("У вас есть матрёшки?", "Do you have matryoshka dolls?"), ("Ско'лько э'то сто'ит?", "How much is this?"),
         ("Покажи'те, пожа'луйста, вот э'ту", "Please show me this one"), ("Что вы посове'туете в пода'рок?", "What do you recommend as a gift?"),
         ("Э'то сде'лано в Росси'и?", "Is this made in Russia?"), ("Есть что-нибу'дь подеше'вле?", "Is there anything cheaper?"),
         ("Упаку'йте, пожа'луйста, как пода'рок", "Please wrap it as a gift"), ("Мо'жно ка'ртой?", "Can I pay by card?")],
        1,
    ),
    _s(
        "small-talk", "People", "Chatting on a park bench", "elderly stranger",
        "You sit down on a park bench in Moscow. The elderly woman next to you starts a conversation and wants to know all about you.",
        "Valentina Petrovna, in her seventies, loves to talk. She asks personal questions, jumps between topics, "
        "tells stories about her grandchildren, and uses old-fashioned phrases and some slang. She is easily offended by a curt answer.",
        "Прекра'сная пого'да, пра'вда? А вы отку'да бу'дете?",
        ["Say where you are from", "Say why you are in Moscow", "Say what you have seen and liked", "Ask her for a recommendation", "Say goodbye politely"],
        [("Мы прие'хали из...", "We have come from..."), ("Мы здесь в пе'рвый раз", "This is our first time here"),
         ("Мы прие'хали в го'сти к родны'м", "We came to visit relatives"), ("Мне о'чень нра'вится Москва'", "I like Moscow very much"),
         ("Вы не посове'туете, что посмотре'ть?", "Could you recommend what to see?"), ("Я пло'хо говорю' по-ру'сски", "I speak Russian badly"),
         ("Прия'тно бы'ло познако'миться", "It was nice to meet you"), ("Всего' до'брого!", "All the best!")],
        3,
    ),
    _s(
        "relatives", "People", "Dinner with relatives", "relative (Aunt Galina)",
        "You arrive at your relatives' flat in Moscow for dinner. Aunt Galina greets you at the door and the table is already full of food.",
        "Galina, in her sixties, is warm, loud and impossible to refuse. She talks fast, uses affectionate diminutives, "
        "keeps putting more food on your plate, and asks about everyone in your family.",
        "Ну наконе'ц-то! Проходи'те, проходи'те, раздева'йтесь! Мы вас так жда'ли!",
        ["Greet her and say you are happy to see her", "Compliment the flat or the food", "Accept or politely refuse more food",
         "Ask about her family", "Give your presents and make a toast"],
        [("Мы о'чень ра'ды вас ви'деть", "We are very glad to see you"), ("У вас о'чень ую'тная кварти'ра", "You have a very cosy flat"),
         ("Всё о'чень вку'сно, спаси'бо", "Everything is delicious, thank you"), ("Мо'жно ещё немно'го?", "May I have a little more?"),
         ("Я бо'льше не могу'", "I can't eat any more"), ("Ско'лько лет ва'шим вну'кам?", "How old are your grandchildren?"),
         ("Э'то вам пода'рок", "This is a present for you"), ("За ва'ше здоро'вье!", "To your health!")],
        2,
    ),
    _s(
        "lost-bag", "Problems", "Lost property", "lost property clerk",
        "You left a black backpack with a phone and a passport in a taxi. You go to the lost property office to report it.",
        "Irina, in her forties, is calm and bureaucratic. She asks many precise questions in a row "
        "(what, where, when, what color), writes everything down, and speaks at a steady, fairly quick pace.",
        "Здра'вствуйте. Что у вас случи'лось?",
        ["Say what you lost", "Describe it: color, size, what is inside", "Say where and when it happened",
         "Give a phone number or your hotel", "Ask what happens next"],
        [("Мы забы'ли рюкза'к в такси'", "We left a backpack in a taxi"), ("У меня' укра'ли телефо'н", "My phone was stolen"),
         ("Рюкза'к чёрный, сре'днего разме'ра", "The backpack is black, medium-sized"), ("Внутри' был па'спорт", "There was a passport inside"),
         ("Э'то случи'лось вчера' ве'чером", "It happened yesterday evening"), ("Вот мой но'мер телефо'на", "Here is my phone number"),
         ("Куда' мне позвони'ть?", "Where should I call?"), ("Что мне де'лать?", "What should I do?")],
        2,
    ),
    _s(
        "wrong-order", "Problems", "The wrong dish", "waiter",
        "At a restaurant the soup is cold, a dish arrives that you did not order, and there is a mistake on the bill.",
        "Artyom, in his twenties, is flustered and a bit defensive. He apologizes quickly, speaks fast, "
        "may blame the kitchen, and will fetch the manager if you ask firmly but politely.",
        "Всё в поря'дке? Вам что-нибу'дь не нра'вится?",
        ["Say the dish is not what you ordered", "Say the food is cold and ask to have it warmed", "Ask for the right dish",
         "Point out the mistake on the bill", "Ask for the manager if needed"],
        [("Э'то не то, что мы заказа'ли", "This is not what we ordered"), ("Мы э'того не зака'зывали", "We did not order this"),
         ("Суп совсе'м холо'дный", "The soup is quite cold"), ("Подогре'йте, пожа'луйста", "Please warm it up"),
         ("Здесь оши'бка в счёте", "There is a mistake in the bill"), ("Мы до'лго ждём", "We have been waiting a long time"),
         ("Позови'те, пожа'луйста, администра'тора", "Please call the manager")],
        2,
    ),
]

_FIELDS = ("title", "setting", "partner_role", "persona", "opening_ru", "goals_json", "vocab_json", "level", "group", "sort", "voice")


def seed(session: Session) -> None:
    """Insert missing scenarios by slug and refresh existing ones from SCENARIOS. Never deletes."""
    existing = {s.slug: s for s in session.exec(select(Scenario)).all()}
    for order, data in enumerate(SCENARIOS):
        data = {**data, "sort": order}
        row = existing.get(data["slug"])
        if row is None:
            session.add(Scenario(**data))
            continue
        for field in _FIELDS:
            if getattr(row, field) != data[field]:
                setattr(row, field, data[field])
                session.add(row)
    session.commit()


def grouped(session: Session) -> list[tuple[str, list[Scenario]]]:
    """Scenarios grouped by situation group, in seed order."""
    groups: dict[str, list[Scenario]] = {}
    for s in session.exec(select(Scenario).order_by(Scenario.sort, Scenario.id)).all():
        groups.setdefault(s.group or "Other", []).append(s)
    return list(groups.items())

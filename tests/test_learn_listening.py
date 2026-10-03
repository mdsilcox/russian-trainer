"""The listening item templates: audio first, Russian text hidden until answered."""
from app.services.exercises import DictationItem, ListenChoiceItem
from app.web import templates

CHOICE = ListenChoiceItem(id="z1", audio_ru="Она́ на рабо́те.", question_en="Where is she?",
                          options=["At work", "At home", "In the park"], answer_index=0, explanation="на рабо́те: at work.")
DICT = DictationItem(id="d1", audio_ru="Где вокза́л?", translation_en="Where is the station?")


def render(name, item, **ctx):
    tpl = templates.env.get_template(f"learn/items/_{name}.html")
    return tpl.render(item=item, url_for=lambda n, path="": f"/static/{path}", **ctx)


def test_listen_choice_audio_first_text_hidden():
    html = render("listen_choice", CHOICE)
    assert html.index("listen-play") < html.index("listen-q") < html.index("listen-opt")
    assert 'data-speak="Она́ на рабо́те."' in html and "rate: 0.75" in html and "Slower" in html
    assert html.count('name="response"') == 3 and 'value="0"' in html and 'value="2"' in html
    reveal = html.split('class="listen-reveal"')[1].split(">")[0]
    assert "hidden" in reveal
    assert "disabled" not in html


def test_listen_choice_answered_shows_text_and_explanation():
    html = render("listen_choice", CHOICE, answered=True)
    reveal = html.split('class="listen-reveal"')[1].split(">")[0]
    assert "hidden" not in reveal
    assert "на рабо́те: at work." in html and "disabled" in html


def test_dictation_input_and_hidden_text():
    html = render("dictation", DICT)
    assert 'name="response"' in html and 'lang="ru"' in html and "autofocus" in html and 'autocorrect="off"' in html
    assert 'data-speak="Где вокза́л?"' in html and "Slower" in html
    reveal = html.split('class="listen-reveal"')[1].split(">")[0]
    assert "hidden" in reveal


def test_dictation_answered_shows_translation():
    html = render("dictation", DICT, answered=True)
    reveal = html.split('class="listen-reveal"')[1].split(">")[0]
    assert "hidden" not in reveal and "Where is the station?" in html and "readonly" in html

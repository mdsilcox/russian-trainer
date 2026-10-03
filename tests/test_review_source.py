"""The review screen's "from your story" line names the right story for each kind of story card."""

from app.models import Card, Module, Story, TranslationAttempt
from app.routes.review import source_label


def _stories(session):
    first = Story(title="Первая", source_lang="en", source_text="One.")
    second = Story(title="Вторая", source_lang="en", source_text="Two.")
    session.add_all([first, second])
    session.commit()
    attempt = TranslationAttempt(story_id=second.id, text="Два.")  # attempt id 1, story id 2
    session.add(attempt)
    session.commit()
    return first, second, attempt


def test_mistake_card_names_the_attempts_story(session):
    _, second, attempt = _stories(session)
    card = Card(ru="два", en="two", source_module=Module.story, source_ref_id=attempt.id)
    assert attempt.id != second.id
    assert source_label(session, card) == "from your story ‘Вторая’"


def test_cloze_card_names_its_story(session):
    _, second, _ = _stories(session)
    card = Card(ru="два", en="two", kind="cloze", source_module=Module.story, source_ref_id=second.id)
    assert source_label(session, card) == "from your story ‘Вторая’"

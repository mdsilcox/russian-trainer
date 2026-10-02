from app.models import TranslationAttempt
from app.routes import workshop as workshop_routes
from app.services import feedback as fb
from app.services import workshop
from app.services.claude import ClaudeClient
from tests.test_claude import FakeAnthropic, fake_response

RUSSIAN = "Я поехал на ночной поезд в Казань. Купе было маленький, но тёплое."


def sample_feedback() -> fb.Feedback:
    return fb.Feedback(
        summary="Good story! Watch prepositional endings and adjective agreement.",
        corrected_text="Я поехал на ночном поезде в Казань. Купе было маленькое, но тёплое.",
        issues=[
            fb.Issue(wrong="ночной поезд", right="ночном поезде", category="case",
                     subcategory="prepositional after на (transport)", explanation="На + prepositional for the means of transport.",
                     severity="error"),
            fb.Issue(wrong="маленький", right="маленькое", category="agreement", subcategory="neuter short adjective",
                     explanation="Купе is neuter.", severity="error"),
            fb.Issue(wrong="не в тексте", right="x", category="idiom", subcategory="", explanation="", severity="style"),
        ],
        rephrasings=[],
        vocab=[fb.VocabItem(ru="купе́", en="sleeper compartment", example_ru="Мы е́хали в купе́.",
                            example_en="We travelled in a compartment.", why="Russian trains")],
        translation_notes=[],
    )


def test_annotate_highlights_issues_in_order_and_reports_missing():
    issues = sample_feedback().issues
    segments, unplaced = fb.annotate(RUSSIAN, issues)
    assert "".join(s.text for s in segments) == RUSSIAN
    assert [s.text for s in segments if s.issue is not None] == ["ночной поезд", "маленький"]
    assert unplaced == {2}


def test_annotate_skips_overlaps():
    issues = [fb.Issue(wrong="ночной поезд", right="a", category="case", subcategory="", explanation="", severity="error"),
              fb.Issue(wrong="поезд", right="b", category="case", subcategory="", explanation="", severity="error")]
    segments, unplaced = fb.annotate("ночной поезд", issues)
    assert unplaced == {1}


def test_grouped_issues_biggest_group_first():
    groups = fb.grouped_issues(sample_feedback())
    assert [label for label, _ in groups][0] in ("Case endings", "Agreement", "Natural phrasing")
    assert sum(len(items) for _, items in groups) == 3


def test_prompt_targets_russian_side(session):
    story = workshop.create_story(session, "Train", "en", "I took the night train.", RUSSIAN)
    attempt = workshop.attempts_for(session, story.id)[0]
    assert fb.russian_text(story, attempt) == RUSSIAN
    assert "<russian>\n" + RUSSIAN in fb.build_prompt(story, attempt)

    ru_story = workshop.create_story(session, "Поезд", "ru", RUSSIAN, "I took the night train.")
    ru_attempt = workshop.attempts_for(session, ru_story.id)[0]
    assert fb.russian_text(ru_story, ru_attempt) == RUSSIAN
    assert "translation_notes" in fb.build_prompt(ru_story, ru_attempt)


def test_system_prompt_uses_settings(session):
    system = fb.build_system(session)
    assert "verbs of motion" in system and "English" in system


def test_feedback_route_stores_and_renders(client, session, monkeypatch):
    story = workshop.create_story(session, "Train", "en", "I took the night train.", RUSSIAN)
    attempt = workshop.attempts_for(session, story.id)[0]
    fake = FakeAnthropic(fake_response(parsed=sample_feedback()))
    monkeypatch.setattr(workshop_routes, "ClaudeClient", lambda s: ClaudeClient(s, client=fake))

    response = client.post(f"/workshop/{story.id}/attempts/{attempt.id}/feedback", headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert '<mark class="issue sev-error" tabindex="0">ночной поезд' in response.text
    assert "Case endings" in response.text and "купе́" in response.text
    assert "couldn't highlight" in response.text

    session.expire_all()
    stored = session.get(TranslationAttempt, attempt.id)
    assert stored.corrected_text.startswith("Я поехал на ночном поезде")
    page = client.get(f"/workshop/{story.id}").text
    assert "2 errors, 0 unnatural" in page
    assert "<ins>ночном</ins>" in page or "<ins>ночном поезде</ins>" in page


def test_feedback_without_key_shows_message(client, session, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from app.config import get_config
    get_config.cache_clear()
    story = workshop.create_story(session, "Train", "en", "I took the night train.", RUSSIAN)
    attempt = workshop.attempts_for(session, story.id)[0]
    try:
        page = client.get(f"/workshop/{story.id}").text
        assert "Set ANTHROPIC_API_KEY" in page
        response = client.post(f"/workshop/{story.id}/attempts/{attempt.id}/feedback", headers={"HX-Request": "true"})
    finally:
        get_config.cache_clear()
    assert "ANTHROPIC_API_KEY" in response.text

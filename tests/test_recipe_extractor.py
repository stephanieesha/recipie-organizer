import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import recipe_extractor
from recipe_extractor import build_prompt, extract_recipe, parse_extraction_response, NoRecipeFoundError, ExtractionError


def test_parses_a_valid_recipe_response():
    response = '''
    {"has_recipe": true, "title": "Garlic Butter Mashed Potatoes",
     "ingredients": ["4 potatoes", "2 tbsp butter", "1 clove garlic"],
     "directions": ["Boil potatoes", "Mash with butter and garlic"]}
    '''
    result = parse_extraction_response(response)
    assert result["title"] == "Garlic Butter Mashed Potatoes"
    assert len(result["ingredients"]) == 3
    assert len(result["directions"]) == 2


def test_strips_markdown_fence_with_json_tag():
    response = '```json\n{"has_recipe": true, "title": "Test", "ingredients": ["egg"], "directions": ["cook"]}\n```'
    result = parse_extraction_response(response)
    assert result["title"] == "Test"


def test_strips_bare_markdown_fence():
    response = '```\n{"has_recipe": true, "title": "Test", "ingredients": ["egg"], "directions": ["cook"]}\n```'
    result = parse_extraction_response(response)
    assert result["title"] == "Test"


def test_raises_no_recipe_found_when_flagged_false():
    response = '{"has_recipe": false, "reason": "This is a dance video with no food content"}'
    with pytest.raises(NoRecipeFoundError) as exc_info:
        parse_extraction_response(response)
    assert "dance video" in str(exc_info.value)


def test_no_recipe_found_has_default_reason_if_missing():
    response = '{"has_recipe": false}'
    with pytest.raises(NoRecipeFoundError):
        parse_extraction_response(response)


def test_raises_extraction_error_when_ingredients_missing():
    response = '{"has_recipe": true, "title": "Test", "directions": ["cook"]}'
    with pytest.raises(ExtractionError):
        parse_extraction_response(response)


def test_raises_extraction_error_when_directions_missing():
    response = '{"has_recipe": true, "title": "Test", "ingredients": ["egg"]}'
    with pytest.raises(ExtractionError):
        parse_extraction_response(response)


def test_defaults_title_when_not_provided():
    response = '{"has_recipe": true, "ingredients": ["egg"], "directions": ["cook"]}'
    result = parse_extraction_response(response)
    assert result["title"] == "Untitled recipe"


def test_raises_on_malformed_json():
    with pytest.raises(Exception):
        parse_extraction_response("not json at all")


# ---------- what the model is asked, and how, for a caption and for a note ----------

ANSWER = '{"has_recipe": true, "title": "Pancakes", "ingredients": ["flour"], "directions": ["Fry"]}'


@pytest.fixture
def model(monkeypatch):
    """A stand-in for the model: it records what it was asked, and answers with model.answer."""
    stand_in = SimpleNamespace(asked=[], answer=ANSWER)

    class FakeAnthropic:
        def __init__(self):
            self.messages = self

        def create(self, **request):
            stand_in.asked.append(request)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text=stand_in.answer)])

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.setattr(recipe_extractor.anthropic, "Anthropic", FakeAnthropic)
    return stand_in


def test_a_caption_is_introduced_as_the_caption_of_a_food_video():
    prompt = build_prompt("Mix flour and eggs")
    assert prompt.startswith("Here is a caption from a social media food video:\n\nMix flour and eggs\n\n")
    assert "Does this caption contain an actual recipe" in prompt
    assert "(wrong kind of video, no food content, or too vague to extract anything useful)" in prompt
    assert "stated or strongly implied in the caption" in prompt
    assert "note" not in prompt


def test_a_caption_is_the_default_kind_of_text():
    assert build_prompt("Mix flour", "caption") == build_prompt("Mix flour")


def test_a_note_is_introduced_as_a_note_and_never_called_a_caption_or_a_video():
    prompt = build_prompt("Mix flour and eggs", "note")
    assert prompt.startswith("Here is a note someone saved:\n\nMix flour and eggs\n\n")
    assert "Does this note contain an actual recipe" in prompt
    assert "(no food content, or too vague to extract anything useful)" in prompt
    assert "stated or strongly implied in the note" in prompt
    assert "caption" not in prompt
    assert "video" not in prompt


@pytest.mark.parametrize("kind", ["caption", "note"])
def test_either_kind_is_asked_for_the_same_json_answer(kind):
    prompt = build_prompt("Mix flour", kind)
    assert "Respond with ONLY a JSON object, no other text, no markdown fences." in prompt
    assert '{"has_recipe": false, "reason": "<brief explanation>"}' in prompt
    assert '{"has_recipe": true, "title": "<short recipe name>", ' in prompt
    assert "do not invent measurements or steps that aren't there" in prompt


def test_an_unknown_kind_of_text_is_a_mistake_in_the_code():
    with pytest.raises(KeyError):
        build_prompt("Mix flour", "tweet")


def test_a_caption_is_sent_with_the_caption_prompt_and_room_for_a_short_answer(model):
    assert extract_recipe("Mix flour")["title"] == "Pancakes"
    assert extract_recipe("Mix flour", "caption")["title"] == "Pancakes"
    assert model.asked == 2 * [{
        "model": "claude-sonnet-5",
        "max_tokens": 800,
        "messages": [{"role": "user", "content": build_prompt("Mix flour", "caption")}],
    }]


def test_a_note_is_sent_with_the_note_prompt_and_room_for_a_longer_answer(model):
    result = extract_recipe("Mix flour", "note")
    assert result == {"title": "Pancakes", "ingredients": ["flour"], "directions": ["Fry"]}
    assert model.asked == [{
        "model": "claude-sonnet-5",
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": build_prompt("Mix flour", "note")}],
    }]


def test_the_model_can_be_chosen_with_an_environment_variable(model, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "some-other-model")
    extract_recipe("Mix flour", "note")
    assert model.asked[0]["model"] == "some-other-model"


@pytest.mark.parametrize("kind", ["caption", "note"])
def test_nothing_is_asked_without_an_api_key(model, monkeypatch, kind):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(ExtractionError, match="ANTHROPIC_API_KEY"):
        extract_recipe("Mix flour", kind)
    assert model.asked == []


@pytest.mark.parametrize("kind", ["caption", "note"])
def test_a_model_that_cannot_be_reached_is_an_extraction_error(monkeypatch, kind):
    class Broken:
        def __init__(self):
            raise RuntimeError("no connection")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(recipe_extractor.anthropic, "Anthropic", Broken)
    with pytest.raises(ExtractionError, match="Could not reach the extraction service: RuntimeError: no connection"):
        extract_recipe("Mix flour", kind)


@pytest.mark.parametrize("kind", ["caption", "note"])
def test_an_answer_that_is_not_json_is_an_extraction_error_that_names_what_was_sent(model, kind):
    model.answer = "Sorry, I cannot help with that."
    with pytest.raises(ExtractionError) as error:
        extract_recipe("Mix flour", kind)
    assert str(error.value) == f"Could not parse a valid response for this {kind}"


@pytest.mark.parametrize("kind", ["caption", "note"])
def test_an_answer_that_says_there_is_no_recipe_is_passed_on(model, kind):
    model.answer = '{"has_recipe": false, "reason": "This is a shopping list"}'
    with pytest.raises(NoRecipeFoundError, match="shopping list"):
        extract_recipe("Buy eggs", kind)

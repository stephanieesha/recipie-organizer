import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from recipe_extractor import parse_extraction_response, NoRecipeFoundError, ExtractionError


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

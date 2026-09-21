"""
Extracts structured recipe data (ingredients with measurements,
step-by-step directions) from a caption's raw text using Claude.

Explicitly distinguishes "no recipe found" from a technical failure, so
the app can show a clear message rather than empty fields when someone
pastes a link to a non-food video by mistake.
"""

import json
import os

import anthropic


class NoRecipeFoundError(Exception):
    pass


class ExtractionError(Exception):
    pass


def _strip_markdown_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) > 1 else cleaned
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return cleaned.strip()


def parse_extraction_response(text: str) -> dict:
    result = json.loads(_strip_markdown_fence(text))

    if result.get("has_recipe") is False:
        raise NoRecipeFoundError(
            result.get("reason", "No recipe or food content was found in this caption")
        )

    if "ingredients" not in result or "directions" not in result:
        raise ExtractionError("The model's response was missing expected recipe fields")

    return {
        "title": result.get("title", "Untitled recipe"),
        "ingredients": result["ingredients"],
        "directions": result["directions"],
    }


def extract_recipe(caption_text: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ExtractionError("Recipe extraction requires an ANTHROPIC_API_KEY to be set.")

    prompt = (
        "Here is a caption from a social media food video:\n\n"
        f"{caption_text}\n\n"
        "Does this caption contain an actual recipe (ingredients and/or "
        "cooking steps), even if informally written? Respond with ONLY a "
        "JSON object, no other text, no markdown fences.\n\n"
        "If it does NOT contain a recipe (wrong kind of video, no food "
        "content, or too vague to extract anything useful), respond with:\n"
        '{"has_recipe": false, "reason": "<brief explanation>"}\n\n'
        "If it DOES contain a recipe, respond with:\n"
        '{"has_recipe": true, "title": "<short recipe name>", '
        '"ingredients": ["<ingredient with measurement>", ...], '
        '"directions": ["<step 1>", "<step 2>", ...]}\n\n'
        "Only include ingredients and steps actually stated or strongly "
        "implied in the caption - do not invent measurements or steps "
        "that aren't there. If a measurement isn't given, just list the "
        "ingredient name."
    )

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
    except Exception as e:
        raise ExtractionError(f"Could not reach the extraction service: {type(e).__name__}: {e}")

    try:
        return parse_extraction_response(text)
    except json.JSONDecodeError:
        raise ExtractionError("Could not parse a valid response for this caption")

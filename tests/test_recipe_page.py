"""
The page of one recipe: what it shows for a recipe that came from a link and for one written out in
notes, which has no link to go back to. The page script runs in Node.js with a small browser stub;
these tests are skipped when Node.js is not installed.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).parent.parent / "templates" / "recipe.html"

NODE_RUNNER = r"""
const fs = require('fs');
const vm = require('vm');

const html = fs.readFileSync(__PAGE__, 'utf8').replace('{{ recipe_id }}', '7');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

const recipe = (fields) => ({
  id: 7, title: 'Garlic noodles', status: 'extracted', ingredients: ['noodles'], directions: ['Boil'],
  source_url: '', platform: 'notes', caption_raw: null, thumbnail_url: null, ...fields,
});

// What the recipe card holds once the page has loaded this recipe.
async function show(fields, found = true) {
  const card = { innerHTML: '' };
  const requested = [];
  const sandbox = {
    document: { getElementById: () => card },
    fetch: async (url) => {
      requested.push(url);
      return { ok: found, json: async () => recipe(fields) };
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(script, sandbox);
  await new Promise((resolve) => setTimeout(resolve, 0));
  return { card: card.innerHTML, requested };
}

const scenarios = {
__SCENARIOS__
};

(async () => {
  const results = {};
  for (const [name, scenario] of Object.entries(scenarios)) {
    results[name] = await scenario();
  }
  console.log(JSON.stringify(results));
})().catch((err) => { console.error(err); process.exit(1); });
"""

SCENARIOS = r"""
  from_a_link: () => show({
    source_url: 'https://www.tiktok.com/@chef/video/7123456789', platform: 'tiktok', caption_raw: 'Boil noodles, fry garlic',
  }),

  from_a_link_with_quotes: () => show({
    source_url: 'https://www.tiktok.com/@chef/video/1?a="b"&c=<d>', platform: 'tiktok',
  }),

  from_notes: () => show({ caption_raw: 'Garlic noodles\nBoil noodles, fry garlic.' }),

  from_notes_without_a_text: () => show({ caption_raw: null }),

  from_notes_not_read_yet: () => show({ title: 'Garlic noodles', status: 'needs_manual', ingredients: [], directions: [], caption_raw: 'Garlic noodles\nBoil noodles.' }),

  not_found: () => show({}, false),
"""


@pytest.fixture(scope="module")
def pages():
    if shutil.which("node") is None:
        pytest.skip("runs the page script with Node.js")
    code = NODE_RUNNER.replace("__PAGE__", json.dumps(str(PAGE))).replace("__SCENARIOS__", SCENARIOS)
    result = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def test_the_page_asks_for_the_recipe_it_was_opened_for(pages):
    assert pages["from_a_link"]["requested"] == ["/api/recipes/7"]


def test_a_recipe_from_a_link_has_a_link_back_to_the_post(pages):
    card = pages["from_a_link"]["card"]
    assert '<a href="https://www.tiktok.com/@chef/video/7123456789" target="_blank" class="source-link">View original on tiktok</a>' in card
    assert "Garlic noodles" in card


def test_the_link_back_to_the_post_is_made_safe_to_put_in_the_page(pages):
    card = pages["from_a_link_with_quotes"]["card"]
    assert 'href="https://www.tiktok.com/@chef/video/1?a=&quot;b&quot;&amp;c=&lt;d&gt;"' in card


def test_a_recipe_from_a_link_calls_its_text_the_original_caption(pages):
    card = pages["from_a_link"]["card"]
    assert "Original caption" in card
    assert "Original note" not in card
    assert "Boil noodles, fry garlic" in card


def test_a_recipe_from_notes_has_no_link_back_because_there_is_none(pages):
    card = pages["from_notes"]["card"]
    assert "View original" not in card
    assert "source-link" not in card
    assert "href" not in card


def test_a_recipe_from_notes_calls_its_text_the_original_note_and_keeps_its_line_breaks(pages):
    card = pages["from_notes"]["card"]
    assert "Original note" in card
    assert "Original caption" not in card
    assert "white-space:pre-wrap" in card
    assert "Garlic noodles\nBoil noodles, fry garlic." in card


def test_a_recipe_from_notes_still_shows_its_title_ingredients_and_steps(pages):
    card = pages["from_notes"]["card"]
    assert '<h2 class="recipe-title">Garlic noodles</h2>' in card
    assert "<li>noodles</li>" in card
    assert "<li>Boil</li>" in card
    assert "Edit" in card


def test_a_recipe_from_notes_with_no_text_has_no_original_section(pages):
    card = pages["from_notes_without_a_text"]["card"]
    assert "Original note" not in card
    assert "Original caption" not in card


def test_a_note_that_could_not_be_read_says_so_and_keeps_its_title_and_text(pages):
    card = pages["from_notes_not_read_yet"]["card"]
    assert "No recipe could be extracted automatically for this one" in card
    assert '<h2 class="recipe-title">Garlic noodles</h2>' in card
    assert "Original note" in card
    assert "View original" not in card


def test_a_recipe_that_is_not_found_says_so(pages):
    assert pages["not_found"]["card"] == "<p>Recipe not found.</p>"

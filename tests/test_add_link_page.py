"""
What the person sees in the "add a recipe" box when something goes wrong. Runs the real page
script with Node.js and a small browser stub, so the answers from the server are made up
here and no network is used. Skipped when Node.js is not installed.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).parent.parent / "templates" / "index.html"

NODE_RUNNER = r"""
const fs = require('fs');
const vm = require('vm');

const html = fs.readFileSync(__PAGE__, 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

const scenarios = __SCENARIOS__;
const results = {};

async function run(name, scenario) {
  const elements = {};
  function element(id) {
    if (!elements[id]) {
      elements[id] = { value: '', innerHTML: '', style: {}, files: [], focus() {}, addEventListener() {} };
    }
    return elements[id];
  }

  async function fakeFetch(url, options) {
    // The lists the page loads when it opens are always fine.
    if (!options || !options.method || options.method === 'GET') {
      return { ok: true, status: 200, json: async () => [] };
    }
    if (scenario.network_down) throw new TypeError('Failed to fetch');
    return {
      ok: scenario.status < 400,
      status: scenario.status,
      json: async () => {
        if (scenario.body === undefined) throw new SyntaxError('Unexpected token < in JSON');
        return scenario.body;
      },
    };
  }

  const sandbox = {
    document: { getElementById: element },
    fetch: fakeFetch,
    window: { location: {} },
    FormData: function () { this.append = () => {}; },
  };
  vm.createContext(sandbox);
  vm.runInContext(script, sandbox);
  await new Promise((resolve) => setTimeout(resolve, 0));

  element('urlInput').value = 'https://vt.tiktok.com/ZSabc/';
  element('categorySelect').value = '';
  await sandbox.addRecipe();
  results[name] = element('addMessage').innerHTML;
}

(async () => {
  for (const [name, scenario] of Object.entries(scenarios)) {
    await run(name, scenario);
  }
  console.log(JSON.stringify(results));
})().catch((err) => { console.error(err); process.exit(1); });
"""

SCENARIOS = {
    "error_page": {"status": 500},
    "bad_gateway_page": {"status": 502},
    "success_without_json": {"status": 201},
    "network_down": {"network_down": True},
    "plain_error": {"status": 400, "body": {"error": "That is more than one link."}},
    "error_without_message": {"status": 400, "body": {}},
    "html_in_error": {"status": 400, "body": {"error": "<img src=x onerror=alert(1)>"}},
    "saved_with_reason": {
        "status": 201,
        "body": {"status": "needs_manual", "extraction_message": "The link is saved. TikTok took too long to answer."},
    },
}


@pytest.fixture(scope="module")
def messages():
    if shutil.which("node") is None:
        pytest.skip("runs the page script with Node.js")
    code = (NODE_RUNNER.replace("__PAGE__", json.dumps(str(PAGE)))
                       .replace("__SCENARIOS__", json.dumps(SCENARIOS)))
    result = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


@pytest.mark.parametrize("name", ["error_page", "bad_gateway_page"])
def test_an_error_page_becomes_a_plain_message_not_a_stuck_page(messages, name):
    assert "Something went wrong on our side. Try again in a moment." in messages[name]
    assert "Adding..." not in messages[name]


def test_a_dropped_connection_says_so(messages):
    assert "Could not reach the server. Check your connection and try again." in messages["network_down"]
    assert "Adding..." not in messages["network_down"]


def test_an_answer_that_is_not_json_is_reported(messages):
    assert "The server sent back something unexpected. Try again." in messages["success_without_json"]


def test_the_servers_own_message_is_shown(messages):
    assert "That is more than one link." in messages["plain_error"]


def test_an_error_without_a_message_still_says_something(messages):
    assert "Something went wrong. Try again." in messages["error_without_message"]


def test_the_message_is_shown_as_text_not_run_as_html(messages):
    assert "<img" not in messages["html_in_error"]
    assert "&lt;img" in messages["html_in_error"]


def test_a_saved_link_explains_why_nothing_was_filled_in(messages):
    shown = messages["saved_with_reason"]
    assert "The link is saved. TikTok took too long to answer." in shown
    assert "You can edit it manually from the recipe page." in shown


def test_the_page_uses_the_safe_request_helper_for_every_form():
    html = PAGE.read_text(encoding="utf-8")
    for url in ("'/api/recipes'", "`/api/recipes/${pendingCaptionRecipeId}/caption`", "'/api/recipes/bulk-import'"):
        assert re.search(r"sendRequest\(\s*" + re.escape(url), html), url

"""
The import box on the home page: what it tells a person to upload, and the preview of what a
file holds before anything is saved. The Node.js tests are skipped when Node.js is not installed.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).parent.parent / "templates" / "index.html"


def test_the_import_box_says_how_to_get_the_instagram_file():
    html = PAGE.read_text(encoding="utf-8")
    assert "Download your information" in html
    assert "Choose JSON as the format" in html
    assert "saved_posts.json" in html


def test_the_import_box_says_how_to_get_the_tiktok_file_and_what_is_imported_from_it():
    html = PAGE.read_text(encoding="utf-8")
    assert "Download your data" in html
    assert "Choose JSON as the file format" in html
    assert "user_data.json" in html
    assert "Only your favorites" in html
    assert "not your likes or watch history" in html


# ---------- the preview, as the page runs it ----------
#
# The page script runs in Node.js with a small browser stub. The buttons and the file box are
# found in the page's own markup and their onclick / onchange code is run, so a button that is
# not wired to the right function fails here. The server's answers are made up.

NODE_RUNNER = r"""
const fs = require('fs');
const vm = require('vm');

const html = fs.readFileSync(__PAGE__, 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

const reel = (i) => ({ url: 'https://www.instagram.com/reel/CODE' + i + '/', platform: 'instagram' });
const reels = (count) => Array.from({ length: count }, (_, i) => reel(i + 1));

async function newPage() {
  const elements = {};
  function element(id) {
    if (!elements[id]) {
      elements[id] = { value: '', innerHTML: '', textContent: '', style: {}, files: [], disabled: false, focus() {}, addEventListener() {} };
    }
    return elements[id];
  }

  const page = { posts: [], gets: [], replies: {}, el: element };

  async function fakeFetch(url, options) {
    options = options || {};
    if (!options.method || options.method === 'GET') {
      page.gets.push(url);
      return { ok: true, status: 200, json: async () => [] };
    }
    page.posts.push({
      url,
      method: options.method,
      headers: options.headers || {},
      body: typeof options.body === 'string'
        ? JSON.parse(options.body)
        : { form: options.body.entries.map(([key, file]) => [key, file.name]) },
    });
    const reply = page.replies[url];
    if (!reply) throw new Error('no answer planned for ' + url);
    if (reply.networkDown) throw new TypeError('Failed to fetch');
    if (reply.wait) await reply.wait;
    return { ok: reply.status < 400, status: reply.status, json: async () => reply.body };
  }

  const sandbox = {
    document: { getElementById: element },
    fetch: fakeFetch,
    window: { location: {} },
    FormData: function () { this.entries = []; this.append = (key, value) => this.entries.push([key, value]); },
  };
  vm.createContext(sandbox);
  vm.runInContext(script, sandbox);
  const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
  await settle();
  page.gets.length = 0;

  page.settle = settle;
  page.call = (code) => vm.runInContext(code, sandbox);

  page.chooseFile = (name) => {
    element('bulkFileInput').files = [{ name }];
    element('bulkFileInput').value = 'C:\\fakepath\\' + name;
    const input = html.match(/<input[^>]*id="bulkFileInput"[^>]*>/)[0];
    page.call(input.match(/onchange="([^"]*)"/)[1]);
  };

  // Presses a button, found by its id or its label, the way a browser would: not when it is disabled.
  page.click = async (which) => {
    const buttons = [...html.matchAll(/<button([^>]*)>([^<]*)<\/button>/g)];
    const found = buttons.find((b) => b[1].includes('id="' + which + '"') || b[2].trim() === which);
    if (!found) throw new Error('no button ' + which);
    const id = (found[1].match(/id="([^"]*)"/) || [])[1];
    if (id && element(id).disabled) return;
    await page.call(found[1].match(/onclick="([^"]*)"/)[1]);
  };

  // Clicks the checkbox on one row of the list by running the code the row carries.
  page.tick = (row) => {
    const boxes = [...element('importList').innerHTML.matchAll(/<input[^>]*>/g)];
    page.call(boxes[row][0].match(/onchange="([^"]*)"/)[1]);
  };

  page.preview = async (links, limit, name) => {
    page.replies['/api/recipes/import-preview'] = { status: 200, body: { limit, links } };
    page.chooseFile(name || 'saved_posts.json');
    await page.click('previewButton');
  };

  // What is on the screen. ticked is how the rows were drawn; after a click on a row, read the
  // import button instead.
  page.view = () => {
    const list = element('importList').innerHTML;
    const button = element('importButton');
    return {
      panel: element('importPreview').style.display,
      summary: element('importSummary').innerHTML.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim(),
      ticked: [...list.matchAll(/<input[^>]*>/g)].map((m) => /\bchecked\b/.test(m[0])),
      urls: [...list.matchAll(/<span class="import-url"[^>]*>([^<]*)<\/span>/g)].map((m) => m[1]),
      listHtml: list,
      importLabel: button.textContent,
      importDisabled: button.disabled,
      selectAllLabel: element('selectAllButton').textContent,
      previewDisabled: element('previewButton').disabled,
      message: element('bulkMessage').innerHTML,
      chosenFile: element('bulkFileInput').value,
      location: sandbox.window.location.href || null,
    };
  };

  return page;
}

const scenarios = {
__SCENARIOS__
};

(async () => {
  const results = {};
  for (const [name, scenario] of Object.entries(scenarios)) {
    results[name] = await scenario(await newPage());
  }
  console.log(JSON.stringify(results));
})().catch((err) => { console.error(err); process.exit(1); });
"""

SCENARIOS = r"""
  listed: async (page) => {
    await page.preview(reels(3), 25);
    return { view: page.view(), posts: page.posts };
  },

  one_recipe: async (page) => {
    await page.preview(reels(1), 25);
    return page.view();
  },

  over_the_limit: async (page) => {
    await page.preview(reels(40), 25);
    const start = page.view();
    page.tick(30);
    const tooMany = page.view();
    page.tick(30);
    return { start, tooMany, back: page.view() };
  },

  no_limit: async (page) => {
    await page.preview(reels(40), 0);
    return page.view();
  },

  select_buttons: async (page) => {
    await page.preview(reels(40), 25);
    await page.click('Select none');
    const none = page.view();
    await page.click('selectAllButton');
    return { none, all: page.view() };
  },

  import_the_first_ones: async (page) => {
    page.replies['/api/recipes/bulk-import'] = { status: 200, body: { recipe_ids: [1] } };
    await page.preview(reels(40), 25);
    await page.click('importButton');
    return page.posts;
  },

  import_with_no_limit: async (page) => {
    page.replies['/api/recipes/bulk-import'] = { status: 200, body: { recipe_ids: [1] } };
    await page.preview(reels(40), 0);
    await page.click('importButton');
    return page.posts;
  },

  import_ticked: async (page) => {
    page.replies['/api/recipes/bulk-import'] = { status: 200, body: { recipe_ids: [7, 8] } };
    await page.preview(reels(3), 25);
    page.tick(2);
    await page.click('importButton');
    return { posts: page.posts, view: page.view() };
  },

  import_fails_then_works: async (page) => {
    page.replies['/api/recipes/bulk-import'] = { status: 400, body: { error: 'Too many links in one import (the limit is 25)' } };
    await page.preview(reels(3), 25);
    page.tick(0);
    await page.click('importButton');
    const afterError = page.view();
    page.replies['/api/recipes/bulk-import'] = { status: 200, body: { recipe_ids: [4, 5] } };
    await page.click('importButton');
    return { afterError, posts: page.posts, final: page.view() };
  },

  import_with_the_connection_down: async (page) => {
    page.replies['/api/recipes/bulk-import'] = { networkDown: true };
    await page.preview(reels(2), 25);
    await page.click('importButton');
    return page.view();
  },

  import_saves_nothing_new: async (page) => {
    page.replies['/api/recipes/bulk-import'] = { status: 200, body: { recipe_ids: [] } };
    await page.preview(reels(2), 25);
    await page.click('importButton');
    return { view: page.view(), gets: page.gets };
  },

  import_one: async (page) => {
    page.replies['/api/recipes/bulk-import'] = { status: 200, body: { recipe_ids: [9] } };
    await page.preview(reels(1), 25);
    await page.click('importButton');
    return page.view();
  },

  import_error_is_text: async (page) => {
    page.replies['/api/recipes/bulk-import'] = { status: 400, body: { error: '<img src=x onerror=alert(1)>' } };
    await page.preview(reels(1), 25);
    await page.click('importButton');
    return page.view();
  },

  import_answered_without_ids: async (page) => {
    page.replies['/api/recipes/bulk-import'] = { status: 200, body: {} };
    await page.preview(reels(2), 25);
    await page.click('importButton');
    return page.view();
  },

  preview_fails: async (page) => {
    page.replies['/api/recipes/import-preview'] = { status: 422, body: { error: 'No Instagram or TikTok links found in this file.' } };
    page.chooseFile('notes.txt');
    await page.click('previewButton');
    const failed = page.view();
    await page.preview(reels(2), 25);
    return { failed, retried: page.view() };
  },

  preview_error_is_text: async (page) => {
    page.replies['/api/recipes/import-preview'] = { status: 422, body: { error: '<img src=x onerror=alert(1)>' } };
    page.chooseFile('notes.txt');
    await page.click('previewButton');
    return page.view();
  },

  a_failed_preview_clears_the_one_before: async (page) => {
    await page.preview(reels(3), 25);
    page.replies['/api/recipes/import-preview'] = { status: 400, body: { error: 'Something went wrong. Try again.' } };
    await page.click('previewButton');
    return page.view();
  },

  preview_with_no_file: async (page) => {
    await page.click('previewButton');
    return { view: page.view(), posts: page.posts };
  },

  cancel: async (page) => {
    await page.preview(reels(3), 25);
    await page.click('Cancel');
    await page.call('importSelected()');
    return { view: page.view(), posts: page.posts };
  },

  another_file_clears_the_preview: async (page) => {
    await page.preview(reels(3), 25);
    page.chooseFile('other.json');
    return page.view();
  },

  addresses_are_text_not_html: async (page) => {
    await page.preview([{ url: 'https://www.instagram.com/reel/a"b<script>x/', platform: '<b>instagram</b>' }], 25);
    return page.view();
  },

  busy_preview: async (page) => {
    let answer;
    page.replies['/api/recipes/import-preview'] = {
      status: 200, body: { limit: 25, links: reels(2) }, wait: new Promise((resolve) => { answer = resolve; }),
    };
    page.chooseFile('saved_posts.json');
    const waiting = page.click('previewButton');
    await page.settle();
    const during = page.view();
    await page.click('previewButton');
    await page.call('previewImport()');
    answer();
    await waiting;
    return { during, posts: page.posts, after: page.view() };
  },

  busy_buttons: async (page) => {
    let answer;
    page.replies['/api/recipes/bulk-import'] = {
      status: 200, body: { recipe_ids: [1, 2, 3] }, wait: new Promise((resolve) => { answer = resolve; }),
    };
    await page.preview(reels(3), 25);
    const waiting = page.click('importButton');
    await page.settle();
    const during = page.view();
    await page.click('importButton');
    await page.call('importSelected()');
    await page.call('previewImport()');
    answer();
    await waiting;
    return { during, posts: page.posts, after: page.view() };
  },

  nothing_to_import: async (page) => {
    await page.preview(reels(40), 25);
    await page.click('Select none');
    await page.call('importSelected()');
    const sentWithNothingTicked = page.posts.length;
    await page.click('selectAllButton');
    page.tick(30);
    await page.call('importSelected()');
    return { sentWithNothingTicked, sentWithTooMany: page.posts.length };
  },
"""


@pytest.fixture(scope="module")
def screens():
    if shutil.which("node") is None:
        pytest.skip("runs the page script with Node.js")
    code = NODE_RUNNER.replace("__PAGE__", json.dumps(str(PAGE))).replace("__SCENARIOS__", SCENARIOS)
    result = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def reel(i):
    return f"https://www.instagram.com/reel/CODE{i}/"


PREVIEW = "/api/recipes/import-preview"
IMPORT = "/api/recipes/bulk-import"


def test_preview_sends_the_file_to_the_preview_and_lists_every_recipe_in_it(screens):
    view, posts = screens["listed"]["view"], screens["listed"]["posts"]
    assert posts == [{"url": PREVIEW, "method": "POST", "headers": {}, "body": {"form": [["file", "saved_posts.json"]]}}]
    assert view["panel"] == "block"
    assert view["urls"] == [reel(1), reel(2), reel(3)]
    assert "instagram" in view["listHtml"]
    assert view["summary"] == "Found 3 recipes."
    assert view["message"] == ""


def test_every_recipe_in_a_short_list_starts_ticked(screens):
    view = screens["listed"]["view"]
    assert view["ticked"] == [True, True, True]
    assert view["importLabel"] == "Import 3 recipes"
    assert view["importDisabled"] is False
    assert view["selectAllLabel"] == "Select all"


def test_nothing_is_saved_by_previewing(screens):
    assert [post["url"] for post in screens["listed"]["posts"]] == [PREVIEW]


def test_one_recipe_is_said_in_the_singular(screens):
    view = screens["one_recipe"]
    assert view["summary"] == "Found 1 recipe."
    assert view["importLabel"] == "Import 1 recipe"


def test_a_long_list_starts_with_the_first_ones_ticked_up_to_the_limit(screens):
    start = screens["over_the_limit"]["start"]
    assert len(start["urls"]) == 40
    assert start["ticked"] == [True] * 25 + [False] * 15
    assert start["importLabel"] == "Import 25 recipes"
    assert start["importDisabled"] is False
    assert start["selectAllLabel"] == "Select first 25"
    assert "You can import 25 at a time, so the first 25 are ticked." in start["summary"]
    assert start["summary"].startswith("Found 40 recipes.")


def test_ticking_more_than_the_limit_stops_the_import_and_says_how_many_to_untick(screens):
    too_many = screens["over_the_limit"]["tooMany"]
    assert too_many["importLabel"] == "Import 26 recipes"
    assert too_many["importDisabled"] is True
    assert "You can import 25 at a time. Untick 1 to continue." in too_many["summary"]


def test_unticking_back_to_the_limit_allows_the_import_again(screens):
    back = screens["over_the_limit"]["back"]
    assert back["importLabel"] == "Import 25 recipes"
    assert back["importDisabled"] is False
    assert "to continue" not in back["summary"]


def test_with_no_limit_every_recipe_starts_ticked(screens):
    view = screens["no_limit"]
    assert view["ticked"] == [True] * 40
    assert view["importLabel"] == "Import 40 recipes"
    assert view["importDisabled"] is False
    assert view["selectAllLabel"] == "Select all"
    assert view["summary"] == "Found 40 recipes."


def test_select_none_unticks_everything_and_stops_the_import(screens):
    none = screens["select_buttons"]["none"]
    assert none["ticked"] == [False] * 40
    assert none["importLabel"] == "Import 0 recipes"
    assert none["importDisabled"] is True


def test_select_all_ticks_everything_that_one_import_can_take(screens):
    everything = screens["select_buttons"]["all"]
    assert everything["ticked"] == [True] * 25 + [False] * 15
    assert everything["importDisabled"] is False


def test_importing_sends_only_the_ticked_links_in_order_as_json(screens):
    posts = screens["import_ticked"]["posts"]
    assert [post["url"] for post in posts] == [PREVIEW, IMPORT]
    assert posts[1]["method"] == "POST"
    assert posts[1]["headers"] == {"Content-Type": "application/json"}
    assert posts[1]["body"] == {"links": [reel(1), reel(2)]}


def test_importing_a_long_list_sends_the_first_ones_up_to_the_limit(screens):
    posts = screens["import_the_first_ones"]
    assert [post["url"] for post in posts] == [PREVIEW, IMPORT]
    assert posts[1]["body"] == {"links": [reel(i) for i in range(1, 26)]}


def test_importing_with_no_limit_sends_every_ticked_link(screens):
    posts = screens["import_with_no_limit"]
    assert posts[1]["body"] == {"links": [reel(i) for i in range(1, 41)]}


def test_after_importing_the_page_goes_to_the_review_of_what_was_saved(screens):
    view = screens["import_ticked"]["view"]
    assert view["location"] == "/bulk-review?ids=7,8"
    assert "Saved 2 recipes" in view["message"]
    assert view["panel"] == "none"


def test_a_failed_import_says_why_and_keeps_the_choice(screens):
    after_error = screens["import_fails_then_works"]["afterError"]
    assert "Too many links in one import (the limit is 25)" in after_error["message"]
    assert after_error["panel"] == "block"
    assert after_error["importLabel"] == "Import 2 recipes"
    assert after_error["importDisabled"] is False
    assert after_error["previewDisabled"] is False
    assert after_error["location"] is None


def test_trying_again_after_a_failed_import_sends_the_same_choice(screens):
    result = screens["import_fails_then_works"]
    assert [post["body"] for post in result["posts"][1:]] == [{"links": [reel(2), reel(3)]}] * 2
    assert result["final"]["location"] == "/bulk-review?ids=4,5"


def test_an_import_with_the_connection_down_says_so_and_keeps_the_list(screens):
    view = screens["import_with_the_connection_down"]
    assert "Could not reach the server. Check your connection and try again." in view["message"]
    assert view["panel"] == "block"
    assert view["importDisabled"] is False


def test_an_import_that_saves_nothing_new_stays_on_the_page(screens):
    view, gets = screens["import_saves_nothing_new"]["view"], screens["import_saves_nothing_new"]["gets"]
    assert "Nothing new was saved." in view["message"]
    assert view["location"] is None
    assert view["panel"] == "none"
    assert view["chosenFile"] == ""
    assert gets == ["/api/recipes"]


def test_one_saved_recipe_is_said_in_the_singular(screens):
    view = screens["import_one"]
    assert "Saved 1 recipe - taking you" in view["message"]
    assert view["location"] == "/bulk-review?ids=9"


def test_the_message_for_a_failed_import_is_text_not_html(screens):
    message = screens["import_error_is_text"]["message"]
    assert "<img" not in message
    assert "&lt;img" in message


def test_an_answer_without_ids_is_treated_as_nothing_saved(screens):
    view = screens["import_answered_without_ids"]
    assert "Nothing new was saved." in view["message"]
    assert view["location"] is None


def test_a_file_that_cannot_be_previewed_says_why_and_shows_no_list(screens):
    failed = screens["preview_fails"]["failed"]
    assert "No Instagram or TikTok links found in this file." in failed["message"]
    assert failed["panel"] == "none"
    assert failed["previewDisabled"] is False


def test_previewing_again_after_a_failure_works(screens):
    retried = screens["preview_fails"]["retried"]
    assert retried["panel"] == "block"
    assert retried["urls"] == [reel(1), reel(2)]
    assert retried["message"] == ""


def test_the_message_for_a_file_that_cannot_be_previewed_is_text_not_html(screens):
    message = screens["preview_error_is_text"]["message"]
    assert "<img" not in message
    assert "&lt;img" in message


def test_a_failed_preview_removes_the_list_from_the_one_before(screens):
    view = screens["a_failed_preview_clears_the_one_before"]
    assert view["panel"] == "none"
    assert view["urls"] == []
    assert "Something went wrong. Try again." in view["message"]


def test_previewing_without_choosing_a_file_asks_for_one_and_sends_nothing(screens):
    result = screens["preview_with_no_file"]
    assert "Choose a file first." in result["view"]["message"]
    assert result["posts"] == []


def test_cancel_removes_the_list_and_leaves_nothing_to_import(screens):
    view = screens["cancel"]["view"]
    assert view["panel"] == "none"
    assert view["urls"] == []
    assert view["summary"] == ""
    assert view["importDisabled"] is True
    assert [post["url"] for post in screens["cancel"]["posts"]] == [PREVIEW]


def test_choosing_another_file_removes_the_list_of_the_first_one(screens):
    view = screens["another_file_clears_the_preview"]
    assert view["panel"] == "none"
    assert view["urls"] == []


def test_addresses_in_the_list_are_shown_as_text_not_run_as_html(screens):
    html = screens["addresses_are_text_not_html"]["listHtml"]
    assert "<script" not in html
    assert "<b>" not in html
    assert "&lt;script&gt;" in html
    assert "a&quot;b" in html


def test_buttons_are_off_while_an_import_is_running_and_it_is_sent_only_once(screens):
    result = screens["busy_buttons"]
    assert result["during"]["importDisabled"] is True
    assert result["during"]["previewDisabled"] is True
    assert "Importing" in result["during"]["message"]
    assert [post["url"] for post in result["posts"]] == [PREVIEW, IMPORT]
    assert result["after"]["location"] == "/bulk-review?ids=1,2,3"


def test_the_preview_button_is_off_while_a_file_is_being_read_and_the_file_is_sent_only_once(screens):
    result = screens["busy_preview"]
    assert result["during"]["previewDisabled"] is True
    assert "Reading the file" in result["during"]["message"]
    assert [post["url"] for post in result["posts"]] == [PREVIEW]
    assert result["after"]["previewDisabled"] is False
    assert result["after"]["urls"] == [reel(1), reel(2)]
    assert result["after"]["message"] == ""


def test_the_import_does_nothing_with_nothing_ticked_or_too_many_ticked(screens):
    result = screens["nothing_to_import"]
    assert result["sentWithNothingTicked"] == 1  # only the preview
    assert result["sentWithTooMany"] == 1

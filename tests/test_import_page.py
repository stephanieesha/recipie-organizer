"""
The import box on the home page: what it tells a person to upload, and the preview of what a
file holds before anything is saved. The Node.js tests are skipped when Node.js is not installed.
"""

import html
import json
import re
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
// A recipe written out in the notes, as the server lists it, and a list of them.
const note = (i) => ({ kind: 'note', text: 'Recipe ' + i + '\nIngredients and steps for recipe ' + i + '.', title: 'Recipe ' + i, url: '', platform: 'notes' });
const notes = (count) => Array.from({ length: count }, (_, i) => note(i + 1));
// The same list with some of its recipes marked as saved already (counting from 1).
const withSaved = (links, ...saved) => links.map((link, i) => ({ ...link, already_saved: saved.includes(i + 1) }));

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

  // Types in the notes box the way a browser would: its own oninput code runs.
  page.typeNotes = (text) => {
    element('notesInput').value = text;
    const box = html.match(/<textarea[^>]*id="notesInput"[^>]*>/)[0];
    page.call(box.match(/oninput="([^"]*)"/)[1]);
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

  page.previewNotes = async (items, limit, skipped, text) => {
    page.replies['/api/recipes/notes-preview'] = { status: 200, body: { limit, links: items, skipped } };
    page.typeNotes(text || 'my notes');
    await page.click('notesPreviewButton');
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
      locked: [...list.matchAll(/<input[^>]*>/g)].map((m) => /\bdisabled\b/.test(m[0])),
      markedSaved: [...list.matchAll(/<label[\s\S]*?<\/label>/g)].map((m) => m[0].includes('already saved')),
      urls: [...list.matchAll(/<span class="import-url"[^>]*>([^<]*)<\/span>/g)].map((m) => m[1]),
      listHtml: list,
      importLabel: button.textContent,
      importDisabled: button.disabled,
      selectAllLabel: element('selectAllButton').textContent,
      previewDisabled: element('previewButton').disabled,
      notesPreviewDisabled: element('notesPreviewButton').disabled,
      notesText: element('notesInput').value,
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

  some_already_saved: async (page) => {
    page.replies['/api/recipes/bulk-import'] = { status: 200, body: { recipe_ids: [1, 2, 3] } };
    await page.preview(withSaved(reels(5), 2, 4), 25);
    const view = page.view();
    await page.click('importButton');
    return { view, posts: page.posts };
  },

  saved_ones_do_not_count_toward_the_limit: async (page) => {
    await page.preview(withSaved(reels(40), 1, 2, 3, 4, 5, 6, 7, 8, 9, 10), 25);
    const start = page.view();
    await page.click('Select none');
    await page.click('selectAllButton');
    return { start, again: page.view() };
  },

  exactly_one_import_worth: async (page) => {
    await page.preview(reels(25), 25);
    return page.view();
  },

  few_enough_new_ones_for_one_import: async (page) => {
    await page.preview(withSaved(reels(40), ...Array.from({ length: 20 }, (_, i) => i + 1)), 25);
    return page.view();
  },

  everything_already_saved: async (page) => {
    await page.preview(withSaved(reels(3), 1, 2, 3), 25);
    await page.click('selectAllButton');
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

  notes_listed: async (page) => {
    await page.previewNotes([reel(1), note(1), note(2)], 25, 0, 'my notes');
    return { view: page.view(), posts: page.posts };
  },

  notes_left_out: async (page) => {
    await page.previewNotes([note(1)], 25, 1);
    const one = page.view();
    await page.previewNotes([note(1)], 25, 3);
    const three = page.view();
    await page.previewNotes([note(1)], 25, 0);
    return { one, three, none: page.view() };
  },

  notes_sent_as_typed: async (page) => {
    await page.previewNotes([note(1)], 25, 0, '\n  my notes  \n');
    return page.posts;
  },

  notes_import_chosen: async (page) => {
    page.replies['/api/recipes/bulk-import'] = { status: 200, body: { recipe_ids: [5, 6] } };
    await page.previewNotes([reel(1), note(1), note(2)], 25, 0, 'my notes');
    page.tick(1);
    await page.click('importButton');
    return { posts: page.posts, view: page.view() };
  },

  notes_import_only_notes: async (page) => {
    page.replies['/api/recipes/bulk-import'] = { status: 200, body: { recipe_ids: [5, 6] } };
    await page.previewNotes([note(1), note(2)], 25, 0);
    await page.click('importButton');
    return page.posts;
  },

  notes_import_fails: async (page) => {
    page.replies['/api/recipes/bulk-import'] = { status: 400, body: { error: 'Too many recipes in one import (the limit is 25)' } };
    await page.previewNotes([note(1), note(2)], 25, 0, 'my notes');
    await page.click('importButton');
    return page.view();
  },

  notes_import_saves_nothing_new: async (page) => {
    page.replies['/api/recipes/bulk-import'] = { status: 200, body: { recipe_ids: [] } };
    await page.previewNotes([note(1)], 25, 0, 'my notes');
    await page.click('importButton');
    return page.view();
  },

  notes_box_empty: async (page) => {
    await page.click('notesPreviewButton');
    const nothing = page.view();
    await page.preview(reels(3), 25);
    page.el('notesInput').value = '  \n ';
    await page.click('notesPreviewButton');
    return { nothing, whitespace: page.view(), posts: page.posts };
  },

  notes_preview_fails: async (page) => {
    page.replies['/api/recipes/notes-preview'] = { status: 422, body: { error: 'Nothing in these notes can be imported.' } };
    page.typeNotes('buy butter');
    await page.click('notesPreviewButton');
    const failed = page.view();
    await page.previewNotes([note(1)], 25, 0, 'buy butter and more');
    return { failed, retried: page.view() };
  },

  notes_preview_error_is_text: async (page) => {
    page.replies['/api/recipes/notes-preview'] = { status: 422, body: { error: '<img src=x onerror=alert(1)>' } };
    page.typeNotes('buy butter');
    await page.click('notesPreviewButton');
    return page.view();
  },

  a_failed_notes_preview_clears_the_one_before: async (page) => {
    await page.previewNotes([note(1)], 25, 0);
    page.replies['/api/recipes/notes-preview'] = { status: 500, body: { error: 'Something went wrong. Try again.' } };
    await page.click('notesPreviewButton');
    return page.view();
  },

  note_rows_are_text_not_html: async (page) => {
    const text = '<b>x</b> "quoted" ' + 'y'.repeat(400);
    await page.previewNotes([{ kind: 'note', text, title: '<img src=x onerror=alert(1)>', url: '', platform: 'notes' }], 25, 0);
    return page.view();
  },

  editing_the_notes_clears_the_preview: async (page) => {
    await page.previewNotes(notes(2), 25, 2, 'my notes');
    page.typeNotes('my notes, edited');
    return page.view();
  },

  busy_notes_preview: async (page) => {
    let answer;
    page.replies['/api/recipes/notes-preview'] = {
      status: 200, body: { limit: 25, links: [note(1)], skipped: 0 }, wait: new Promise((resolve) => { answer = resolve; }),
    };
    page.typeNotes('my notes');
    const waiting = page.click('notesPreviewButton');
    await page.settle();
    const during = page.view();
    await page.click('notesPreviewButton');
    await page.call('previewNotes()');
    await page.click('previewButton');
    answer();
    await waiting;
    return { during, posts: page.posts, after: page.view() };
  },

  notes_already_saved: async (page) => {
    page.replies['/api/recipes/bulk-import'] = { status: 200, body: { recipe_ids: [1] } };
    await page.previewNotes(withSaved(notes(3), 2), 25, 0);
    const view = page.view();
    await page.click('importButton');
    return { view, posts: page.posts };
  },

  a_long_list_of_notes: async (page) => {
    page.replies['/api/recipes/bulk-import'] = { status: 200, body: { recipe_ids: [1] } };
    await page.previewNotes(notes(30), 25, 0);
    const start = page.view();
    await page.click('importButton');
    return { start, posts: page.posts };
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


def test_recipes_already_saved_are_marked_unticked_and_locked(screens):
    view = screens["some_already_saved"]["view"]
    assert view["markedSaved"] == [False, True, False, True, False]
    assert view["ticked"] == [True, False, True, False, True]
    assert view["locked"] == [False, True, False, True, False]
    assert "import-saved" in view["listHtml"]


def test_the_summary_says_how_many_are_already_saved_and_only_the_new_ones_are_counted(screens):
    view = screens["some_already_saved"]["view"]
    assert view["summary"] == "Found 5 recipes. 2 already saved."
    assert view["importLabel"] == "Import 3 recipes"
    assert view["importDisabled"] is False
    assert view["selectAllLabel"] == "Select all"


def test_only_the_new_recipes_are_sent_to_the_import(screens):
    posts = screens["some_already_saved"]["posts"]
    assert posts[1]["body"] == {"links": [reel(1), reel(3), reel(5)]}


def test_saved_recipes_do_not_use_up_the_limit(screens):
    start = screens["saved_ones_do_not_count_toward_the_limit"]["start"]
    assert start["ticked"] == [False] * 10 + [True] * 25 + [False] * 5
    assert start["importLabel"] == "Import 25 recipes"
    assert start["summary"].startswith("Found 40 recipes. 10 already saved. You can import 25 at a time")
    assert start["selectAllLabel"] == "Select first 25"


def test_select_all_skips_the_saved_recipes_too(screens):
    again = screens["saved_ones_do_not_count_toward_the_limit"]["again"]
    assert again["ticked"] == [False] * 10 + [True] * 25 + [False] * 5


def test_exactly_as_many_recipes_as_one_import_takes_is_not_a_long_list(screens):
    view = screens["exactly_one_import_worth"]
    assert view["ticked"] == [True] * 25
    assert view["summary"] == "Found 25 recipes."
    assert view["selectAllLabel"] == "Select all"
    assert view["importDisabled"] is False


def test_when_the_new_recipes_fit_in_one_import_there_is_no_limit_message(screens):
    view = screens["few_enough_new_ones_for_one_import"]
    assert view["ticked"] == [False] * 20 + [True] * 20
    assert view["summary"] == "Found 40 recipes. 20 already saved."
    assert view["selectAllLabel"] == "Select all"
    assert view["importLabel"] == "Import 20 recipes"


def test_when_everything_is_already_saved_there_is_nothing_to_import(screens):
    view = screens["everything_already_saved"]
    assert view["summary"] == "Found 3 recipes. 3 already saved. There is nothing new to import."
    assert view["ticked"] == [False, False, False]
    assert view["importLabel"] == "Import 0 recipes"
    assert view["importDisabled"] is True


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
    assert "Nothing new was saved. Those recipes are already in your list." in view["message"]
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


# ---------- notes pasted into the box ----------

NOTES_PREVIEW = "/api/recipes/notes-preview"


def note_text(i):
    return f"Recipe {i}\nIngredients and steps for recipe {i}."


def test_the_import_box_has_a_button_for_previewing_notes_and_a_box_to_paste_them_in():
    page = PAGE.read_text(encoding="utf-8")
    assert re.search(r'<button id="notesPreviewButton"[^>]*>Preview notes</button>', page)
    box = re.search(r'<textarea id="notesInput"[^>]*>', page).group(0)
    assert "Paste your notes here." in box
    assert "Put a line with --- between one note and the next." in box


def test_the_import_box_explains_how_notes_are_read():
    page = PAGE.read_text(encoding="utf-8")
    help_text = re.search(r"<p[^>]*>(Notes: [^<]*)</p>", page).group(1)
    assert help_text.startswith("Notes: paste them into the box and press Preview notes.")
    assert "Put a line with --- between one note and the next." in help_text
    assert "A note with a TikTok or Instagram link and a few words is imported as that link." in help_text
    assert "A note with a whole recipe written out (at least 80 characters) is saved as it is, with or without a link" in help_text
    assert "A note with several links is read as a list of links, and a note with neither is left out." in help_text


def test_pasted_notes_are_sent_to_the_notes_preview_as_json(screens):
    posts = screens["notes_listed"]["posts"]
    assert posts == [{"url": NOTES_PREVIEW, "method": "POST", "headers": {"Content-Type": "application/json"}, "body": {"text": "my notes"}}]


def test_every_note_and_link_in_the_notes_is_listed_and_starts_ticked(screens):
    view = screens["notes_listed"]["view"]
    assert view["panel"] == "block"
    assert view["urls"] == [reel(1), "Recipe 1", "Recipe 2"]
    assert view["ticked"] == [True, True, True]
    assert view["summary"] == "Found 3 recipes."
    assert view["importLabel"] == "Import 3 recipes"
    assert view["message"] == ""


def test_a_note_is_marked_as_a_note_and_a_link_by_its_platform(screens):
    pills = re.findall(r'<span class="status-tag status-pending">([^<]*)</span>', screens["notes_listed"]["view"]["listHtml"])
    assert pills == ["instagram", "note", "note"]


def test_the_notes_stay_in_the_box_after_previewing(screens):
    assert screens["notes_listed"]["view"]["notesText"] == "my notes"


def test_the_summary_says_how_many_notes_were_left_out(screens):
    why = "since a note needs a TikTok or Instagram link or a whole recipe written out."
    assert screens["notes_left_out"]["one"]["summary"] == f"Found 1 recipe. 1 note was left out, {why}"
    assert screens["notes_left_out"]["three"]["summary"] == f"Found 1 recipe. 3 notes were left out, {why}"
    assert screens["notes_left_out"]["none"]["summary"] == "Found 1 recipe."


def test_the_notes_that_were_left_out_are_forgotten_when_the_preview_is_cleared(screens):
    assert "left out" not in screens["editing_the_notes_clears_the_preview"]["summary"]


def test_the_ticked_notes_and_links_are_sent_apart_to_the_import(screens):
    result = screens["notes_import_chosen"]
    assert [post["url"] for post in result["posts"]] == [NOTES_PREVIEW, IMPORT]
    assert result["posts"][1]["method"] == "POST"
    assert result["posts"][1]["headers"] == {"Content-Type": "application/json"}
    assert result["posts"][1]["body"] == {"links": [reel(1)], "notes": [note_text(2)]}


def test_only_notes_are_sent_with_an_empty_list_of_links(screens):
    assert screens["notes_import_only_notes"][1]["body"] == {"links": [], "notes": [note_text(1), note_text(2)]}


def test_after_importing_notes_the_box_and_the_page_move_on(screens):
    view = screens["notes_import_chosen"]["view"]
    assert view["location"] == "/bulk-review?ids=5,6"
    assert view["notesText"] == ""
    assert view["chosenFile"] == ""
    assert view["panel"] == "none"


def test_when_importing_notes_saves_nothing_new_the_box_is_emptied_and_the_page_stays(screens):
    view = screens["notes_import_saves_nothing_new"]
    assert "Nothing new was saved" in view["message"]
    assert view["notesText"] == ""
    assert view["location"] is None


def test_a_failed_import_of_notes_keeps_the_notes_and_the_list(screens):
    view = screens["notes_import_fails"]
    assert "Too many recipes in one import (the limit is 25)" in view["message"]
    assert view["notesText"] == "my notes"
    assert view["ticked"] == [True, True]
    assert view["importDisabled"] is False


def test_pressing_preview_notes_with_nothing_pasted_asks_for_notes_and_sends_nothing(screens):
    result = screens["notes_box_empty"]
    for view in (result["nothing"], result["whitespace"]):
        assert "Paste your notes first." in view["message"]
        assert view["panel"] == "none"
    assert len(result["posts"]) == 1


def test_pressing_preview_notes_with_nothing_pasted_also_clears_the_list_before(screens):
    whitespace = screens["notes_box_empty"]["whitespace"]
    assert whitespace["urls"] == []
    assert whitespace["importDisabled"] is True


def test_notes_that_cannot_be_previewed_say_why_and_show_no_list(screens):
    failed = screens["notes_preview_fails"]["failed"]
    assert "Nothing in these notes can be imported." in failed["message"]
    assert failed["panel"] == "none"
    assert failed["notesText"] == "buy butter"


def test_previewing_notes_again_after_a_failure_works(screens):
    retried = screens["notes_preview_fails"]["retried"]
    assert retried["urls"] == ["Recipe 1"]
    assert retried["message"] == ""


def test_the_message_for_notes_that_cannot_be_previewed_is_text_not_html(screens):
    message = screens["notes_preview_error_is_text"]["message"]
    assert "<img" not in message
    assert "&lt;img src=x onerror=alert(1)&gt;" in message


def test_a_failed_notes_preview_removes_the_list_from_the_one_before(screens):
    view = screens["a_failed_notes_preview_clears_the_one_before"]
    assert view["panel"] == "none"
    assert view["urls"] == []
    assert "Something went wrong" in view["message"]


def test_the_title_and_text_of_a_note_are_shown_as_text_not_html(screens):
    view = screens["note_rows_are_text_not_html"]
    assert "<img" not in view["listHtml"]
    assert "<b>" not in view["listHtml"]
    assert view["urls"] == ["&lt;img src=x onerror=alert(1)&gt;"]


def test_a_note_shows_the_start_of_its_text_when_the_pointer_rests_on_it(screens):
    listed = screens["note_rows_are_text_not_html"]["listHtml"]
    hint = re.search(r'<span class="import-url" title="([^"]*)"', listed).group(1)
    assert html.unescape(hint) == ('<b>x</b> "quoted" ' + "y" * 400)[:300]


def test_changing_the_notes_clears_the_preview_of_the_old_ones(screens):
    view = screens["editing_the_notes_clears_the_preview"]
    assert view["panel"] == "none"
    assert view["urls"] == []
    assert view["summary"] == ""
    assert view["importDisabled"] is True
    assert view["notesText"] == "my notes, edited"


def test_while_notes_are_being_read_both_preview_buttons_are_off_and_nothing_is_sent_twice(screens):
    result = screens["busy_notes_preview"]
    assert result["during"]["previewDisabled"] is True
    assert result["during"]["notesPreviewDisabled"] is True
    assert "Reading your notes" in result["during"]["message"]
    assert len(result["posts"]) == 1
    assert result["after"]["previewDisabled"] is False
    assert result["after"]["notesPreviewDisabled"] is False
    assert result["after"]["urls"] == ["Recipe 1"]


def test_notes_already_saved_are_marked_unticked_and_locked_like_links(screens):
    result = screens["notes_already_saved"]
    view = result["view"]
    assert view["markedSaved"] == [False, True, False]
    assert view["ticked"] == [True, False, True]
    assert view["locked"] == [False, True, False]
    assert view["summary"] == "Found 3 recipes. 1 already saved."
    assert result["posts"][1]["body"] == {"links": [], "notes": [note_text(1), note_text(3)]}


def test_a_long_list_of_notes_is_limited_like_a_long_list_of_links(screens):
    result = screens["a_long_list_of_notes"]
    assert result["start"]["ticked"] == [True] * 25 + [False] * 5
    assert "You can import 25 at a time, so the first 25 are ticked." in result["start"]["summary"]
    assert result["posts"][1]["body"] == {"links": [], "notes": [note_text(i) for i in range(1, 26)]}


def test_the_notes_are_sent_exactly_as_they_were_typed(screens):
    assert screens["notes_sent_as_typed"][0]["body"] == {"text": "\n  my notes  \n"}

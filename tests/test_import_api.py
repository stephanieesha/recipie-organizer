"""
The bulk import as the page uses it: a file goes up, links come out as saved recipes. Each case
goes through the real routes with a temporary database, and TikTok is never contacted.
"""

import io
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import app as app_module  # noqa: E402
import db  # noqa: E402
import limits  # noqa: E402
from import_parser import NO_FAVORITES, NO_LINKS, NO_POSTS, TIKTOK_TEXT_FILE  # noqa: E402
from notes_parser import NOTHING_TO_IMPORT  # noqa: E402
from recipe_extractor import ExtractionError, NoRecipeFoundError  # noqa: E402
from tiktok_oembed import TikTokFetchError  # noqa: E402

REEL = "https://www.instagram.com/reel/DQ6rx2JDxFR/"
POST = "https://www.instagram.com/p/fA9uwTtkSN/"
TV = "https://www.instagram.com/tv/CxYz123abc/"
PROFILE = "https://www.instagram.com/chef_one/"
TIKTOK = "https://www.tiktok.com/@chef/video/7123456789"


@pytest.fixture
def client(monkeypatch):
    for name in ("WRITE_LIMIT_PER_MINUTE", "AUTH_LIMIT_PER_15_MIN", "DAILY_SIGNUP_LIMIT", "DAILY_AI_LIMIT", "MAX_BULK_LINKS"):
        monkeypatch.delenv(name, raising=False)
    limits._recent_requests.clear()
    limits._recent_auth_attempts.clear()

    def tiktok_unavailable(url):
        raise TikTokFetchError("not reachable in tests")

    monkeypatch.setattr(app_module, "fetch_tiktok_data", tiktok_unavailable)

    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(db, "DB_PATH", Path(tmpdir) / "test.db")
        db.init_db()
        app_module.app.config["TESTING"] = True
        test_client = app_module.app.test_client()
        test_client.post("/signup", data={"email": "cook@example.com", "password": "correct-horse"})
        yield test_client


@pytest.fixture
def other_client(client):
    """A second person with an account of their own."""
    other = app_module.app.test_client()
    other.post("/signup", data={"email": "other@example.com", "password": "correct-horse"})
    return other


def saved_posts_json(*hrefs):
    entries = [
        {"title": f"chef_{i}", "string_map_data": {"Saved on": {"href": href, "timestamp": 1700000000 + i}}}
        for i, href in enumerate(hrefs)
    ]
    return json.dumps({"saved_saved_media": entries}, indent=2)


def upload(client, content, name="saved_posts.json"):
    data = content.encode() if isinstance(content, str) else content
    return client.post(
        "/api/recipes/bulk-import",
        data={"file": (io.BytesIO(data), name)},
        content_type="multipart/form-data",
    )


def saved_urls(client):
    recipes = client.get("/api/recipes").get_json()
    return [r["source_url"] for r in sorted(recipes, key=lambda r: r["id"])]


# ---------- Instagram's saved posts ----------

def test_saved_posts_json_saves_each_post_as_a_recipe_waiting_for_its_caption(client):
    response = upload(client, saved_posts_json(REEL, POST, TV))
    summary = response.get_json()

    assert response.status_code == 200
    assert summary["total_found"] == 3
    assert summary["needs_caption"] == 3
    assert len(summary["recipe_ids"]) == 3
    assert saved_urls(client) == [REEL, POST, TV]
    assert {r["platform"] for r in client.get("/api/recipes").get_json()} == {"instagram"}


def test_the_html_version_of_the_export_works_too(client):
    html_export = (
        f'<a target="_blank" href="{REEL}">{REEL}</a><br>'
        f'<a target="_blank" href="{POST}">{POST}</a><a href="{PROFILE}">chef_one</a>'
    )
    summary = upload(client, html_export, "saved_posts.html").get_json()
    assert summary["total_found"] == 2
    assert saved_urls(client) == [REEL, POST]


def test_profile_links_in_the_file_are_not_saved_as_recipes(client):
    summary = upload(client, saved_posts_json(REEL, PROFILE, POST)).get_json()
    assert summary["total_found"] == 2
    assert saved_urls(client) == [REEL, POST]


def test_a_post_listed_twice_is_saved_once(client):
    upload(client, saved_posts_json(REEL, POST, REEL))
    assert saved_urls(client) == [REEL, POST]


def test_a_file_that_is_not_valid_utf8_is_still_read(client):
    content = "caf\u00e9 notes\n".encode("latin-1") + REEL.encode() + b"\n"
    summary = upload(client, content, "links.txt").get_json()
    assert summary["total_found"] == 1
    assert saved_urls(client) == [REEL]


def test_instagram_and_tiktok_links_in_one_text_file(client):
    summary = upload(client, f"{REEL}\n{TIKTOK}\n", "links.txt").get_json()
    assert summary["total_found"] == 2
    assert summary["needs_caption"] == 1  # the Instagram post
    assert summary["needs_manual"] == 1   # TikTok could not be reached, so the link waits for manual entry
    assert saved_urls(client) == [REEL, TIKTOK]


# ---------- files that cannot be imported ----------

def test_a_file_with_no_links_is_explained_and_nothing_is_saved(client):
    response = upload(client, '{"name": "chef"}')
    assert response.status_code == 422
    assert response.get_json() == {"error": NO_LINKS}
    assert saved_urls(client) == []


def test_a_file_with_only_profile_links_is_explained_and_nothing_is_saved(client):
    response = upload(client, saved_posts_json(PROFILE))
    assert response.status_code == 422
    assert response.get_json() == {"error": NO_POSTS}
    assert saved_urls(client) == []


def test_an_empty_file_is_explained(client):
    response = upload(client, "")
    assert response.status_code == 422
    assert "empty" in response.get_json()["error"]


def test_no_file_and_no_file_chosen_are_both_refused(client):
    assert client.post("/api/recipes/bulk-import", data={}, content_type="multipart/form-data").status_code == 400
    blank = client.post("/api/recipes/bulk-import", data={"file": (io.BytesIO(b"x"), "")}, content_type="multipart/form-data")
    assert blank.status_code == 400


def test_too_many_links_in_one_file_are_refused_before_anything_is_saved(client, monkeypatch):
    monkeypatch.setenv("MAX_BULK_LINKS", "2")
    response = upload(client, saved_posts_json(REEL, POST, TV))
    assert response.status_code == 400
    assert "the limit is 2" in response.get_json()["error"]
    assert saved_urls(client) == []


def test_a_file_with_exactly_the_most_links_allowed_is_accepted(client, monkeypatch):
    monkeypatch.setenv("MAX_BULK_LINKS", "3")
    assert upload(client, saved_posts_json(REEL, POST, TV)).status_code == 200
    assert saved_urls(client) == [REEL, POST, TV]


def test_a_file_over_the_size_limit_is_refused_with_a_plain_message(client, monkeypatch):
    monkeypatch.setitem(app_module.app.config, "MAX_CONTENT_LENGTH", 2000)
    response = upload(client, saved_posts_json(REEL) + " " * 5000)
    assert response.status_code == 413
    assert "too big" in response.get_json()["error"]
    assert "50 MB" in response.get_json()["error"]
    assert saved_urls(client) == []


def test_a_file_just_under_the_size_limit_is_accepted(client, monkeypatch):
    content = saved_posts_json(REEL)
    monkeypatch.setitem(app_module.app.config, "MAX_CONTENT_LENGTH", len(content) + 1000)
    assert upload(client, content).status_code == 200


def test_the_upload_limit_is_fifty_megabytes():
    assert app_module.MAX_UPLOAD_BYTES == 50 * 1024 * 1024
    assert app_module.app.config["MAX_CONTENT_LENGTH"] == app_module.MAX_UPLOAD_BYTES


# ---------- TikTok's data download ----------

def share_link(video_id):
    return f"https://www.tiktokv.com/share/video/{video_id}/"


FAVORITES = [share_link(7100000000000000001 + i) for i in range(3)]
LIKES = [share_link(7200000000000000001 + i) for i in range(2)]
HISTORY = [share_link(7300000000000000001 + i) for i in range(4)]


def tiktok_data(favorites, likes=(), history=()):
    def entries(links):
        return [{"Date": "2023-05-01 10:00:00", "Link": link} for link in links]

    return json.dumps({"Activity": {
        "Favorite Videos": {"FavoriteVideoList": entries(favorites)},
        "Like List": {"ItemFavoriteList": entries(likes)},
        "Video Browsing History": {"VideoList": entries(history)},
    }}, indent=2)


def test_only_the_favorites_in_a_tiktok_data_file_are_saved(client):
    summary = upload(client, tiktok_data(FAVORITES, LIKES, HISTORY), "user_data.json").get_json()
    assert summary["total_found"] == 3
    assert saved_urls(client) == FAVORITES
    assert {r["platform"] for r in client.get("/api/recipes").get_json()} == {"tiktok"}


def test_each_favorite_is_looked_up_and_its_recipe_filled_in(client, monkeypatch):
    looked_up = []

    def fake_lookup(url):
        looked_up.append(url)
        return {"caption": "Garlic bread: butter, garlic, bread", "thumbnail_url": "https://example.com/cover.jpg"}

    def fake_extraction(caption, kind):
        return {"title": "Garlic bread", "ingredients": ["butter", "garlic", "bread"], "directions": ["Mix", "Bake"]}

    monkeypatch.setattr(app_module, "fetch_tiktok_data", fake_lookup)
    monkeypatch.setattr(app_module, "extract_recipe", fake_extraction)

    summary = upload(client, tiktok_data(FAVORITES, LIKES, HISTORY), "user_data.json").get_json()

    assert summary["extracted"] == 3
    assert looked_up == FAVORITES  # the links as the file has them; the lookup works out the web link itself
    recipes = client.get("/api/recipes").get_json()
    assert {r["title"] for r in recipes} == {"Garlic bread"}
    assert {r["thumbnail_url"] for r in recipes} == {"https://example.com/cover.jpg"}


def test_a_tiktok_data_file_without_favorites_is_explained_and_nothing_is_saved(client):
    response = upload(client, tiktok_data([], LIKES, HISTORY), "user_data.json")
    assert response.status_code == 422
    assert response.get_json() == {"error": NO_FAVORITES}
    assert saved_urls(client) == []


def test_a_tiktok_data_file_in_text_form_is_explained_and_nothing_is_saved(client):
    text = "Video Browsing History\nLink: " + HISTORY[0] + "\n"
    response = upload(client, text, "user_data.txt")
    assert response.status_code == 422
    assert response.get_json() == {"error": TIKTOK_TEXT_FILE}
    assert saved_urls(client) == []


def test_a_tiktok_link_that_is_not_a_video_is_not_saved(client):
    summary = upload(client, f"https://www.tiktok.com/@chef\n{FAVORITES[0]}\nhttps://www.tiktok.com/tag/jollof\n", "links.txt").get_json()
    assert summary["total_found"] == 1
    assert saved_urls(client) == [FAVORITES[0]]


# ---------- the preview, and importing what was ticked on it ----------

def preview(client, content, name="saved_posts.json"):
    data = content.encode() if isinstance(content, str) else content
    return client.post(
        "/api/recipes/import-preview",
        data={"file": (io.BytesIO(data), name)},
        content_type="multipart/form-data",
    )


def import_chosen(client, links):
    return client.post("/api/recipes/bulk-import", json={"links": links})


def send_json(client, body):
    return client.post("/api/recipes/bulk-import", data=json.dumps(body), content_type="application/json")


def test_the_preview_lists_the_recipes_in_a_file_and_saves_nothing(client):
    response = preview(client, saved_posts_json(REEL, PROFILE, POST, REEL))
    assert response.status_code == 200
    assert response.get_json()["links"] == [
        {"url": REEL, "platform": "instagram", "already_saved": False},
        {"url": POST, "platform": "instagram", "already_saved": False},
    ]
    assert saved_urls(client) == []


def test_the_preview_of_a_tiktok_file_lists_only_the_favorites_and_looks_nothing_up(client, monkeypatch):
    calls = []
    monkeypatch.setattr(app_module, "fetch_tiktok_data", lambda url: calls.append(url))
    monkeypatch.setattr(app_module, "extract_recipe", lambda caption, kind: calls.append(caption))

    response = preview(client, tiktok_data(FAVORITES, LIKES, HISTORY), "user_data.json")

    assert response.status_code == 200
    assert [link["url"] for link in response.get_json()["links"]] == FAVORITES
    assert {link["platform"] for link in response.get_json()["links"]} == {"tiktok"}
    assert calls == []
    assert saved_urls(client) == []


def test_the_preview_says_how_many_can_be_imported_at_once_and_still_lists_them_all(client, monkeypatch):
    monkeypatch.setenv("MAX_BULK_LINKS", "2")
    body = preview(client, saved_posts_json(REEL, POST, TV)).get_json()
    assert body["limit"] == 2
    assert [link["url"] for link in body["links"]] == [REEL, POST, TV]


def test_the_preview_has_a_limit_of_zero_when_no_limit_is_set(client):
    assert preview(client, saved_posts_json(REEL)).get_json()["limit"] == 0


@pytest.mark.parametrize("content,name,error", [
    ('{"name": "chef"}', "saved_posts.json", NO_LINKS),
    (saved_posts_json(PROFILE), "saved_posts.json", NO_POSTS),
    ("", "saved_posts.json", "This file is empty."),
    (tiktok_data([], LIKES, HISTORY), "user_data.json", NO_FAVORITES),
    ("Video Browsing History\nLink: " + HISTORY[0] + "\n", "user_data.txt", TIKTOK_TEXT_FILE),
])
def test_a_file_with_nothing_to_import_is_explained_by_the_preview(client, content, name, error):
    response = preview(client, content, name)
    assert response.status_code == 422
    assert response.get_json() == {"error": error}


def test_the_preview_needs_a_file(client):
    missing = client.post("/api/recipes/import-preview", data={}, content_type="multipart/form-data")
    blank = client.post("/api/recipes/import-preview", data={"file": (io.BytesIO(b"x"), "")}, content_type="multipart/form-data")
    assert (missing.status_code, missing.get_json()) == (400, {"error": "No file uploaded"})
    assert (blank.status_code, blank.get_json()) == (400, {"error": "No file selected"})


def test_a_file_over_the_size_limit_is_refused_by_the_preview_too(client, monkeypatch):
    monkeypatch.setitem(app_module.app.config, "MAX_CONTENT_LENGTH", 2000)
    response = preview(client, saved_posts_json(REEL) + " " * 5000)
    assert response.status_code == 413
    assert "50 MB" in response.get_json()["error"]


def test_only_the_links_that_were_ticked_are_saved_in_the_order_given(client):
    response = import_chosen(client, [TV, REEL])
    summary = response.get_json()
    assert response.status_code == 200
    assert summary["total_found"] == 2
    assert summary["needs_caption"] == 2
    assert summary["recipe_ids"] == sorted(summary["recipe_ids"]) and len(summary["recipe_ids"]) == 2
    assert saved_urls(client) == [TV, REEL]


def test_a_link_chosen_twice_is_saved_once(client):
    summary = import_chosen(client, [REEL, POST, REEL]).get_json()
    assert summary["total_found"] == 2
    assert saved_urls(client) == [REEL, POST]


def test_chosen_tiktok_videos_are_looked_up_and_filled_in(client, monkeypatch):
    looked_up = []

    def fake_lookup(url):
        looked_up.append(url)
        return {"caption": "Garlic bread: butter, garlic, bread", "thumbnail_url": "https://example.com/cover.jpg"}

    monkeypatch.setattr(app_module, "fetch_tiktok_data", fake_lookup)
    monkeypatch.setattr(app_module, "extract_recipe", lambda caption, kind: {"title": "Garlic bread", "ingredients": ["butter"], "directions": ["Bake"]})

    summary = import_chosen(client, FAVORITES[:2]).get_json()

    assert summary["extracted"] == 2
    assert looked_up == FAVORITES[:2]
    assert {r["title"] for r in client.get("/api/recipes").get_json()} == {"Garlic bread"}


def test_a_tiktok_video_that_cannot_be_looked_up_is_still_saved_for_manual_entry(client):
    summary = import_chosen(client, [FAVORITES[0], REEL]).get_json()
    assert summary["needs_manual"] == 1
    assert summary["needs_caption"] == 1
    assert saved_urls(client) == [FAVORITES[0], REEL]


def test_the_chosen_recipes_belong_to_the_person_who_imported_them(client, other_client):
    import_chosen(client, [REEL])
    assert other_client.get("/api/recipes").get_json() == []
    assert saved_urls(client) == [REEL]


def test_more_chosen_links_than_the_limit_are_refused_and_nothing_is_saved(client, monkeypatch):
    monkeypatch.setenv("MAX_BULK_LINKS", "2")
    response = import_chosen(client, [REEL, POST, TV])
    assert response.status_code == 400
    assert "the limit is 2" in response.get_json()["error"]
    assert saved_urls(client) == []


def test_exactly_the_limit_of_chosen_links_is_accepted(client, monkeypatch):
    monkeypatch.setenv("MAX_BULK_LINKS", "3")
    assert import_chosen(client, [REEL, POST, TV]).status_code == 200
    assert saved_urls(client) == [REEL, POST, TV]


def test_the_limit_counts_a_link_chosen_twice_once(client, monkeypatch):
    monkeypatch.setenv("MAX_BULK_LINKS", "2")
    assert import_chosen(client, [REEL, REEL, POST]).status_code == 200
    assert saved_urls(client) == [REEL, POST]


@pytest.mark.parametrize("body", [
    {}, {"links": []}, {"links": None}, {"links": REEL}, {"links": {"url": REEL}}, {"other": [REEL]},
    [REEL], None, "text", 5,
])
def test_a_request_that_chooses_no_recipes_is_refused(client, body):
    response = send_json(client, body)
    assert response.status_code == 400
    assert response.get_json() == {"error": "Choose at least one recipe to import"}
    assert saved_urls(client) == []


def test_a_request_that_is_not_valid_json_is_refused(client):
    response = client.post("/api/recipes/bulk-import", data="{oops", content_type="application/json")
    assert response.status_code == 400
    assert response.get_json() == {"error": "Choose at least one recipe to import"}


@pytest.mark.parametrize("bad", [
    PROFILE,
    "https://www.tiktok.com/@chef",
    "https://example.com/reel/abc123/",
    "https://www.instagram.com.evil.example/reel/abc123/",
    "javascript:alert(1)",
    "not a link",
    "",
    REEL + " and some more text",
    REEL + " " + POST,
    " " + REEL,
    REEL + "\n",
    REEL + ",",
    "www.instagram.com/reel/abc123/",
    123,
    None,
    [REEL],
    {"url": REEL},
], ids=repr)
def test_a_chosen_link_that_is_not_exactly_one_post_link_refuses_the_whole_request(client, bad):
    response = import_chosen(client, [REEL, bad])
    assert response.status_code == 400
    assert response.get_json() == {"error": "One of the chosen links is not a TikTok or Instagram post, reel or video"}
    assert saved_urls(client) == []


ROUND_TRIP_FILES = [
    pytest.param(saved_posts_json(REEL, POST, TV), "saved_posts.json", id="instagram json"),
    pytest.param(f'<a href="{REEL}?igsh=abc&amp;utm=1">x</a><a href="{POST}">y</a>', "saved_posts.html", id="html with entities"),
    pytest.param(json.dumps({"saved": [REEL, POST]}).replace("/", "\\/"), "saved_posts.json", id="json with escaped slashes"),
    pytest.param("www.instagram.com/reel/ABC123/,\n" + TIKTOK + ".\n(" + POST + ")\n", "links.txt", id="bare and punctuated links"),
    pytest.param(tiktok_data(FAVORITES, LIKES, HISTORY), "user_data.json", id="tiktok favorites"),
]


@pytest.mark.parametrize("content,name", ROUND_TRIP_FILES)
def test_every_link_the_preview_lists_can_be_imported(client, content, name):
    listed = [link["url"] for link in preview(client, content, name).get_json()["links"]]
    assert listed
    assert import_chosen(client, listed).status_code == 200
    assert saved_urls(client) == listed


# ---------- recipes that are already saved ----------

def another_way(link):
    """The same Instagram post written differently: /p/ instead of /reel/, with tracking added."""
    return link.replace("/reel/", "/p/").replace("/tv/", "/p/") + "?igsh=MXx4eWx"


def test_the_preview_marks_the_posts_already_saved_even_when_the_file_writes_them_another_way(client):
    import_chosen(client, [REEL])
    listed = preview(client, saved_posts_json(another_way(REEL), POST, TV)).get_json()["links"]
    assert [(link["url"], link["already_saved"]) for link in listed] == [
        (another_way(REEL), True), (POST, False), (TV, False),
    ]
    assert saved_urls(client) == [REEL]


def test_the_preview_marks_posts_saved_by_pasting_a_link_too(client):
    client.post("/api/recipes", json={"url": POST})
    listed = preview(client, saved_posts_json(REEL, POST)).get_json()["links"]
    assert [link["already_saved"] for link in listed] == [False, True]


def test_the_preview_does_not_mark_posts_that_only_someone_else_saved(client, other_client):
    import_chosen(other_client, [REEL])
    assert preview(client, saved_posts_json(REEL)).get_json()["links"][0]["already_saved"] is False


def test_a_post_that_is_already_saved_is_skipped_and_the_rest_are_saved(client):
    first = import_chosen(client, [REEL]).get_json()["recipe_ids"]
    summary = import_chosen(client, [REEL, POST, TV]).get_json()
    assert summary["total_found"] == 3
    assert summary["already_saved"] == 1
    assert summary["needs_caption"] == 2
    assert len(summary["recipe_ids"]) == 2
    assert first[0] not in summary["recipe_ids"]
    assert saved_urls(client) == [REEL, POST, TV]


def test_a_post_already_saved_under_another_link_is_skipped(client):
    import_chosen(client, [REEL])
    summary = import_chosen(client, [another_way(REEL)]).get_json()
    assert summary["already_saved"] == 1
    assert summary["recipe_ids"] == []
    assert saved_urls(client) == [REEL]


def test_a_post_saved_by_pasting_its_link_is_skipped_by_the_import(client):
    client.post("/api/recipes", json={"url": REEL})
    summary = import_chosen(client, [REEL, POST]).get_json()
    assert summary["already_saved"] == 1
    assert saved_urls(client) == [REEL, POST]


def test_the_same_post_written_two_ways_in_one_import_is_saved_once(client):
    summary = import_chosen(client, [REEL, another_way(REEL)]).get_json()
    assert summary["already_saved"] == 1
    assert len(summary["recipe_ids"]) == 1
    assert saved_urls(client) == [REEL]


def test_importing_the_same_file_again_saves_nothing_new(client):
    content = saved_posts_json(REEL, POST, TV)
    upload(client, content)
    again = upload(client, content).get_json()
    assert again["already_saved"] == 3
    assert again["recipe_ids"] == []
    assert again["needs_caption"] == 0
    assert saved_urls(client) == [REEL, POST, TV]


def test_a_tiktok_video_already_saved_is_not_looked_up_again(client, monkeypatch):
    looked_up = []

    def unreachable(url):
        looked_up.append(url)
        raise TikTokFetchError("not reachable in tests")

    monkeypatch.setattr(app_module, "fetch_tiktok_data", unreachable)
    import_chosen(client, [FAVORITES[0]])
    looked_up.clear()

    address_bar_link = "https://www.tiktok.com/@chef/video/7100000000000000001"
    summary = import_chosen(client, [FAVORITES[0], address_bar_link, FAVORITES[1]]).get_json()

    assert summary["already_saved"] == 2
    assert looked_up == [FAVORITES[1]]
    assert saved_urls(client) == [FAVORITES[0], FAVORITES[1]]


def test_a_removed_recipe_can_be_imported_again(client):
    recipe_id = import_chosen(client, [REEL]).get_json()["recipe_ids"][0]
    client.delete(f"/api/recipes/{recipe_id}")
    summary = import_chosen(client, [REEL]).get_json()
    assert summary["already_saved"] == 0
    assert len(summary["recipe_ids"]) == 1
    assert saved_urls(client) == [REEL]


def test_a_post_only_someone_else_saved_is_saved_for_you_too(client, other_client):
    import_chosen(other_client, [REEL])
    summary = import_chosen(client, [REEL]).get_json()
    assert summary["already_saved"] == 0
    assert saved_urls(client) == [REEL]


def test_a_file_in_which_every_post_is_saved_already_is_still_a_normal_answer(client):
    import_chosen(client, [REEL, POST])
    response = import_chosen(client, [POST, REEL])
    assert response.status_code == 200
    assert response.get_json()["already_saved"] == 2
    assert response.get_json()["recipe_ids"] == []


# ---------- notes: pasted, previewed, and imported ----------

NOTE = (
    "Garlic noodles\n\n"
    "Ingredients: 200g noodles, 4 cloves garlic, 2 tbsp soy sauce, 2 tbsp butter\n"
    "Boil the noodles. Fry the garlic in the butter, add the soy sauce and toss it all together."
)
OTHER_NOTE = NOTE.replace("Garlic noodles", "Chili noodles")
NOT_ONE_NOTE = "One of the chosen notes is not a single recipe written out"


@pytest.fixture
def reading(monkeypatch):
    """A stand-in for the model. It records what it was given, and reads every recipe as Pancakes."""
    given = []

    def read(text, kind):
        given.append((text, kind))
        return {"title": "Pancakes", "ingredients": ["flour", "eggs"], "directions": ["Mix", "Fry"]}

    monkeypatch.setattr(app_module, "extract_recipe", read)
    return given


def preview_notes(client, text):
    return client.post("/api/recipes/notes-preview", json={"text": text})


def import_notes(client, notes, links=None):
    body = {"notes": notes}
    if links is not None:
        body["links"] = links
    return client.post("/api/recipes/bulk-import", json=body)


def all_recipes(client):
    return sorted(client.get("/api/recipes").get_json(), key=lambda r: r["id"])


def test_the_notes_preview_lists_links_and_recipes_written_out_in_the_order_they_are_written(client):
    text = f"{REEL}\n---\n{NOTE}\n---\n{TIKTOK}\n---\nbuy butter"
    response = preview_notes(client, text)
    assert response.status_code == 200
    assert response.get_json() == {
        "limit": 0,
        "skipped": 1,
        "links": [
            {"url": REEL, "platform": "instagram", "already_saved": False},
            {"kind": "note", "text": NOTE, "title": "Garlic noodles", "url": "", "platform": "notes", "already_saved": False},
            {"url": TIKTOK, "platform": "tiktok", "already_saved": False},
        ],
    }


def test_the_notes_preview_saves_nothing_and_asks_nobody(client, monkeypatch, reading):
    asked = []
    monkeypatch.setattr(app_module, "fetch_tiktok_data", lambda url: asked.append(url))
    assert preview_notes(client, f"{TIKTOK}\n---\n{NOTE}").status_code == 200
    assert asked == [] and reading == []
    assert all_recipes(client) == []


def test_the_notes_preview_says_what_the_import_limit_is(client, monkeypatch):
    monkeypatch.setenv("MAX_BULK_LINKS", "7")
    assert preview_notes(client, REEL).get_json()["limit"] == 7


def test_the_notes_preview_marks_what_is_already_saved(client, reading):
    import_chosen(client, [REEL])
    import_notes(client, [NOTE])
    items = preview_notes(client, f"{REEL}\n---\n{NOTE}\n---\n{OTHER_NOTE}\n---\n{POST}").get_json()["links"]
    assert [item["already_saved"] for item in items] == [True, True, False, False]


def test_a_note_with_its_link_is_marked_saved_when_that_post_is_saved(client):
    import_chosen(client, [TIKTOK])
    text = NOTE + "\n" + TIKTOK
    assert preview_notes(client, text).get_json()["links"] == [
        {"kind": "note", "text": text, "title": "Garlic noodles", "url": TIKTOK, "platform": "tiktok", "already_saved": True},
    ]


def test_another_persons_recipes_do_not_mark_a_note_as_saved(client, other_client, reading):
    import_notes(other_client, [NOTE])
    assert preview_notes(client, NOTE).get_json()["links"][0]["already_saved"] is False


@pytest.mark.parametrize("body", [{}, {"text": ""}, {"text": "  \n "}, {"text": None}, {"text": 5}, {"text": [NOTE]}, [NOTE], None, "text", 5])
def test_the_notes_preview_wants_some_text(client, body):
    response = client.post("/api/recipes/notes-preview", data=json.dumps(body), content_type="application/json")
    assert response.status_code == 400
    assert response.get_json() == {"error": "Paste your notes first"}


def test_the_notes_preview_wants_json(client):
    response = client.post("/api/recipes/notes-preview", data=NOTE, content_type="text/plain")
    assert response.status_code == 400
    assert response.get_json() == {"error": "Paste your notes first"}


@pytest.mark.parametrize("text", ["buy butter", PROFILE, "---", "x" * 6000])
def test_notes_with_nothing_to_import_are_explained(client, text):
    response = preview_notes(client, text)
    assert response.status_code == 422
    assert response.get_json() == {"error": NOTHING_TO_IMPORT}


def test_a_note_is_saved_as_a_recipe_read_by_the_model(client, reading):
    response = import_notes(client, [NOTE])
    assert response.status_code == 200
    summary = response.get_json()
    assert summary == {"total_found": 1, "already_saved": 0, "extracted": 1, "needs_caption": 0, "needs_manual": 0, "recipe_ids": summary["recipe_ids"]}
    assert reading == [(NOTE, "note")]
    (recipe,) = all_recipes(client)
    assert recipe["id"] == summary["recipe_ids"][0]
    assert (recipe["platform"], recipe["source_url"], recipe["status"]) == ("notes", "", "extracted")
    assert (recipe["title"], recipe["ingredients"], recipe["directions"]) == ("Pancakes", ["flour", "eggs"], ["Mix", "Fry"])
    assert recipe["caption_raw"] == NOTE
    assert recipe["thumbnail_url"] is None


def test_a_note_with_the_link_it_came_from_keeps_the_link_and_is_not_looked_up(client, monkeypatch, reading):
    looked_up = []
    monkeypatch.setattr(app_module, "fetch_tiktok_data", lambda url: looked_up.append(url))
    summary = import_notes(client, [NOTE + "\n" + TIKTOK, OTHER_NOTE + "\n" + REEL]).get_json()
    assert looked_up == []
    assert (summary["extracted"], summary["needs_caption"], summary["needs_manual"]) == (2, 0, 0)
    tiktok_note, instagram_note = all_recipes(client)
    assert (tiktok_note["platform"], tiktok_note["source_url"], tiktok_note["caption_raw"]) == ("tiktok", TIKTOK, NOTE + "\n" + TIKTOK)
    assert (instagram_note["platform"], instagram_note["source_url"]) == ("instagram", REEL)
    assert [text for text, kind in reading] == [NOTE + "\n" + TIKTOK, OTHER_NOTE + "\n" + REEL]


def test_links_and_notes_chosen_together_are_all_saved_links_first(client, reading):
    summary = import_notes(client, [NOTE, OTHER_NOTE], links=[REEL, POST]).get_json()
    assert summary["total_found"] == 4
    assert (summary["extracted"], summary["needs_caption"], summary["already_saved"]) == (2, 2, 0)
    assert [r["platform"] for r in all_recipes(client)] == ["instagram", "instagram", "notes", "notes"]
    assert [r["id"] for r in all_recipes(client)] == summary["recipe_ids"]
    assert [text for text, kind in reading] == [NOTE, OTHER_NOTE]


def test_a_note_the_model_finds_no_recipe_in_is_kept_for_filling_in_by_hand(client, monkeypatch):
    def no_recipe(text, kind):
        raise NoRecipeFoundError("This is a shopping list")

    monkeypatch.setattr(app_module, "extract_recipe", no_recipe)
    summary = import_notes(client, [NOTE]).get_json()
    assert (summary["extracted"], summary["needs_manual"]) == (0, 1)
    (recipe,) = all_recipes(client)
    assert (recipe["status"], recipe["title"], recipe["caption_raw"]) == ("needs_manual", "Garlic noodles", NOTE)


def test_a_note_the_model_cannot_be_asked_about_is_kept_for_filling_in_by_hand(client, monkeypatch):
    def unreachable(text, kind):
        raise ExtractionError("Could not reach the extraction service")

    monkeypatch.setattr(app_module, "extract_recipe", unreachable)
    summary = import_notes(client, [NOTE, OTHER_NOTE]).get_json()
    assert (summary["extracted"], summary["needs_manual"]) == (0, 2)
    assert [(r["status"], r["title"]) for r in all_recipes(client)] == [("needs_manual", "Garlic noodles"), ("needs_manual", "Chili noodles")]


def test_without_an_api_key_the_notes_are_kept_for_filling_in_by_hand(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    summary = import_notes(client, [NOTE]).get_json()
    assert (summary["extracted"], summary["needs_manual"]) == (0, 1)
    assert all_recipes(client)[0]["status"] == "needs_manual"


def test_a_note_after_the_daily_limit_is_kept_without_asking_the_model(client, monkeypatch, reading):
    monkeypatch.setenv("DAILY_AI_LIMIT", "1")
    summary = import_notes(client, [NOTE, OTHER_NOTE]).get_json()
    assert (summary["extracted"], summary["needs_manual"]) == (1, 1)
    assert reading == [(NOTE, "note")]
    assert [(r["status"], r["title"]) for r in all_recipes(client)] == [("extracted", "Pancakes"), ("needs_manual", "Chili noodles")]


def test_a_note_saved_before_is_not_saved_or_read_again(client, reading):
    first = import_notes(client, [NOTE]).get_json()["recipe_ids"]
    summary = import_notes(client, [NOTE, OTHER_NOTE]).get_json()
    assert (summary["total_found"], summary["already_saved"], summary["extracted"]) == (2, 1, 1)
    assert len(summary["recipe_ids"]) == 1 and summary["recipe_ids"] != first
    assert reading == [(NOTE, "note"), (OTHER_NOTE, "note")]
    assert len(all_recipes(client)) == 2


def test_a_note_saved_before_is_known_by_its_words_not_its_spacing(client, reading):
    import_notes(client, [NOTE])
    summary = import_notes(client, [NOTE.upper().replace("\n", "\n\n")]).get_json()
    assert (summary["already_saved"], summary["recipe_ids"]) == (1, [])


def test_the_same_note_chosen_twice_is_saved_once_as_it_was_first_chosen(client, reading):
    summary = import_notes(client, [NOTE, NOTE, NOTE.lower()]).get_json()
    assert (summary["total_found"], summary["extracted"], summary["already_saved"]) == (1, 1, 0)
    assert reading == [(NOTE, "note")]
    assert [r["caption_raw"] for r in all_recipes(client)] == [NOTE]


def test_a_note_for_a_post_that_is_already_saved_is_not_saved_again(client, reading):
    import_chosen(client, [TIKTOK])
    summary = import_notes(client, [NOTE + "\n" + TIKTOK]).get_json()
    assert (summary["already_saved"], summary["extracted"], summary["recipe_ids"]) == (1, 0, [])
    assert reading == []


def test_a_link_and_a_note_for_the_same_post_chosen_together_are_one_recipe(client, reading):
    summary = import_notes(client, [NOTE + "\n" + REEL], links=[REEL]).get_json()
    assert (summary["total_found"], summary["needs_caption"], summary["already_saved"], summary["extracted"]) == (2, 1, 1, 0)
    assert len(all_recipes(client)) == 1


def test_the_notes_chosen_belong_to_the_person_who_imported_them(client, other_client, reading):
    import_notes(client, [NOTE])
    assert other_client.get("/api/recipes").get_json() == []
    assert len(all_recipes(client)) == 1


def test_a_note_is_saved_as_the_preview_listed_it(client, reading):
    import_notes(client, ["\n\n  " + NOTE.replace("\n", "\r\n") + "  \n\n"])
    assert all_recipes(client)[0]["caption_raw"] == NOTE
    assert reading == [(NOTE, "note")]


@pytest.mark.parametrize("text", [
    NOTE,
    NOTE + "\n" + TIKTOK,
    "# Chili\r\n" + NOTE.replace("\n", "\r\n") + "\r\n" + REEL,
])
def test_every_note_the_preview_lists_can_be_imported(client, reading, text):
    (item,) = preview_notes(client, text).get_json()["links"]
    assert import_notes(client, [item["text"]]).status_code == 200
    assert len(all_recipes(client)) == 1


def test_more_chosen_recipes_than_the_limit_are_refused_and_nothing_is_saved(client, monkeypatch, reading):
    monkeypatch.setenv("MAX_BULK_LINKS", "2")
    response = import_notes(client, [NOTE, OTHER_NOTE], links=[REEL])
    assert response.status_code == 400
    assert response.get_json() == {"error": "Too many recipes in one import (the limit is 2)"}
    assert all_recipes(client) == [] and reading == []


def test_exactly_the_limit_of_links_and_notes_together_is_accepted(client, monkeypatch, reading):
    monkeypatch.setenv("MAX_BULK_LINKS", "2")
    assert import_notes(client, [NOTE], links=[REEL]).status_code == 200
    assert len(all_recipes(client)) == 2


def test_the_limit_counts_a_note_chosen_twice_once(client, monkeypatch, reading):
    monkeypatch.setenv("MAX_BULK_LINKS", "1")
    assert import_notes(client, [NOTE, NOTE]).status_code == 200


@pytest.mark.parametrize("body", [{"notes": []}, {"notes": None}, {"links": [], "notes": []}, {"links": None, "notes": None}])
def test_no_links_and_no_notes_chosen_is_refused(client, body):
    response = send_json(client, body)
    assert response.status_code == 400
    assert response.get_json() == {"error": "Choose at least one recipe to import"}


@pytest.mark.parametrize("bad", [
    "buy butter",
    REEL,
    NOTE + "\n" + REEL + "\n" + TIKTOK,
    NOTE + "\n---\n" + OTHER_NOTE,
    NOTE + "\n---\n" + REEL,
    "",
    "   ",
    "x" * 6000,
    123,
    None,
    [NOTE],
    {"text": NOTE},
], ids=repr)
def test_a_chosen_note_that_is_not_one_recipe_written_out_refuses_the_whole_request(client, reading, bad):
    response = import_notes(client, [NOTE, bad], links=[REEL])
    assert response.status_code == 400
    assert response.get_json() == {"error": NOT_ONE_NOTE}
    assert all_recipes(client) == [] and reading == []


@pytest.mark.parametrize("notes", [NOTE, {"0": NOTE}, 5, True])
def test_chosen_notes_that_are_not_a_list_are_refused(client, reading, notes):
    response = import_notes(client, notes)
    assert response.status_code == 400
    assert response.get_json() == {"error": NOT_ONE_NOTE}
    assert all_recipes(client) == []


def test_chosen_links_that_are_not_a_list_are_still_refused_when_notes_are_chosen(client, reading):
    response = send_json(client, {"links": REEL, "notes": [NOTE]})
    assert response.status_code == 400
    assert response.get_json() == {"error": "Choose at least one recipe to import"}
    assert all_recipes(client) == []


def test_a_bad_link_refuses_the_notes_chosen_with_it(client, reading):
    response = send_json(client, {"links": [PROFILE], "notes": [NOTE]})
    assert response.status_code == 400
    assert response.get_json() == {"error": "One of the chosen links is not a TikTok or Instagram post, reel or video"}
    assert all_recipes(client) == [] and reading == []


def test_the_recipes_page_data_of_a_note_recipe_has_no_link_to_show(client, reading):
    import_notes(client, [NOTE])
    (listed,) = client.get("/api/recipes").get_json()
    recipe = client.get(f"/api/recipes/{listed['id']}").get_json()
    assert (recipe["source_url"], recipe["platform"]) == ("", "notes")


def test_a_caption_is_read_as_a_caption_whichever_way_it_arrives(client, monkeypatch):
    kinds = []

    def read(text, kind):
        kinds.append(kind)
        return {"title": "Garlic bread", "ingredients": ["butter"], "directions": ["Bake"]}

    monkeypatch.setattr(app_module, "extract_recipe", read)
    monkeypatch.setattr(app_module, "fetch_tiktok_data", lambda url: {"caption": "Garlic bread", "thumbnail_url": None})

    import_chosen(client, [TIKTOK])
    client.post("/api/recipes", json={"url": REEL, "caption": "Garlic bread: butter, garlic"})
    waiting = client.post("/api/recipes", json={"url": POST}).get_json()
    client.patch(f"/api/recipes/{waiting['id']}/caption", json={"caption": "Garlic bread: butter, garlic"})

    assert kinds == ["caption", "caption", "caption"]

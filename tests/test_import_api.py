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

    def fake_extraction(caption):
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

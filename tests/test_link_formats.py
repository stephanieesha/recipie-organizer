"""
The ways people really paste a TikTok or Instagram link into the "add a recipe" box:
copied from the share sheet, copied from an address bar with the https:// hidden,
or pasted together with the words the app put around it. Each case goes through the
real add-recipe route, so what is checked is what ends up saved.

The cases marked EXPECTED_TO_FAIL show pasting problems that are fixed in the next commit.
"""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import app as app_module  # noqa: E402
import db  # noqa: E402
import limits  # noqa: E402
from tiktok_oembed import TikTokFetchError  # noqa: E402

TIKTOK = "https://www.tiktok.com/@chef/video/7123456789"
TIKTOK_SHORT = "https://vt.tiktok.com/ZSpv3EJdj/"
INSTAGRAM = "https://www.instagram.com/reel/DQ6rx2JDxFR/"

EXPECTED_TO_FAIL = pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="pasting problem fixed in the next commit"
)


@pytest.fixture
def client(monkeypatch):
    for name in ("WRITE_LIMIT_PER_MINUTE", "AUTH_LIMIT_PER_15_MIN", "DAILY_SIGNUP_LIMIT", "DAILY_AI_LIMIT"):
        monkeypatch.delenv(name, raising=False)
    limits._recent_requests.clear()
    limits._recent_auth_attempts.clear()

    def tiktok_unavailable(url):
        raise TikTokFetchError("not reachable in tests")

    # No test reaches TikTok: the link is saved and left for manual entry.
    monkeypatch.setattr(app_module, "fetch_tiktok_data", tiktok_unavailable)

    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(db, "DB_PATH", Path(tmpdir) / "test.db")
        db.init_db()
        app_module.app.config["TESTING"] = True
        test_client = app_module.app.test_client()
        test_client.post("/signup", data={"email": "cook@example.com", "password": "correct-horse"})
        yield test_client


def paste(client, text):
    return client.post("/api/recipes", json={"url": text})


# --- Links that should be saved as they are -------------------------------

@pytest.mark.parametrize("link, platform", [
    (TIKTOK, "tiktok"),
    (TIKTOK_SHORT, "tiktok"),
    ("https://vm.tiktok.com/ZMabcdef/", "tiktok"),
    ("https://www.tiktok.com/t/ZTabc123/", "tiktok"),
    ("https://m.tiktok.com/v/7123456789.html", "tiktok"),
    ("http://www.tiktok.com/@chef/video/7123456789", "tiktok"),
    ("https://www.tiktok.com/@chef/video/7123456789?is_from_webapp=1&sender_device=pc", "tiktok"),
    (INSTAGRAM, "instagram"),
    ("https://www.instagram.com/reel/DQ6rx2JDxFR/?igsh=MXx4eWx", "instagram"),
    ("https://www.instagram.com/p/fA9uwTtkSN/", "instagram"),
    ("https://www.instagram.com/share/reel/BAbc123/", "instagram"),
])
def test_a_normal_link_is_saved_unchanged(client, link, platform):
    response = paste(client, link)
    assert response.status_code == 201
    saved = response.get_json()
    assert saved["source_url"] == link
    assert saved["platform"] == platform


@pytest.mark.parametrize("text", [f"  {TIKTOK}  ", f"{TIKTOK}\n", f"\n{INSTAGRAM}"])
def test_spaces_and_line_breaks_around_a_link_are_ignored(client, text):
    response = paste(client, text)
    assert response.status_code == 201
    assert response.get_json()["source_url"] == text.strip()


# --- Links as people really copy them -------------------------------------

@pytest.mark.parametrize("text, saved_as", [
    pytest.param("www.instagram.com/reel/DQ6rx2JDxFR/", INSTAGRAM, marks=EXPECTED_TO_FAIL, id="instagram-www-no-https"),
    pytest.param("instagram.com/reel/DQ6rx2JDxFR/", INSTAGRAM, marks=EXPECTED_TO_FAIL, id="instagram-no-https"),
    pytest.param("www.tiktok.com/@chef/video/7123456789", TIKTOK, marks=EXPECTED_TO_FAIL, id="tiktok-www-no-https"),
    pytest.param("tiktok.com/@chef/video/7123456789", TIKTOK, marks=EXPECTED_TO_FAIL, id="tiktok-no-https"),
    pytest.param(f"Check out this video {TIKTOK_SHORT} via TikTok", TIKTOK_SHORT, marks=EXPECTED_TO_FAIL, id="tiktok-share-text"),
    pytest.param(f"Look at this recipe!\n{INSTAGRAM}", INSTAGRAM, marks=EXPECTED_TO_FAIL, id="text-before-link"),
    pytest.param(f"{TIKTOK_SHORT} Check out this video", TIKTOK_SHORT, marks=EXPECTED_TO_FAIL, id="text-after-link"),
])
def test_a_link_pasted_with_extra_text_or_without_https_is_saved_cleanly(client, text, saved_as):
    response = paste(client, text)
    assert response.status_code == 201
    assert response.get_json()["source_url"] == saved_as


# --- Things that are not a recipe link ------------------------------------

@pytest.mark.parametrize("text", [
    "",
    "   ",
    "not a link at all",
    "https://www.youtube.com/watch?v=abc123",
    "https://www.tiktok.com/",
    "https://www.instagram.com",
    "https://tiktok.com.evil.example/video/1",
    "https://nottiktok.com/@chef/video/1",
    "https://evil.example/?u=https://www.tiktok.com/@chef/video/1",
])
def test_anything_else_is_refused_and_nothing_is_saved(client, text):
    response = paste(client, text)
    assert response.status_code == 400
    assert client.get("/api/recipes").get_json() == []


@EXPECTED_TO_FAIL
def test_two_links_in_one_paste_are_refused_rather_than_saved_as_one_address(client):
    response = paste(client, f"{INSTAGRAM}\n{TIKTOK}")
    assert response.status_code == 400
    assert client.get("/api/recipes").get_json() == []

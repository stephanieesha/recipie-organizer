import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from url_utils import detect_platform, extract_urls_from_text


def test_detect_tiktok_standard_url():
    assert detect_platform("https://www.tiktok.com/@user/video/123456") == "tiktok"


def test_detect_tiktok_short_url():
    assert detect_platform("https://vm.tiktok.com/ZMabcdef/") == "tiktok"


def test_detect_tiktok_vt_short_url():
    assert detect_platform("https://vt.tiktok.com/ZSpv3EJdj/") == "tiktok"


def test_detect_instagram_reel():
    assert detect_platform("https://www.instagram.com/reel/DQ6rx2JDxFR/") == "instagram"


def test_detect_instagram_post():
    assert detect_platform("https://www.instagram.com/p/fA9uwTtkSN/") == "instagram"


def test_detect_rejects_unsupported_platform():
    with pytest.raises(ValueError):
        detect_platform("https://www.youtube.com/watch?v=abc123")


def test_detect_rejects_garbage_input():
    with pytest.raises(ValueError):
        detect_platform("not a url at all")


def test_extract_urls_from_plain_text_list():
    text = """
    https://www.instagram.com/reel/DQ6rx2JDxFR/?utm_source=ig_web_copy_link
    https://www.tiktok.com/@user/video/7123456789
    """
    urls = extract_urls_from_text(text)
    assert len(urls) == 2
    assert any("instagram.com" in u for u in urls)
    assert any("tiktok.com" in u for u in urls)


def test_extract_urls_deduplicates():
    text = "https://www.tiktok.com/@user/video/123 https://www.tiktok.com/@user/video/123"
    urls = extract_urls_from_text(text)
    assert len(urls) == 1


def test_extract_urls_from_json_export_style_text():
    json_like = '''
    {"saved_saved_media": [
      {"href": "https://www.instagram.com/reel/ABC123/", "timestamp": 1700000000},
      {"href": "https://www.instagram.com/p/DEF456/", "timestamp": 1700000001}
    ]}
    '''
    urls = extract_urls_from_text(json_like)
    assert len(urls) == 2
    assert "https://www.instagram.com/reel/ABC123/" in urls


def test_extract_urls_strips_trailing_json_punctuation():
    text = '"href": "https://www.tiktok.com/@user/video/999",'
    urls = extract_urls_from_text(text)
    assert urls == ["https://www.tiktok.com/@user/video/999"]


def test_extract_urls_ignores_unrelated_links():
    text = "https://www.youtube.com/watch?v=abc https://example.com/page"
    urls = extract_urls_from_text(text)
    assert urls == []


def test_extract_urls_empty_text_returns_empty_list():
    assert extract_urls_from_text("") == []


# --- find_recipe_link: the link inside whatever was pasted -----------------

from url_utils import find_recipe_link  # noqa: E402


@pytest.mark.parametrize("text, expected", [
    ("https://www.tiktok.com/@user/video/123", "https://www.tiktok.com/@user/video/123"),
    ("www.instagram.com/reel/ABC/", "https://www.instagram.com/reel/ABC/"),
    ("instagram.com/reel/ABC/", "https://instagram.com/reel/ABC/"),
    ("Check out this video https://vt.tiktok.com/ZSabc/ via TikTok", "https://vt.tiktok.com/ZSabc/"),
    ("see (https://www.tiktok.com/@user/video/123).", "https://www.tiktok.com/@user/video/123"),
    ("HTTPS://WWW.TIKTOK.COM/@user/video/1", "HTTPS://WWW.TIKTOK.COM/@user/video/1"),
    ("https://www.tiktok.com/@u/video/1 https://www.tiktok.com/@u/video/1", "https://www.tiktok.com/@u/video/1"),
])
def test_find_recipe_link_returns_the_one_link(text, expected):
    assert find_recipe_link(text) == expected


@pytest.mark.parametrize("text", [
    "",
    "no link here",
    "https://www.youtube.com/watch?v=abc",
    "https://www.tiktok.com/",
    "https://tiktok.com.evil.example/video/1",
    "https://nottiktok.com/@chef/video/1",
    "https://evil.example/?u=https://www.tiktok.com/@chef/video/1",
    "https://evil.example/?u=tiktok.com/@chef/video/1",
])
def test_find_recipe_link_refuses_text_without_a_real_link(text):
    with pytest.raises(ValueError, match="TikTok or Instagram video, reel or post"):
        find_recipe_link(text)


def test_find_recipe_link_refuses_two_different_links():
    with pytest.raises(ValueError, match="one link at a time"):
        find_recipe_link("https://www.tiktok.com/@u/video/1 https://www.instagram.com/reel/ABC/")

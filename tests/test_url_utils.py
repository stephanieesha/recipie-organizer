import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from url_utils import detect_platform, extract_urls_from_text, link_key, tiktok_web_link


def test_detect_tiktok_standard_url():
    assert detect_platform("https://www.tiktok.com/@user/video/123456") == "tiktok"


def test_detect_tiktok_short_url():
    assert detect_platform("https://vm.tiktok.com/ZMabcdef/") == "tiktok"


def test_detect_tiktok_vt_short_url():
    assert detect_platform("https://vt.tiktok.com/ZSpv3EJdj/") == "tiktok"


def test_detect_tiktokv_share_url():
    assert detect_platform("https://www.tiktokv.com/share/video/7123456789/") == "tiktok"


@pytest.mark.parametrize("url", [
    "https://tiktokv.com.evil.example/share/video/1",
    "https://nottiktokv.com/share/video/1",
    "https://tiktokvx.com/share/video/1",
    "https://www.tiktokvv.com/share/video/1",
])
def test_detect_rejects_addresses_that_only_look_like_tiktokv(url):
    with pytest.raises(ValueError):
        detect_platform(url)


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
    ("https://www.tiktokv.com/share/video/7123456789/", "https://www.tiktokv.com/share/video/7123456789/"),
    ("tiktokv.com/share/video/7123456789/", "https://tiktokv.com/share/video/7123456789/"),
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
    "https://tiktokv.com.evil.example/share/video/1",
    "https://nottiktokv.com/share/video/1",
    "https://tiktokvv.com/share/video/1",
    "https://evil.example/?u=https://www.tiktokv.com/share/video/1",
])
def test_find_recipe_link_refuses_text_without_a_real_link(text):
    with pytest.raises(ValueError, match="TikTok or Instagram video, reel or post"):
        find_recipe_link(text)


def test_find_recipe_link_refuses_two_different_links():
    with pytest.raises(ValueError, match="one link at a time"):
        find_recipe_link("https://www.tiktok.com/@u/video/1 https://www.instagram.com/reel/ABC/")


# --- tiktok_web_link: the ordinary link for a link from TikTok's data download ----

@pytest.mark.parametrize("url", [
    "https://www.tiktokv.com/share/video/7123456789/",
    "https://www.tiktokv.com/share/video/7123456789",
    "https://m.tiktokv.com/share/video/7123456789/?x=1",
    "https://www.tiktok.com/share/video/7123456789/",
    "  https://www.tiktokv.com/share/video/7123456789/  ",
    "HTTPS://WWW.TIKTOKV.COM/SHARE/VIDEO/7123456789/",
])
def test_a_data_download_link_gets_its_ordinary_web_link(url):
    assert tiktok_web_link(url) == "https://www.tiktok.com/@_/video/7123456789"


@pytest.mark.parametrize("url", [
    "https://www.tiktok.com/@chef/video/7123456789",
    "https://vt.tiktok.com/ZSabc/",
    "https://www.tiktokv.com/share/video/abc/",
    "https://www.tiktokv.com/share/user/7123456789/",
    "https://www.tiktokv.com/share/7123456789/",
    "https://www.instagram.com/share/video/7123456789/",
    "https://evil.example/share/video/7123456789/",
    "https://tiktokv.com.evil.example/share/video/7123456789/",
    "",
])
def test_any_other_link_has_no_such_web_link(url):
    assert tiktok_web_link(url) is None


# ---------- which post a link goes to ----------

SAME_POST = [
    pytest.param("instagram:DQ6rx2JDxFR", [
        "https://www.instagram.com/reel/DQ6rx2JDxFR/",
        "https://www.instagram.com/p/DQ6rx2JDxFR/",
        "https://www.instagram.com/tv/DQ6rx2JDxFR/",
        "https://www.instagram.com/reels/DQ6rx2JDxFR/",
        "https://www.instagram.com/chef_one/reel/DQ6rx2JDxFR/",
        "https://www.instagram.com/chef.one/p/DQ6rx2JDxFR/",
        "https://instagram.com/reel/DQ6rx2JDxFR",
        "http://www.instagram.com/reel/DQ6rx2JDxFR/?igsh=MXx4eWx&utm_source=ig_web_copy_link",
        "https://WWW.Instagram.com/REEL/DQ6rx2JDxFR/",
        "https://m.instagram.com/p/DQ6rx2JDxFR/#comments",
        "  https://www.instagram.com/reel/DQ6rx2JDxFR/  ",
        "\u00a0https://www.instagram.com/reel/DQ6rx2JDxFR/\u00a0",
    ], id="instagram post"),
    pytest.param("instagram:share:BAbc123", [
        "https://www.instagram.com/share/reel/BAbc123/",
        "https://www.instagram.com/share/p/BAbc123/",
        "https://www.instagram.com/share/BAbc123",
        "https://www.instagram.com/share/reel/BAbc123/?igsh=x",
    ], id="instagram share link"),
    pytest.param("tiktok:7123456789", [
        "https://www.tiktok.com/@chef/video/7123456789",
        "https://www.tiktok.com/@other.chef/video/7123456789/",
        "https://www.tiktok.com/@_/video/7123456789",
        "https://www.tiktok.com/@chef/photo/7123456789",
        "http://tiktok.com/@chef/video/7123456789?is_from_webapp=1&sender_device=pc",
        "https://m.tiktok.com/v/7123456789.html",
        "https://www.tiktokv.com/share/video/7123456789/",
        "https://www.tiktokv.com/share/video/7123456789",
        "HTTPS://WWW.TIKTOK.COM/@Chef/VIDEO/7123456789",
    ], id="tiktok video"),
    pytest.param("tiktok:vm.tiktok.com/ZMabcdef", [
        "https://vm.tiktok.com/ZMabcdef/",
        "http://VM.TikTok.com/ZMabcdef?x=1",
    ], id="tiktok vm link"),
    pytest.param("tiktok:vt.tiktok.com/ZSpv3EJdj", ["https://vt.tiktok.com/ZSpv3EJdj/"], id="tiktok vt link"),
    pytest.param("tiktok:t/ZTabc123", ["https://www.tiktok.com/t/ZTabc123/", "https://tiktok.com/t/ZTabc123"], id="tiktok t link"),
]


@pytest.mark.parametrize("key, links", SAME_POST)
def test_every_way_of_writing_a_link_to_one_post_gives_the_same_key(key, links):
    assert [link_key(link) for link in links] == [key] * len(links)


@pytest.mark.parametrize("one, other", [
    ("https://www.instagram.com/reel/AbCdEf/", "https://www.instagram.com/reel/abcdef/"),
    ("https://www.instagram.com/reel/AAA/", "https://www.instagram.com/reel/BBB/"),
    ("https://www.instagram.com/share/reel/BAbc123/", "https://www.instagram.com/reel/BAbc123/"),
    ("https://www.tiktok.com/@chef/video/7123456789", "https://www.tiktok.com/@chef/video/7123456780"),
    ("https://vm.tiktok.com/ZMabcdef/", "https://vt.tiktok.com/ZMabcdef/"),
    ("https://vm.tiktok.com/ZMabcdef/", "https://vm.tiktok.com/ZMABCDEF/"),
    ("https://vm.tiktok.com/ZMabcdef/", "https://www.tiktok.com/t/ZMabcdef/"),
    ("https://www.tiktok.com/@chef/video/7123456789", "https://vm.tiktok.com/7123456789/"),
    ("https://www.instagram.com/reel/AAA/", "https://www.tiktok.com/t/AAA/"),
])
def test_links_to_different_posts_have_different_keys(one, other):
    assert link_key(one) != link_key(other)


@pytest.mark.parametrize("link", [
    "https://www.instagram.com/chef_one/",
    "https://www.instagram.com/explore/tags/jollof/",
    "https://www.instagram.com/stories/chef_one/123/",
    "https://www.instagram.com/reels/audio/1234567890/",
    "https://www.instagram.com/",
    "https://www.tiktok.com/@chef",
    "https://www.tiktok.com/tag/jollof",
    "https://www.tiktok.com/music/sound-123",
    "https://www.tiktok.com/@chef/video/abc",
    "https://vm.tiktok.com/",
    "https://www.youtube.com/watch?v=abc123",
    "https://www.instagram.com.evil.example/reel/abc123/",
    "https://evil.example/?u=https://www.instagram.com/reel/abc123/",
    "www.instagram.com/reel/abc123/",
    "not a link",
    "https://",
    "http://[::1",
    "",
    "   ",
])
def test_a_link_that_does_not_go_to_one_post_has_no_key_and_never_raises(link):
    assert link_key(link) is None

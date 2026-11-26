"""
Reading the file someone uploads for a bulk import: Instagram's saved_posts file as JSON or HTML,
and a plain list of links. What matters is that every saved post is found, nothing that is not a
post is imported, and a file that cannot be used is explained in plain words.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from import_parser import NO_LINKS, NO_POSTS, ImportFileError, read_export  # noqa: E402
from url_utils import is_post_link  # noqa: E402

REEL = "https://www.instagram.com/reel/DQ6rx2JDxFR/"
POST = "https://www.instagram.com/p/fA9uwTtkSN/"
TV = "https://www.instagram.com/tv/CxYz123abc/"


def urls(text):
    return [link["url"] for link in read_export(text)]


def saved_posts_json(*hrefs, indent=2):
    """The shape of Instagram's saved_posts.json: one entry per saved post."""
    entries = [
        {"title": f"chef_{i}", "string_map_data": {"Saved on": {"href": href, "timestamp": 1700000000 + i}}}
        for i, href in enumerate(hrefs)
    ]
    return json.dumps({"saved_saved_media": entries}, indent=indent)


# ---------- Instagram's saved posts, as JSON ----------

def test_saved_posts_json_gives_every_post_in_file_order():
    assert urls(saved_posts_json(REEL, POST, TV)) == [REEL, POST, TV]


def test_each_link_comes_with_its_platform():
    assert read_export(saved_posts_json(REEL)) == [{"url": REEL, "platform": "instagram"}]


def test_saved_posts_json_on_one_line_is_read_too():
    assert urls(saved_posts_json(REEL, POST, indent=None)) == [REEL, POST]


def test_a_link_with_tracking_parameters_is_kept_as_it_is():
    link = REEL + "?utm_source=ig_web_copy_link&igsh=MXx4eWx"
    assert urls(saved_posts_json(link)) == [link]


def test_slashes_escaped_the_way_some_exports_write_them_are_decoded():
    text = '{"saved_saved_media":[{"string_map_data":{"Saved on":{"href":"https:\\/\\/www.instagram.com\\/reel\\/DQ6rx2JDxFR\\/"}}}]}'
    assert urls(text) == [REEL]


def test_links_come_out_in_the_order_they_appear_in_the_file():
    text = json.dumps({"first": REEL, "second": [{"a": POST, "b": TV}, "x"], "third": {"c": [REEL.replace("DQ6", "ZZZ")]}})
    assert urls(text) == [REEL, POST, TV, REEL.replace("DQ6", "ZZZ")]


@pytest.mark.parametrize("indent", [2, None])
def test_a_file_cut_off_part_way_still_gives_the_posts_before_the_cut(indent):
    whole = saved_posts_json(REEL, POST, TV, indent=indent)
    cut = whole[: whole.index(TV) - 4]  # ends just before the last link starts
    with pytest.raises(json.JSONDecodeError):
        json.loads(cut)
    assert urls(cut) == [REEL, POST]


# ---------- Instagram's saved posts, as HTML ----------

HTML_EXPORT = """
<html><body>
<div class="pam"><div>chef_one</div><div>Saved on Jan 3, 2025
<a target="_blank" href="https://www.instagram.com/reel/DQ6rx2JDxFR/">https://www.instagram.com/reel/DQ6rx2JDxFR/</a></div></div>
<div class="pam"><div>chef_two</div><div>Saved on Jan 2, 2025
<a target="_blank" href="https://www.instagram.com/p/fA9uwTtkSN/?img_index=1&amp;igsh=abc">https://www.instagram.com/p/fA9uwTtkSN/?img_index=1&amp;igsh=abc</a></div></div>
<a href="https://www.instagram.com/chef_one/">chef_one</a>
</body></html>
"""


def test_html_export_gives_the_posts_and_not_the_profile_links():
    assert urls(HTML_EXPORT) == [REEL, POST + "?img_index=1&igsh=abc"]


def test_a_link_in_html_stops_at_the_closing_quote_and_tag():
    found = urls('<a href="https://www.instagram.com/reel/AAA111/">x</a><a href="https://www.instagram.com/reel/BBB222/">y</a>')
    assert found == ["https://www.instagram.com/reel/AAA111/", "https://www.instagram.com/reel/BBB222/"]


def test_a_link_in_single_quotes_or_angle_brackets_ends_where_the_link_ends():
    text = f"<a href='{REEL}'>reel</a> and <{POST}> and [{TV}]"
    assert urls(text) == [REEL, POST, TV]


def test_quoted_links_with_no_space_between_them_are_told_apart():
    assert urls(f"['{REEL}','{POST}']") == [REEL, POST]


def test_html_inside_a_json_string_in_a_file_that_is_cut_off_still_gives_the_link():
    # Not valid JSON (the end is missing), so it is read as plain text, with the quotes still escaped.
    text = '{"saved_saved_media": [{"html": "<a href=\\"https:\\/\\/www.instagram.com\\/reel\\/DQ6rx2JDxFR\\/\\">x</a>"}, '
    assert urls(text) == [REEL]


# ---------- links that only look like Instagram links ----------

@pytest.mark.parametrize("text", [
    "https://notinstagram.com/p/fA9uwTtkSN/",
    "https://instagram.com.evil.example/p/fA9uwTtkSN/",
    "https://evil.example/?u=https://www.instagram.com/p/fA9uwTtkSN/",
    "https://evil.example/?u=instagram.com/p/fA9uwTtkSN/",
    "https://evil.example/?instagram.com/p/fA9uwTtkSN/",
    "https://evil.example/?a=1&instagram.com/p/fA9uwTtkSN/",
    "https://evil.example/foo.instagram.com/p/fA9uwTtkSN/",
    "https://evil.example/instagram.com/p/fA9uwTtkSN/",
    "https://evil.example/100%instagram.com/p/fA9uwTtkSN/",
    "https://evil-instagram.com/p/fA9uwTtkSN/",
    "chef@instagram.com/p/fA9uwTtkSN/",
])
def test_a_link_to_another_address_that_mentions_instagram_is_not_imported(text):
    with pytest.raises(ImportFileError) as error:
        read_export(text)
    assert str(error.value) == NO_LINKS


# ---------- a plain list of links ----------

def test_one_link_per_line():
    assert urls(f"{REEL}\n{POST}\n") == [REEL, POST]


def test_links_without_https_get_it_added():
    assert urls("instagram.com/reel/DQ6rx2JDxFR/\nwww.instagram.com/p/fA9uwTtkSN/") == [
        "https://instagram.com/reel/DQ6rx2JDxFR/", "https://www.instagram.com/p/fA9uwTtkSN/",
    ]


def test_punctuation_after_a_link_is_not_part_of_it():
    assert urls(f"saved: {REEL}, and ({POST}).") == [REEL, POST]


def test_the_same_link_twice_is_imported_once():
    assert urls(f"{REEL}\n{POST}\n{REEL}\n") == [REEL, POST]


def test_tiktok_links_in_a_list_are_still_read():
    tiktok = "https://www.tiktok.com/@chef/video/7123456789"
    assert read_export(f"{REEL}\n{tiktok}") == [
        {"url": REEL, "platform": "instagram"}, {"url": tiktok, "platform": "tiktok"},
    ]


# ---------- only posts are imported ----------

POSTS = [
    REEL, POST, TV,
    "https://www.instagram.com/reels/DQ6rx2JDxFR/",
    "https://www.instagram.com/chef.one/p/fA9uwTtkSN/",
    "https://www.instagram.com/chef_one/reel/DQ6rx2JDxFR/",
    "https://www.instagram.com/share/reel/BAbc123/",
    "https://www.instagram.com/share/BAbc123",
    "https://instagram.com/p/fA9uwTtkSN",
    "https://www.instagram.com/p/fA9uwTtkSN/?img_index=2",
    "https://www.instagram.com/p/-Ab_C1d2eF/",
    "https://www.instagram.com/reel/_Ab-C1d2eF/",
    "https://www.instagram.com/REEL/DQ6rx2JDxFR/",
]
NOT_POSTS = [
    "https://www.instagram.com/chef_one/",
    "https://www.instagram.com/chef_one/reels/",
    "https://www.instagram.com/chef_one/tagged/",
    "https://www.instagram.com/explore/tags/jollof/",
    "https://www.instagram.com/explore/locations/123456/lagos/",
    "https://www.instagram.com/stories/chef_one/3012345678901234567/",
    "https://www.instagram.com/reels/audio/1234567890/",
    "https://www.instagram.com/reels/",
    "https://www.instagram.com/p/",
    "https://www.instagram.com/explore/tags/jollof/p/fA9uwTtkSN/",
    "https://www.instagram.com/accounts/login/?next=/p/fA9uwTtkSN/",
    "https://www.instagram.com/",
    "https://about.instagram.com/blog",
]


@pytest.mark.parametrize("link", POSTS)
def test_these_are_post_links(link):
    assert is_post_link(link)
    assert urls(link) == [link]


@pytest.mark.parametrize("link", NOT_POSTS)
def test_these_are_not_post_links(link):
    assert not is_post_link(link)


def test_a_file_with_profile_and_hashtag_links_between_the_posts_imports_only_the_posts():
    mixed = "\n".join([NOT_POSTS[0], REEL, NOT_POSTS[3], POST, NOT_POSTS[5]])
    assert urls(mixed) == [REEL, POST]


@pytest.mark.parametrize("link", ["https://www.youtube.com/watch?v=abc", "not a link", ""])
def test_a_link_to_another_site_is_not_a_post_link(link):
    assert not is_post_link(link)


# ---------- files that cannot be imported ----------

@pytest.mark.parametrize("text", ["", "   \n\t "])
def test_an_empty_file_is_explained(text):
    with pytest.raises(ImportFileError, match="empty"):
        read_export(text)


@pytest.mark.parametrize("text", [
    "no links in here",
    '{"saved_saved_media": []}',
    '{"name": "chef", "followers": 120}',
    "https://www.youtube.com/watch?v=abc https://example.com/page",
])
def test_a_file_without_instagram_or_tiktok_links_is_explained(text):
    with pytest.raises(ImportFileError) as error:
        read_export(text)
    assert str(error.value) == NO_LINKS


def test_a_file_with_only_profile_links_says_there_are_no_posts_in_it():
    following = json.dumps({"relationships_following": [{"string_list_data": [{"href": NOT_POSTS[0]}]}]})
    with pytest.raises(ImportFileError) as error:
        read_export(following)
    assert str(error.value) == NO_POSTS
    assert "saved_posts.json" in NO_POSTS


def test_a_file_that_is_not_text_is_explained_rather_than_crashing():
    with pytest.raises(ImportFileError):
        read_export(bytes(range(256)).decode("utf-8", errors="ignore"))


def test_the_error_is_a_value_error_so_callers_can_catch_either():
    assert issubclass(ImportFileError, ValueError)


# ---------- size ----------

def test_a_long_file_is_read_quickly():
    hrefs = [f"https://www.instagram.com/reel/C{i:010d}/" for i in range(20000)]
    assert urls(saved_posts_json(*hrefs)) == hrefs

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

from import_parser import (  # noqa: E402
    NO_FAVORITES, NO_LINKS, NO_POSTS, TIKTOK_TEXT_FILE, TIKTOK_UNREADABLE, ImportFileError, read_export,
)
from url_utils import is_post_link  # noqa: E402

REEL = "https://www.instagram.com/reel/DQ6rx2JDxFR/"
POST = "https://www.instagram.com/p/fA9uwTtkSN/"
TV = "https://www.instagram.com/tv/CxYz123abc/"


def tiktok_link(video_id):
    """A link written the way TikTok's own data download writes them."""
    return f"https://www.tiktokv.com/share/video/{video_id}/"


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


def test_the_same_post_written_two_ways_is_imported_once_with_the_first_way():
    other_way = REEL.replace("/reel/", "/p/") + "?igsh=MXx4eWx"
    assert urls(f"{REEL}\n{POST}\n{other_way}\n") == [REEL, POST]
    assert urls(f"{other_way}\n{REEL}\n") == [other_way]


def test_a_tiktok_video_written_two_ways_is_imported_once():
    data_download = tiktok_link(7123456789)
    address_bar = "https://www.tiktok.com/@chef/video/7123456789"
    assert urls(f"{data_download}\n{address_bar}\n") == [data_download]


def test_posts_whose_codes_differ_only_in_case_are_different_posts():
    lower = REEL.replace("DQ6rx2JDxFR", "dq6rx2jdxfr")
    assert urls(f"{REEL}\n{lower}\n") == [REEL, lower]


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


# ---------- TikTok's data download: only the favorites ----------

def tiktok_data(favorites=(), likes=(), history=(), indent=2, favorites_key="Favorite Videos", link_key="Link"):
    """The shape of TikTok's user_data.json, where the favorites sit next to the likes and the watch history."""
    def entries(links, key):
        return [{"Date": f"2023-05-{i + 1:02d} 10:00:00", key: link} for i, link in enumerate(links)]

    activity = {
        "Favorite Effects": {"FavoriteEffectsList": [{"Date": "2023-01-01 10:00:00", "EffectLink": "https://www.tiktok.com/effect/1"}]},
        favorites_key: {"FavoriteVideoList": entries(favorites, link_key)},
        "Like List": {"ItemFavoriteList": entries(likes, "link")},
        "Video Browsing History": {"VideoList": entries(history, "VideoLink")},
    }
    return json.dumps({"Profile": {"Profile Information": {"ProfileMap": {"userName": "cook"}}}, "Activity": activity}, indent=indent)


FAVORITES = [tiktok_link(7100000000000000001 + i) for i in range(3)]
LIKES = [tiktok_link(7200000000000000001 + i) for i in range(4)]
HISTORY = [tiktok_link(7300000000000000001 + i) for i in range(5)]


def test_only_the_favorites_are_imported_not_the_likes_or_the_watch_history():
    assert urls(tiktok_data(FAVORITES, LIKES, HISTORY)) == FAVORITES


def test_each_favorite_is_a_tiktok_link():
    assert read_export(tiktok_data(FAVORITES[:1], LIKES, HISTORY)) == [{"url": FAVORITES[0], "platform": "tiktok"}]


def test_the_favorites_of_a_file_on_one_line_are_read_too():
    assert urls(tiktok_data(FAVORITES, LIKES, HISTORY, indent=None)) == FAVORITES


def test_the_british_spelling_of_the_section_is_read_too():
    assert urls(tiktok_data(FAVORITES, LIKES, HISTORY, favorites_key="Favourite Videos")) == FAVORITES


@pytest.mark.parametrize("link_key", ["Link", "link", "VideoLink"])
def test_the_name_of_the_link_field_does_not_matter(link_key):
    assert urls(tiktok_data(FAVORITES, LIKES, HISTORY, link_key=link_key)) == FAVORITES


@pytest.mark.parametrize("key", ["FavoriteVideoList", "FavouriteVideoList", "Favorite Videos", "Favourite Videos"])
def test_the_favorites_are_found_under_any_of_the_names_tiktok_uses(key):
    text = json.dumps({"Activity": {key: [{"Link": FAVORITES[0]}], "Like List": {"ItemFavoriteList": [{"link": LIKES[0]}]}}})
    assert urls(text) == [FAVORITES[0]]


def test_favorites_in_more_than_one_place_in_the_file_are_all_read():
    text = json.dumps({"One": {"Favorite Videos": [{"Link": FAVORITES[0]}]}, "Two": {"Favorite Videos": [{"Link": FAVORITES[1]}]}})
    assert urls(text) == FAVORITES[:2]


def test_favorites_come_out_in_the_order_they_are_in_the_file():
    text = json.dumps({"Favorite Videos": {"A": [FAVORITES[0], {"x": FAVORITES[1], "y": FAVORITES[2]}], "B": [{"z": LIKES[0]}]}})
    assert urls(text) == [FAVORITES[0], FAVORITES[1], FAVORITES[2], LIKES[0]]


def test_a_favorite_that_is_also_in_the_likes_is_still_imported_once():
    assert urls(tiktok_data(FAVORITES + FAVORITES[:1], FAVORITES, FAVORITES)) == FAVORITES


def test_links_that_are_not_videos_are_left_out_of_the_favorites():
    profile, tag, sound = "https://www.tiktok.com/@chef", "https://www.tiktok.com/tag/jollof", "https://www.tiktok.com/music/Sound-123"
    assert urls(tiktok_data([profile, FAVORITES[0], tag, sound, FAVORITES[1]])) == FAVORITES[:2]


def test_escaped_slashes_in_the_favorites_are_decoded():
    text = '{"Activity": {"Favorite Videos": {"FavoriteVideoList": [{"Link": "https:\\/\\/www.tiktokv.com\\/share\\/video\\/7100000000000000001\\/"}]}}}'
    assert urls(text) == [FAVORITES[0]]


def test_the_favorites_are_found_when_the_file_is_cut_off_after_them():
    whole = tiktok_data(FAVORITES, LIKES, HISTORY)
    cut = whole[: whole.index(HISTORY[2])]  # the watch history is cut off part way
    with pytest.raises(json.JSONDecodeError):
        json.loads(cut)
    assert urls(cut) == FAVORITES


def test_a_file_cut_off_inside_the_favorites_is_explained():
    whole = tiktok_data(FAVORITES, LIKES, HISTORY)
    cut = whole[: whole.index(FAVORITES[1])]
    with pytest.raises(ImportFileError) as error:
        read_export(cut)
    assert str(error.value) == TIKTOK_UNREADABLE


def test_favorites_nested_too_deeply_to_read_are_explained_not_crashed_on():
    with pytest.raises(ImportFileError) as error:
        read_export('{"Favorite Videos": ' + "[" * 100000)
    assert str(error.value) == TIKTOK_UNREADABLE


@pytest.mark.parametrize("empty", [
    tiktok_data([], LIKES, HISTORY),
    '{"Activity": {"Favorite Videos": {}, "Like List": {"ItemFavoriteList": []}}}',
    '{"Activity": {"Favorite Videos": []}}',
    '{"Activity": {"Favorite Videos": {"FavoriteVideoList": [{"Date": "2023-05-01 10:00:00"}]}}}',
])
def test_a_tiktok_file_without_favorites_says_so_and_does_not_import_the_likes(empty):
    with pytest.raises(ImportFileError) as error:
        read_export(empty)
    assert str(error.value) == NO_FAVORITES


@pytest.mark.parametrize("without", [
    json.dumps({"Activity": {"Like List": {"ItemFavoriteList": [{"link": LIKES[0]}]}, "Video Browsing History": {"VideoList": []}}}),
    json.dumps({"ItemFavoriteList": [{"link": LIKES[0]}]}),
    json.dumps({"Like List": {"anything": [{"link": LIKES[0]}]}}),
    json.dumps({"Video Browsing History": {"VideoList": [{"VideoLink": HISTORY[0]}]}}),
])
def test_a_tiktok_file_with_no_favorites_section_at_all_says_so(without):
    with pytest.raises(ImportFileError) as error:
        read_export(without)
    assert str(error.value) == NO_FAVORITES


def test_a_tiktok_data_file_in_text_form_is_explained_and_its_links_are_not_imported():
    text = "Activity\n  Favorite Videos\n    Date: 2023-05-01 10:00:00\n    Link: " + FAVORITES[0] + "\n  Video Browsing History\n    Link: " + HISTORY[0] + "\n"
    with pytest.raises(ImportFileError) as error:
        read_export(text)
    assert str(error.value) == TIKTOK_TEXT_FILE


@pytest.mark.parametrize("title", ["My Favorite Videos", "Like List", "My Favorite Videos: Like List"])
def test_a_title_in_someones_own_list_does_not_make_it_a_tiktok_data_file(title):
    text = f"{title}\n{FAVORITES[0]}\n{FAVORITES[1]}\n"
    assert urls(text) == FAVORITES[:2]


def test_a_huge_watch_history_is_not_read_and_the_favorites_still_are():
    history = [tiktok_link(7300000000000000000 + i) for i in range(150000)]
    text = tiktok_data(FAVORITES, LIKES, history, indent=None)
    assert len(text) > 15_000_000
    assert urls(text) == FAVORITES


def test_a_tiktok_link_list_in_a_plain_text_file_is_read_like_any_list():
    assert urls("\n".join(FAVORITES)) == FAVORITES


# ---------- TikTok links: which ones are videos ----------

TIKTOK_POSTS = [
    "https://www.tiktok.com/@chef/video/7123456789",
    "https://www.tiktok.com/@chef.one_2/video/7123456789?is_from_webapp=1&sender_device=pc",
    "https://www.tiktok.com/@chef/photo/7123456789",
    "https://www.tiktok.com/@_/video/7123456789",
    "https://m.tiktok.com/v/7123456789.html",
    "https://www.tiktok.com/t/ZTabc123/",
    "https://vm.tiktok.com/ZMabcdef/",
    "https://vt.tiktok.com/ZSpv3EJdj/",
    "https://vt.tiktok.com/ZS-pv_3EJdj",
    "https://www.tiktokv.com/share/video/7123456789/",
    "https://m.tiktokv.com/share/video/7123456789",
    "https://www.tiktok.com/share/video/7123456789",
    "HTTPS://WWW.TIKTOK.COM/@Chef/VIDEO/7123456789",
]
TIKTOK_NOT_POSTS = [
    "https://www.tiktok.com/@chef",
    "https://www.tiktok.com/@chef/",
    "https://www.tiktok.com/@chef/video/",
    "https://www.tiktok.com/@chef/video/abc",
    "https://www.tiktok.com/@/video/7123456789",
    "https://www.tiktok.com/discover/@chef/video/7123456789",
    "https://vt.tiktok.com/?ref=share",
    "https://www.tiktok.com/@chef/collection/Dinners-7123456789",
    "https://www.tiktok.com/tag/jollof",
    "https://www.tiktok.com/music/Original-Sound-7123456789",
    "https://www.tiktok.com/discover",
    "https://www.tiktok.com/foryou",
    "https://www.tiktok.com/live",
    "https://www.tiktok.com/",
    "https://vm.tiktok.com/",
    "https://www.tiktok.com/ZMabcdef/",
    "https://www.tiktokv.com/share/user/123456",
    "https://www.tiktokv.com/",
]


@pytest.mark.parametrize("link", TIKTOK_POSTS)
def test_these_are_tiktok_video_links(link):
    assert is_post_link(link)


@pytest.mark.parametrize("link", TIKTOK_NOT_POSTS)
def test_these_are_not_tiktok_video_links(link):
    assert not is_post_link(link)


@pytest.mark.parametrize("link", TIKTOK_POSTS[:-1])
def test_a_list_of_links_keeps_the_videos_and_drops_the_rest(link):
    mixed = "\n".join([TIKTOK_NOT_POSTS[0], link, TIKTOK_NOT_POSTS[5]])
    assert urls(mixed) == [link]


@pytest.mark.parametrize("text", [
    "https://tiktokv.com.evil.example/share/video/7123456789/",
    "https://nottiktokv.com/share/video/7123456789/",
    "https://tiktokvx.com/share/video/7123456789/",
    "https://tiktokvv.com/share/video/7123456789/",
    "https://evil.example/?u=https://www.tiktokv.com/share/video/7123456789/",
    "https://evil.example/foo.tiktokv.com/share/video/7123456789/",
])
def test_a_link_to_another_address_that_mentions_tiktokv_is_not_imported(text):
    with pytest.raises(ImportFileError) as error:
        read_export(text)
    assert str(error.value) == NO_LINKS

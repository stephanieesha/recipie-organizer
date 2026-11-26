"""
Reads a file someone uploads from their Instagram or TikTok data download, or a plain list of
links, and returns the recipe links in it.

Instagram keeps saved posts in saved_posts.json (or saved_posts.html). TikTok's download is one big
user_data.json, with the favorites next to thousands of watched and liked videos, so only the
favorites are read from it. Only links to one post or video are kept, so the profile, hashtag and
sound links around them are not imported as recipes.
"""

import html
import json
import re

from url_utils import detect_platform, extract_urls_from_text, is_post_link

MAX_UPLOAD_BYTES = 50 * 1024 * 1024

NO_LINKS = "No Instagram or TikTok links found in this file."
NO_POSTS = (
    "This file has Instagram or TikTok links, but none of them go to a post, reel or video, so "
    "there is nothing to import. For Instagram, upload saved_posts.json from your data download."
)
NO_FAVORITES = (
    "There are no favorite videos in this TikTok file. Only favorites are imported, not likes or "
    "watch history. In TikTok, tap the bookmark on a video to add it to your favorites, then "
    "download your data again."
)
TIKTOK_TEXT_FILE = (
    "This looks like a TikTok data file in text form, which cannot be read here. Request your data "
    "from TikTok again and choose JSON as the file format."
)
TIKTOK_UNREADABLE = (
    "The favorite videos in this TikTok file could not be read. The file may be damaged, so "
    "download your data from TikTok again."
)

# The part of TikTok's JSON file that holds the videos saved with the bookmark button.
FAVORITES_KEY = re.compile(r'"(?:Favou?rite Videos|Favou?riteVideoList)"\s*:\s*')
# Names that only a TikTok data file has, in either of its forms (JSON or text).
TIKTOK_DATA_FILE = re.compile(r'Video Browsing History|ItemFavoriteList|"Like List"\s*:')


class ImportFileError(ValueError):
    """The file cannot be imported. The message is written for the person who uploaded it."""


def read_export(text: str) -> list:
    """
    The recipe links in an uploaded file, in the order they appear, each one once, as
    [{"url": ..., "platform": "instagram" or "tiktok"}].
    Raises ImportFileError, with a message for the person, when the file has nothing to import.

    Anything but a TikTok data file is searched as plain text, so JSON, HTML and a list of links all
    work, and so does a file that was cut off part way. JSON writes a slash as \\/ and HTML writes &
    as &amp;, so both are turned back first.
    """
    if not text or text.isspace():
        raise ImportFileError("This file is empty.")

    found = _favorite_videos(text)
    if found is None:
        found = extract_urls_from_text(html.unescape(text.replace("\\/", "/")))

    posts = [url for url in dict.fromkeys(found) if is_post_link(url)]
    if not posts:
        raise ImportFileError(NO_POSTS if found else NO_LINKS)
    return [{"url": url, "platform": detect_platform(url)} for url in posts]


def _favorite_videos(text: str):
    """
    The links in the favorite videos of a TikTok data file, or None when this is not one. Only that
    one part of the file is read, so the likes and the watch history, which can run to hundreds of
    thousands of links, are never looked at.
    """
    sections = list(FAVORITES_KEY.finditer(text))
    if not sections:
        if TIKTOK_DATA_FILE.search(text):
            raise ImportFileError(NO_FAVORITES if re.match(r"\s*\{", text) else TIKTOK_TEXT_FILE)
        return None

    links = []
    for section in sections:
        try:
            value, _ = json.JSONDecoder().raw_decode(text, section.end())
        except (ValueError, RecursionError):
            raise ImportFileError(TIKTOK_UNREADABLE)
        for string in _strings_in(value):
            links.extend(extract_urls_from_text(string))
    if not links:
        raise ImportFileError(NO_FAVORITES)
    return links


def _strings_in(value):
    """Every string in a parsed JSON value, in file order, without recursion."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            stack.extend(reversed(list(item.values())))
        elif isinstance(item, list):
            stack.extend(reversed(item))

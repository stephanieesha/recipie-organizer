"""
Reads a file someone uploads from their Instagram data download, or a plain list of links, and
returns the recipe links in it.

Instagram keeps saved posts in saved_posts.json (or saved_posts.html). Only links to one post,
reel or video are kept, so the profile, hashtag and place links around them are not imported as
recipes.
"""

import html

from url_utils import detect_platform, extract_urls_from_text, is_post_link

MAX_UPLOAD_BYTES = 50 * 1024 * 1024

NO_LINKS = "No Instagram or TikTok links found in this file."
NO_POSTS = (
    "This file has Instagram or TikTok links, but none of them go to a post, reel or video, so "
    "there is nothing to import. For Instagram, upload saved_posts.json from your data download."
)


class ImportFileError(ValueError):
    """The file cannot be imported. The message is written for the person who uploaded it."""


def read_export(text: str) -> list:
    """
    The recipe links in an uploaded file, in the order they appear, each one once, as
    [{"url": ..., "platform": "instagram" or "tiktok"}].
    Raises ImportFileError, with a message for the person, when the file has nothing to import.

    The file is searched as plain text, so JSON, HTML and a list of links all work, and so does a
    file that was cut off part way. JSON writes a slash as \\/ and HTML writes & as &amp;, so both
    are turned back first.
    """
    if not text.strip():
        raise ImportFileError("This file is empty.")

    found = extract_urls_from_text(html.unescape(text.replace("\\/", "/")))
    posts = [url for url in found if is_post_link(url)]
    if not posts:
        raise ImportFileError(NO_POSTS if found else NO_LINKS)
    return [{"url": url, "platform": detect_platform(url)} for url in posts]

"""
Detects which platform a recipe link is from, and pulls candidate
recipe links out of a bulk data-export file for the backlog-import flow.
"""

import re
from urllib.parse import urlsplit

NOT_A_RECIPE_LINK = (
    "That doesn't look like a link to a TikTok or Instagram video, reel or post. "
    "Copy the link from the app's Share menu and paste it here."
)

# tiktokv.com is the address TikTok's own data download uses for the video links in it.
TIKTOK_PATTERN = re.compile(r"https?://(?:[\w-]+\.)?tiktokv?\.com/\S+", re.IGNORECASE)
INSTAGRAM_PATTERN = re.compile(r"https?://(?:[\w-]+\.)?instagram\.com/\S+", re.IGNORECASE)


def detect_platform(url: str) -> str:
    if TIKTOK_PATTERN.match(url.strip()):
        return "tiktok"
    if INSTAGRAM_PATTERN.match(url.strip()):
        return "instagram"
    raise ValueError(NOT_A_RECIPE_LINK)


def _clean_url(raw: str) -> str:
    return raw.rstrip('",.;)\']')


def tidy_link(raw: str) -> str:
    """A link as it was found in some text: trailing punctuation removed, https:// added if missing."""
    link = _clean_url(raw)
    if not re.match(r"https?://", link, re.IGNORECASE):
        link = "https://" + link
    return link


# A link inside pasted text. The https:// may be missing (address bars hide it), but the
# link must start on its own: not in the middle of another address such as
# https://example.com/?u=tiktok.com/..., and not at the end of another host name.
LINK_IN_TEXT_PATTERN = re.compile(
    r"(?<![\w./@=?&%-])((?:https?://)?(?:[\w-]+\.)?(?:tiktokv?|instagram)\.com/\S+)",
    re.IGNORECASE,
)


def find_recipe_link(text: str) -> str:
    """
    Return the one TikTok or Instagram link inside whatever was pasted: a bare link, a
    link with the share-sheet words around it, or a link without its https://.
    Raises ValueError when there is no link, or when there is more than one.
    """
    links = []
    for match in LINK_IN_TEXT_PATTERN.findall(text or ""):
        link = tidy_link(match)
        if link not in links:
            links.append(link)

    if not links:
        raise ValueError(NOT_A_RECIPE_LINK)
    if len(links) > 1:
        raise ValueError("That is more than one link. Paste one link at a time, or use the bulk import for many.")
    return links[0]


# A link inside a data-export file. Unlike a pasted link it can sit right against markup, so it
# stops at whitespace, a quote or the start of a tag: a link in HTML or in minified JSON ends where
# the link ends, instead of running on into the text after it.
LINK_IN_FILE_PATTERN = re.compile(
    r"(?<![\w./@=?&%-])((?:https?://)?(?:[\w-]+\.)?(?:tiktokv?|instagram)\.com/[^\s\"'<>\\]+)",
    re.IGNORECASE,
)


def extract_urls_from_text(text: str) -> list:
    """Every TikTok and Instagram link in the text, each one once, in the order they appear."""
    found = {}
    for match in LINK_IN_FILE_PATTERN.findall(text):
        found[tidy_link(match)] = None
    return list(found)


# A link to one post or reel: /p/<code>, /reel/<code>, /reels/<code> or /tv/<code>, with an optional
# /<username>/ in front, plus the share links the app makes: /share/<code> and /share/reel/<code>.
INSTAGRAM_POST_PATH = re.compile(
    r"/(?:(?:[\w.]+/)?(?:p|reels?|tv)|share(?:/(?:p|reels?|tv))?)/(?!audio/)[\w-]+",
    re.IGNORECASE,
)


# A TikTok link to one video or photo post: /@user/video/<id>, /@user/photo/<id>, /v/<id>.html,
# /t/<code>, and /share/video/<id>, which is how TikTok's data download writes its links. The links
# from the share sheet, vm.tiktok.com/<code> and vt.tiktok.com/<code>, have only a code in the path.
TIKTOK_POST_PATH = re.compile(r"/(?:@[\w.-]+/(?:video|photo)/\d+|t/[\w-]+|v/\d+|share/video/\d+)", re.IGNORECASE)
TIKTOK_SHORT_LINK_HOSTS = ("vm.tiktok.com", "vt.tiktok.com")


def is_post_link(url: str) -> bool:
    """
    True when the link goes to one post, reel or video, and not to a profile, a hashtag, a sound, a
    place or a story, or to some other site. The link is judged by its address, not by asking the
    site.
    """
    try:
        platform = detect_platform(url)
    except ValueError:
        return False
    parts = urlsplit(url)
    if platform == "instagram":
        return bool(INSTAGRAM_POST_PATH.match(parts.path))
    if parts.hostname in TIKTOK_SHORT_LINK_HOSTS:
        return bool(re.match(r"/[\w-]+", parts.path))
    return bool(TIKTOK_POST_PATH.match(parts.path))


def tiktok_web_link(url: str):
    """
    The ordinary web link for a link written the way TikTok's data download writes them, such as
    https://www.tiktokv.com/share/video/7123456789/. None for any other link.
    """
    if not TIKTOK_PATTERN.match(url.strip()):
        return None
    match = re.match(r"/share/video/(\d+)", urlsplit(url).path, re.IGNORECASE)
    return f"https://www.tiktok.com/@_/video/{match.group(1)}" if match else None

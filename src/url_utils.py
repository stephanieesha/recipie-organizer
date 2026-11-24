"""
Detects which platform a recipe link is from, and pulls candidate
recipe links out of a bulk data-export file for the backlog-import flow.
"""

import re

NOT_A_RECIPE_LINK = (
    "That doesn't look like a link to a TikTok or Instagram video, reel or post. "
    "Copy the link from the app's Share menu and paste it here."
)

TIKTOK_PATTERN = re.compile(r"https?://(?:[\w-]+\.)?tiktok\.com/\S+", re.IGNORECASE)
INSTAGRAM_PATTERN = re.compile(r"https?://(?:[\w-]+\.)?instagram\.com/\S+", re.IGNORECASE)


def detect_platform(url: str) -> str:
    if TIKTOK_PATTERN.match(url.strip()):
        return "tiktok"
    if INSTAGRAM_PATTERN.match(url.strip()):
        return "instagram"
    raise ValueError(NOT_A_RECIPE_LINK)


def _clean_url(raw: str) -> str:
    return raw.rstrip('",.;)\']')


# A link inside pasted text. The https:// may be missing (address bars hide it), but the
# link must start on its own: not in the middle of another address such as
# https://example.com/?u=tiktok.com/..., and not at the end of another host name.
LINK_IN_TEXT_PATTERN = re.compile(
    r"(?<![\w./@=?&%-])((?:https?://)?(?:[\w-]+\.)?(?:tiktok|instagram)\.com/\S+)",
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
        link = _clean_url(match)
        if not re.match(r"https?://", link, re.IGNORECASE):
            link = "https://" + link
        if link not in links:
            links.append(link)

    if not links:
        raise ValueError(NOT_A_RECIPE_LINK)
    if len(links) > 1:
        raise ValueError("That is more than one link. Paste one link at a time, or use the bulk import for many.")
    return links[0]


def extract_urls_from_text(text: str) -> list:
    found = set()
    for pattern in (TIKTOK_PATTERN, INSTAGRAM_PATTERN):
        for match in pattern.findall(text):
            found.add(_clean_url(match))
    return sorted(found)

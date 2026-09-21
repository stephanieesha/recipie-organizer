"""
Detects which platform a recipe link is from, and pulls candidate
recipe links out of a bulk data-export file for the backlog-import flow.
"""

import re

TIKTOK_PATTERN = re.compile(r"https?://(?:www\.|vm\.)?tiktok\.com/\S+", re.IGNORECASE)
INSTAGRAM_PATTERN = re.compile(r"https?://(?:www\.)?instagram\.com/\S+", re.IGNORECASE)


def detect_platform(url: str) -> str:
    if TIKTOK_PATTERN.match(url.strip()):
        return "tiktok"
    if INSTAGRAM_PATTERN.match(url.strip()):
        return "instagram"
    raise ValueError("Only TikTok and Instagram links are supported")


def _clean_url(raw: str) -> str:
    return raw.rstrip('",.;)\']')


def extract_urls_from_text(text: str) -> list:
    found = set()
    for pattern in (TIKTOK_PATTERN, INSTAGRAM_PATTERN):
        for match in pattern.findall(text):
            found.add(_clean_url(match))
    return sorted(found)

"""
Reads notes someone pastes in, copied out of a notes app or a document.

A line that only says ---, *** or ___ separates one note from the next. Each note is one of these:
- a link to a TikTok or Instagram post with at most a few words beside it, or a list of several such
  links, which are imported like any other link;
- a recipe written out, with or without the link to the post it came from, which is saved as it is
  written;
- neither, which is left out and counted.
"""

import re

from import_parser import ImportFileError
from url_utils import LINK_IN_FILE_PATTERN, detect_platform, extract_urls_from_text, link_key

# A note with at least this many characters beside its links is a recipe written out, not a link
# with a comment. One with more than the most is not one recipe but several notes never separated.
MIN_RECIPE_CHARS = 80
MAX_RECIPE_CHARS = 5000

NOTHING_TO_IMPORT = (
    "Nothing in these notes can be imported. A note needs a link to a TikTok or Instagram post, "
    f"or a whole recipe written out ({MIN_RECIPE_CHARS} to {MAX_RECIPE_CHARS:,} characters). Put a line "
    "that only says --- between one note and the next."
)

NOTE_SEPARATOR = re.compile(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$", re.MULTILINE)


def note_key(text: str) -> str:
    """What identifies a written note: its words, however they are spaced or capitalised."""
    return "note:" + " ".join(text.lower().split())


def item_key(item: dict) -> str:
    """What identifies the recipe an item would save: the post its link goes to, else its text."""
    return link_key(item["url"]) if item["url"] else note_key(item["text"])


def note_title(text: str) -> str:
    """The first line of a note that has words in it, to tell the notes apart in a list."""
    for line in text.split("\n"):
        words = " ".join(LINK_IN_FILE_PATTERN.sub(" ", line).split()).strip("#*_>- ")
        if words:
            return words[:80]
    return "Recipe from notes"


def read_notes(text: str):
    """
    What can be imported from the notes, in the order it appears, as (items, left_out). A link is
    {"url", "platform"}. A recipe written out is {"kind": "note", "text", "title", "url", "platform"},
    where url is the link of the post it came from, or empty, and platform is "notes" when there
    is no link. left_out counts the notes that were neither. Each recipe is listed once.
    Raises ImportFileError, with a message for the person, when there is nothing to import.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    items = {}
    left_out = 0
    for chunk in NOTE_SEPARATOR.split(text):
        note = chunk.strip()
        if not note:
            continue
        found = _items_in(note)
        if not found:
            left_out += 1
        for item in found:
            key = item_key(item)
            # A recipe written out is better than a bare link to the same post.
            if key not in items or ("kind" in item and "kind" not in items[key]):
                items[key] = item

    if not items:
        raise ImportFileError(NOTHING_TO_IMPORT)
    return list(items.values()), left_out


def _items_in(note: str) -> list:
    links = {}
    for url in extract_urls_from_text(note):
        key = link_key(url)
        if key:
            links.setdefault(key, url)
    words = " ".join(LINK_IN_FILE_PATTERN.sub(" ", note).split())

    if len(links) <= 1 and MIN_RECIPE_CHARS <= len(words) and len(note) <= MAX_RECIPE_CHARS:
        url = next(iter(links.values()), "")
        return [{
            "kind": "note", "text": note, "title": note_title(note), "url": url,
            "platform": detect_platform(url) if url else "notes",
        }]
    return [{"url": url, "platform": detect_platform(url)} for url in links.values()]

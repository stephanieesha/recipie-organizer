"""
Reading pasted notes: which notes are links, which are recipes written out, and which are left out.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from import_parser import ImportFileError  # noqa: E402
from notes_parser import (  # noqa: E402
    MAX_RECIPE_CHARS, MIN_RECIPE_CHARS, NOTHING_TO_IMPORT, item_key, note_key, note_title, read_notes,
)
from url_utils import link_key  # noqa: E402

REEL = "https://www.instagram.com/reel/DQ6rx2JDxFR/"
POST = "https://www.instagram.com/p/fA9uwTtkSN/"
TIKTOK = "https://www.tiktok.com/@chef/video/7123456789"
PROFILE = "https://www.instagram.com/chef_one/"

RECIPE = (
    "Garlic noodles\n\n"
    "Ingredients: 200g noodles, 4 cloves garlic, 2 tbsp soy sauce, 2 tbsp butter\n"
    "Boil the noodles. Fry the garlic in the butter, add the soy sauce and toss it all together."
)


def link(url, platform):
    return {"url": url, "platform": platform}


def note(text, url="", platform="notes", title="Garlic noodles"):
    return {"kind": "note", "text": text, "title": title, "url": url, "platform": platform}


def words(count):
    """Text with exactly this many characters and no link in it."""
    return "a" * count


# ---------- one note: a link, a recipe written out, or neither ----------

def test_a_note_that_is_only_a_link_is_that_link():
    assert read_notes(REEL) == ([link(REEL, "instagram")], 0)


def test_a_tiktok_link_is_a_link_too():
    assert read_notes(TIKTOK) == ([link(TIKTOK, "tiktok")], 0)


def test_a_link_with_a_few_words_beside_it_is_still_just_a_link():
    assert read_notes("Try this one on Friday\n" + REEL) == ([link(REEL, "instagram")], 0)


def test_a_link_written_without_its_https_is_found():
    assert read_notes("www.instagram.com/reel/DQ6rx2JDxFR/") == ([link("https://www.instagram.com/reel/DQ6rx2JDxFR/", "instagram")], 0)


def test_a_recipe_written_out_is_saved_as_a_note_with_no_link():
    assert read_notes(RECIPE) == ([note(RECIPE)], 0)


def test_a_recipe_written_out_keeps_the_link_it_came_from():
    text = RECIPE + "\nSaved from " + TIKTOK
    assert read_notes(text) == ([note(text, TIKTOK, "tiktok")], 0)


def test_a_recipe_with_an_instagram_link_keeps_that_link_and_platform():
    text = REEL + "\n" + RECIPE
    assert read_notes(text) == ([note(text, REEL, "instagram")], 0)


def test_a_note_with_several_links_is_a_list_of_links_whatever_else_it_says():
    text = RECIPE + "\n" + REEL + "\n" + TIKTOK
    assert read_notes(text) == ([link(REEL, "instagram"), link(TIKTOK, "tiktok")], 0)


def test_one_link_written_two_ways_in_a_note_is_still_one_link_so_the_note_is_a_recipe():
    text = RECIPE + "\n" + REEL + "\n" + "https://www.instagram.com/p/DQ6rx2JDxFR/?igsh=abc"
    assert read_notes(text) == ([note(text, REEL, "instagram")], 0)


def test_a_list_of_links_one_to_a_line_is_each_link():
    text = f"{REEL}\n{POST}\n{TIKTOK}"
    assert read_notes(text)[0] == [link(REEL, "instagram"), link(POST, "instagram"), link(TIKTOK, "tiktok")]


def test_a_note_with_neither_a_link_nor_enough_words_is_left_out_and_counted():
    with pytest.raises(ImportFileError):
        read_notes("buy butter")
    assert read_notes("buy butter\n---\n" + REEL) == ([link(REEL, "instagram")], 1)


def test_a_link_that_is_not_one_post_is_not_a_link():
    assert read_notes(PROFILE + "\n---\n" + REEL) == ([link(REEL, "instagram")], 1)


def test_a_profile_link_in_a_recipe_does_not_make_it_a_recipe_from_that_link():
    text = RECIPE + "\n" + PROFILE
    assert read_notes(text) == ([note(text)], 0)


# ---------- how much has to be written ----------

def test_the_words_beside_the_links_have_to_reach_the_minimum_to_be_a_recipe():
    assert MIN_RECIPE_CHARS == 80
    just_short = words(MIN_RECIPE_CHARS - 1) + "\n" + REEL
    just_enough = words(MIN_RECIPE_CHARS) + "\n" + REEL
    assert read_notes(just_short)[0] == [link(REEL, "instagram")]
    assert read_notes(just_enough)[0] == [note(just_enough, REEL, "instagram", title=words(MIN_RECIPE_CHARS))]


def test_the_minimum_counts_words_not_spaces_or_line_breaks():
    # 40 + 38 letters and the one space they are collapsed to make 79, however much space is between them
    padded = "a" * 40 + " " * 30 + "\n\n\n" + "a" * 38
    assert read_notes(padded + "\n" + REEL)[0] == [link(REEL, "instagram")]
    assert read_notes(padded + "a\n" + REEL)[0][0]["kind"] == "note"


def test_the_words_on_either_side_of_a_link_do_not_run_together():
    # 39 + 38 letters, the quotes round the link and the two spaces that stand for it make 80
    quoted = words(39) + '"' + REEL + '"' + words(38)
    assert read_notes(quoted)[0] == [note(quoted, REEL, "instagram", title=words(39) + '" "' + words(38))]


def test_a_long_link_does_not_count_as_words():
    long_link = REEL + "?igsh=" + "x" * 200
    assert read_notes("Try this one\n" + long_link)[0] == [link(long_link, "instagram")]


def test_a_recipe_can_be_as_long_as_the_most_but_no_longer():
    assert MAX_RECIPE_CHARS == 5000
    longest = "word " * (MAX_RECIPE_CHARS // 5)
    assert len(longest.strip()) == MAX_RECIPE_CHARS - 1
    exactly_the_most = longest.strip() + "x"
    assert len(exactly_the_most) == MAX_RECIPE_CHARS
    assert read_notes(exactly_the_most)[0][0]["kind"] == "note"
    with pytest.raises(ImportFileError):
        read_notes(exactly_the_most + "x")


def test_the_most_counts_the_links_in_the_note_too():
    long_link = REEL + "?igsh=" + "x" * MAX_RECIPE_CHARS
    assert read_notes(RECIPE + "\n" + long_link) == ([link(long_link, "instagram")], 0)


def test_a_note_too_long_to_be_one_recipe_still_gives_its_link():
    too_long = "word " * 1100
    assert read_notes(too_long + REEL) == ([link(REEL, "instagram")], 0)
    assert read_notes(too_long + "\n---\n" + REEL) == ([link(REEL, "instagram")], 1)


# ---------- separating the notes ----------

@pytest.mark.parametrize("separator", ["---", "***", "___", "-----", "  ---  ", "\t***", "---\t"])
def test_a_line_of_dashes_stars_or_underscores_separates_two_notes(separator):
    assert read_notes(f"{REEL}\n{separator}\n{TIKTOK}") == ([link(REEL, "instagram"), link(TIKTOK, "tiktok")], 0)
    assert read_notes(f"{RECIPE}\n{separator}\n{REEL}")[0] == [note(RECIPE), link(REEL, "instagram")]


@pytest.mark.parametrize("not_a_separator", ["--", "**", "__", "- - -", "---x", "x---", "a --- b", "-*-", "- -- -"])
def test_other_lines_do_not_separate_notes(not_a_separator):
    text = f"{RECIPE}\n{not_a_separator}\n{REEL}"
    assert read_notes(text) == ([note(text, REEL, "instagram")], 0)


def test_windows_and_old_mac_line_breaks_separate_notes_too():
    assert read_notes(f"{RECIPE}\r\n---\r\n{REEL}")[0] == [note(RECIPE), link(REEL, "instagram")]
    assert read_notes(f"{RECIPE}\r---\r{REEL}")[0] == [note(RECIPE), link(REEL, "instagram")]


def test_the_text_of_a_note_has_plain_line_breaks_and_no_blank_ends():
    items, _ = read_notes("\r\n\r\n" + RECIPE.replace("\n", "\r\n") + "\r\n\r\n---\r\n" + REEL)
    assert items[0]["text"] == RECIPE


def test_empty_notes_between_separators_are_not_counted_as_left_out():
    assert read_notes(f"---\n\n---\n{REEL}\n---\n---\n   \n---\n") == ([link(REEL, "instagram")], 0)


def test_notes_come_out_in_the_order_they_were_written():
    items, left_out = read_notes(f"{TIKTOK}\n---\n{RECIPE}\n---\n{REEL}\n---\nbuy butter\n---\n{POST}")
    assert items == [link(TIKTOK, "tiktok"), note(RECIPE), link(REEL, "instagram"), link(POST, "instagram")]
    assert left_out == 1


# ---------- the same recipe twice ----------

def test_the_same_link_in_two_notes_is_listed_once():
    assert read_notes(f"{REEL}\n---\n{REEL}")[0] == [link(REEL, "instagram")]


def test_the_same_post_written_two_ways_is_listed_once_the_first_way():
    other = "https://www.instagram.com/p/DQ6rx2JDxFR/?igsh=abc"
    assert read_notes(f"{REEL}\n---\n{other}")[0] == [link(REEL, "instagram")]


def test_the_same_recipe_written_out_twice_is_listed_once_however_it_is_spaced_or_capitalised():
    again = RECIPE.upper().replace("\n", "\n\n  ")
    assert read_notes(f"{RECIPE}\n---\n{again}")[0] == [note(RECIPE)]


def test_two_different_recipes_are_both_listed():
    other = RECIPE.replace("Garlic noodles", "Chili noodles")
    assert [i["title"] for i in read_notes(f"{RECIPE}\n---\n{other}")[0]] == ["Garlic noodles", "Chili noodles"]


def test_a_recipe_written_out_replaces_a_bare_link_to_the_same_post_where_the_link_was():
    with_recipe = RECIPE + "\n" + TIKTOK
    items, _ = read_notes(f"{REEL}\n---\n{TIKTOK}\n---\n{POST}\n---\n{with_recipe}")
    assert items == [link(REEL, "instagram"), note(with_recipe, TIKTOK, "tiktok"), link(POST, "instagram")]


def test_a_bare_link_does_not_replace_a_recipe_written_out_for_the_same_post():
    with_recipe = RECIPE + "\n" + TIKTOK
    assert read_notes(f"{with_recipe}\n---\n{TIKTOK}")[0] == [note(with_recipe, TIKTOK, "tiktok")]


def test_the_first_of_two_recipes_written_out_for_the_same_post_is_kept():
    first = RECIPE + "\n" + TIKTOK
    second = RECIPE.replace("Garlic noodles", "Chili noodles") + "\n" + TIKTOK
    assert read_notes(f"{first}\n---\n{second}")[0] == [note(first, TIKTOK, "tiktok")]


# ---------- nothing to import ----------

@pytest.mark.parametrize("text", ["", "   \n\n ", "---", "---\n***\n___", "buy butter and eggs", PROFILE, "words " + PROFILE + " more"])
def test_notes_with_nothing_to_import_are_refused_with_a_message_for_the_person(text):
    with pytest.raises(ImportFileError) as error:
        read_notes(text)
    assert str(error.value) == NOTHING_TO_IMPORT


def test_the_message_says_what_a_note_needs_and_how_to_separate_notes():
    assert "TikTok or Instagram post" in NOTHING_TO_IMPORT
    assert "80 to 5,000 characters" in NOTHING_TO_IMPORT
    assert "--- between one note and the next" in NOTHING_TO_IMPORT


# ---------- the title of a note ----------

@pytest.mark.parametrize("text,title", [
    ("Garlic noodles\nmore", "Garlic noodles"),
    ("\n\n  Garlic   noodles  \nmore", "Garlic noodles"),
    ("# Garlic noodles", "Garlic noodles"),
    ("## Garlic noodles ##", "Garlic noodles"),
    ("**Garlic noodles**", "Garlic noodles"),
    ("_Garlic noodles_", "Garlic noodles"),
    ("- Garlic noodles", "Garlic noodles"),
    ("> Garlic noodles", "Garlic noodles"),
    (TIKTOK + "\nGarlic noodles", "Garlic noodles"),
    ("Garlic noodles " + TIKTOK, "Garlic noodles"),
    ("###\n***bold\nGarlic noodles", "bold"),
    ("#" * 100, "Recipe from notes"),
    ("", "Recipe from notes"),
    (REEL, "Recipe from notes"),
    ("Garlic-noodles - the best", "Garlic-noodles - the best"),
    ("x" * 100, "x" * 80),
])
def test_the_title_is_the_first_line_with_words_in_it(text, title):
    assert note_title(text) == title


def test_the_title_of_a_note_in_the_list_is_its_first_line():
    assert read_notes("# Garlic noodles\n" + RECIPE)[0][0]["title"] == "Garlic noodles"


# ---------- what identifies a recipe ----------

def test_a_note_is_identified_by_its_words_however_they_are_spaced_or_capitalised():
    assert note_key("Garlic  noodles\n4 cloves") == note_key("garlic noodles 4 CLOVES")
    assert note_key("Garlic noodles") != note_key("Garlic noodle")
    assert note_key("Garlic noodles").startswith("note:")


def test_an_item_is_identified_by_its_post_or_else_by_its_words():
    assert item_key(link(REEL, "instagram")) == link_key(REEL)
    assert item_key(note(RECIPE + REEL, REEL, "instagram")) == link_key(REEL)
    assert item_key(note(RECIPE)) == note_key(RECIPE)


@pytest.mark.parametrize("text", [
    RECIPE,
    RECIPE + "\n" + TIKTOK,
    "# Chili\r\n" + RECIPE.replace("\n", "\r\n") + "\r\n" + REEL,
])
def test_reading_the_text_of_a_note_again_gives_the_same_note(text):
    items, _ = read_notes(text)
    assert read_notes(items[0]["text"]) == (items, 0)

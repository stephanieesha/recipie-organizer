import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from db import get_connection, init_db
from recipe_storage import (
    add_recipe, update_recipe_extracted, mark_recipe_needs_manual,
    update_recipe_manual, get_recipes, get_recipe, delete_recipe,
    set_recipe_thumbnail, set_recipe_category, get_recipes_by_category,
    saved_links, RecipeNotFound,
)


@pytest.fixture
def conn():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        connection = get_connection(db_path)
        yield connection
        connection.close()


def test_add_recipe_starts_as_pending(conn):
    recipe = add_recipe(conn, "https://www.tiktok.com/@x/video/1", "tiktok")
    assert recipe["status"] == "pending"
    assert recipe["ingredients"] == []
    assert recipe["directions"] == []


def test_add_recipe_with_caption(conn):
    recipe = add_recipe(conn, "https://www.instagram.com/reel/x/", "instagram", caption_raw="4 eggs, scramble them")
    assert recipe["caption_raw"] == "4 eggs, scramble them"


def test_update_recipe_extracted_sets_status_and_fields(conn):
    recipe = add_recipe(conn, "https://www.tiktok.com/@x/video/1", "tiktok")
    updated = update_recipe_extracted(
        conn, recipe["id"], "Scrambled Eggs", ["4 eggs", "1 tbsp butter"], ["Whisk eggs", "Cook in butter"]
    )
    assert updated["status"] == "extracted"
    assert updated["title"] == "Scrambled Eggs"
    assert updated["ingredients"] == ["4 eggs", "1 tbsp butter"]
    assert updated["directions"] == ["Whisk eggs", "Cook in butter"]


def test_extracted_recipe_persists_on_refetch(conn):
    recipe = add_recipe(conn, "https://www.tiktok.com/@x/video/1", "tiktok")
    update_recipe_extracted(conn, recipe["id"], "Test", ["a"], ["b"])

    refetched = get_recipe(conn, recipe["id"])
    assert refetched["title"] == "Test"
    assert refetched["ingredients"] == ["a"]


def test_mark_needs_manual_sets_status(conn):
    recipe = add_recipe(conn, "https://www.tiktok.com/@x/video/1", "tiktok")
    updated = mark_recipe_needs_manual(conn, recipe["id"])
    assert updated["status"] == "needs_manual"


def test_mark_needs_manual_preserves_the_link_not_deleted(conn):
    recipe = add_recipe(conn, "https://www.tiktok.com/@x/video/1", "tiktok")
    mark_recipe_needs_manual(conn, recipe["id"], caption_raw="just a dance video")

    all_recipes = get_recipes(conn)
    assert len(all_recipes) == 1
    assert all_recipes[0]["source_url"] == "https://www.tiktok.com/@x/video/1"
    assert all_recipes[0]["caption_raw"] == "just a dance video"


def test_update_recipe_manual_moves_status_to_extracted(conn):
    recipe = add_recipe(conn, "https://www.tiktok.com/@x/video/1", "tiktok")
    mark_recipe_needs_manual(conn, recipe["id"])

    updated = update_recipe_manual(conn, recipe["id"], "Hand-typed recipe", ["salt"], ["season food"])
    assert updated["status"] == "extracted"
    assert updated["title"] == "Hand-typed recipe"


def test_get_recipes_ordered_most_recent_first(conn):
    add_recipe(conn, "https://www.tiktok.com/@x/video/1", "tiktok")
    add_recipe(conn, "https://www.tiktok.com/@x/video/2", "tiktok")

    recipes = get_recipes(conn)
    assert recipes[0]["source_url"] == "https://www.tiktok.com/@x/video/2"


def test_get_recipe_raises_for_unknown_id(conn):
    with pytest.raises(RecipeNotFound):
        get_recipe(conn, 9999)


def test_delete_recipe_removes_it(conn):
    recipe = add_recipe(conn, "https://www.tiktok.com/@x/video/1", "tiktok")
    delete_recipe(conn, recipe["id"])
    assert get_recipes(conn) == []


def test_delete_raises_for_unknown_id(conn):
    with pytest.raises(RecipeNotFound):
        delete_recipe(conn, 9999)


def test_empty_recipe_list_initially(conn):
    assert get_recipes(conn) == []


def test_add_recipe_with_category_and_thumbnail(conn):
    from category_storage import add_category
    category = add_category(conn, "Desserts")
    recipe = add_recipe(
        conn, "https://www.tiktok.com/@x/video/1", "tiktok",
        category_id=category["id"], thumbnail_url="https://cdn.example.com/cover.jpg",
    )
    assert recipe["category_id"] == category["id"]
    assert recipe["category_name"] == "Desserts"
    assert recipe["thumbnail_url"] == "https://cdn.example.com/cover.jpg"


def test_recipe_with_no_category_has_null_category_fields(conn):
    recipe = add_recipe(conn, "https://www.tiktok.com/@x/video/1", "tiktok")
    assert recipe["category_id"] is None
    assert recipe["category_name"] is None


def test_set_recipe_thumbnail(conn):
    recipe = add_recipe(conn, "https://www.tiktok.com/@x/video/1", "tiktok")
    updated = set_recipe_thumbnail(conn, recipe["id"], "https://cdn.example.com/new.jpg")
    assert updated["thumbnail_url"] == "https://cdn.example.com/new.jpg"


def test_set_recipe_category(conn):
    from category_storage import add_category
    category = add_category(conn, "Soups")
    recipe = add_recipe(conn, "https://www.tiktok.com/@x/video/1", "tiktok")

    updated = set_recipe_category(conn, recipe["id"], category["id"])
    assert updated["category_id"] == category["id"]
    assert updated["category_name"] == "Soups"


def test_get_recipes_by_category_filters_correctly(conn):
    from category_storage import add_category
    cat_a = add_category(conn, "A")
    cat_b = add_category(conn, "B")
    add_recipe(conn, "https://www.tiktok.com/@x/video/1", "tiktok", category_id=cat_a["id"])
    add_recipe(conn, "https://www.tiktok.com/@x/video/2", "tiktok", category_id=cat_b["id"])
    add_recipe(conn, "https://www.tiktok.com/@x/video/3", "tiktok", category_id=cat_a["id"])

    results = get_recipes_by_category(conn, cat_a["id"])
    assert len(results) == 2
    assert all(r["category_id"] == cat_a["id"] for r in results)


def test_get_recipes_by_category_empty_for_category_with_no_recipes(conn):
    from category_storage import add_category
    category = add_category(conn, "Empty")
    assert get_recipes_by_category(conn, category["id"]) == []


# ---------- the posts a person has saved ----------

def test_saved_links_lists_each_saved_post_by_what_it_goes_to(conn):
    first = add_recipe(conn, "https://www.instagram.com/reel/AAA/", "instagram", user_id=1)
    second = add_recipe(conn, "https://www.tiktok.com/@chef/video/123", "tiktok", user_id=1)
    assert saved_links(conn, user_id=1) == {"instagram:AAA": first["id"], "tiktok:123": second["id"]}


def test_saved_links_only_lists_that_persons_recipes(conn):
    add_recipe(conn, "https://www.instagram.com/reel/AAA/", "instagram", user_id=1)
    mine = add_recipe(conn, "https://www.instagram.com/reel/BBB/", "instagram", user_id=2)
    assert saved_links(conn, user_id=2) == {"instagram:BBB": mine["id"]}


def test_saved_links_without_a_person_lists_every_recipe(conn):
    add_recipe(conn, "https://www.instagram.com/reel/AAA/", "instagram", user_id=1)
    add_recipe(conn, "https://www.instagram.com/reel/BBB/", "instagram", user_id=2)
    assert set(saved_links(conn)) == {"instagram:AAA", "instagram:BBB"}


def test_a_post_saved_twice_is_listed_with_its_oldest_recipe(conn):
    older = add_recipe(conn, "https://www.instagram.com/reel/AAA/", "instagram", user_id=1)
    add_recipe(conn, "https://www.instagram.com/p/AAA/?igsh=1", "instagram", user_id=1)
    assert saved_links(conn, user_id=1) == {"instagram:AAA": older["id"]}


def test_saved_links_leaves_out_recipes_whose_link_is_not_one_post(conn):
    add_recipe(conn, "https://www.instagram.com/chef_one/", "instagram", user_id=1)
    add_recipe(conn, "not a link at all", "instagram", user_id=1)
    add_recipe(conn, "", "instagram", user_id=1)
    assert saved_links(conn, user_id=1) == {}


def test_a_removed_recipe_is_no_longer_saved(conn):
    recipe = add_recipe(conn, "https://www.instagram.com/reel/AAA/", "instagram", user_id=1)
    delete_recipe(conn, recipe["id"], user_id=1)
    assert saved_links(conn, user_id=1) == {}

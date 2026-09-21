import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from db import get_connection, init_db
from category_storage import (
    add_category, get_categories, get_category, delete_category,
    CategoryNotFound, CategoryAlreadyExists,
)
from recipe_storage import add_recipe, get_recipe


@pytest.fixture
def conn():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        connection = get_connection(db_path)
        yield connection
        connection.close()


def test_add_category_returns_it_with_id(conn):
    category = add_category(conn, "Potatoes")
    assert category["id"] is not None
    assert category["name"] == "Potatoes"


def test_add_category_strips_whitespace(conn):
    category = add_category(conn, "  Desserts  ")
    assert category["name"] == "Desserts"


def test_duplicate_category_name_rejected(conn):
    add_category(conn, "Soups")
    with pytest.raises(CategoryAlreadyExists):
        add_category(conn, "Soups")


def test_get_categories_includes_recipe_count(conn):
    category = add_category(conn, "Chicken")
    add_recipe(conn, "https://www.tiktok.com/@x/video/1", "tiktok", category_id=category["id"])
    add_recipe(conn, "https://www.tiktok.com/@x/video/2", "tiktok", category_id=category["id"])

    categories = get_categories(conn)
    chicken = next(c for c in categories if c["name"] == "Chicken")
    assert chicken["recipe_count"] == 2


def test_get_categories_zero_count_for_empty_category(conn):
    add_category(conn, "Empty")
    categories = get_categories(conn)
    assert categories[0]["recipe_count"] == 0


def test_get_categories_sorted_alphabetically(conn):
    add_category(conn, "Zucchini")
    add_category(conn, "Apples")
    categories = get_categories(conn)
    assert [c["name"] for c in categories] == ["Apples", "Zucchini"]


def test_get_category_raises_for_unknown_id(conn):
    with pytest.raises(CategoryNotFound):
        get_category(conn, 9999)


def test_delete_category_removes_it(conn):
    category = add_category(conn, "Temp")
    delete_category(conn, category["id"])
    assert get_categories(conn) == []


def test_delete_category_unassigns_recipes_rather_than_deleting_them(conn):
    category = add_category(conn, "Snacks")
    recipe = add_recipe(conn, "https://www.tiktok.com/@x/video/1", "tiktok", category_id=category["id"])

    delete_category(conn, category["id"])

    refetched = get_recipe(conn, recipe["id"])
    assert refetched["category_id"] is None


def test_delete_raises_for_unknown_id(conn):
    with pytest.raises(CategoryNotFound):
        delete_category(conn, 9999)

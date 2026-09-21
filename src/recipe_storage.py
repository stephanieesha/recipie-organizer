"""
Recipe storage. status tracks where a recipe is in its lifecycle:
- 'pending': link saved, no caption/extraction yet (Instagram links
  waiting on a manually pasted caption)
- 'extracted': successfully parsed into ingredients/directions
- 'needs_manual': extraction ran but found no recipe, or failed -
  the link and any caption are kept so it can be filled in by hand
  rather than losing the saved link entirely
"""

import json
import sqlite3


class RecipeNotFound(Exception):
    pass


def _row_to_recipe(row: sqlite3.Row) -> dict:
    recipe = dict(row)
    recipe["ingredients"] = json.loads(recipe["ingredients_json"]) if recipe["ingredients_json"] else []
    recipe["directions"] = json.loads(recipe["directions_json"]) if recipe["directions_json"] else []
    del recipe["ingredients_json"]
    del recipe["directions_json"]
    return recipe


def add_recipe(conn: sqlite3.Connection, source_url: str, platform: str, caption_raw: str = None,
                category_id: int = None, thumbnail_url: str = None) -> dict:
    cursor = conn.execute(
        "INSERT INTO recipes (source_url, platform, caption_raw, status, category_id, thumbnail_url) VALUES (?, ?, ?, 'pending', ?, ?)",
        (source_url, platform, caption_raw, category_id, thumbnail_url),
    )
    conn.commit()
    return get_recipe(conn, cursor.lastrowid)


def set_recipe_thumbnail(conn: sqlite3.Connection, recipe_id: int, thumbnail_url: str) -> dict:
    conn.execute("UPDATE recipes SET thumbnail_url = ? WHERE id = ?", (thumbnail_url, recipe_id))
    conn.commit()
    return get_recipe(conn, recipe_id)


def set_recipe_category(conn: sqlite3.Connection, recipe_id: int, category_id: int) -> dict:
    conn.execute("UPDATE recipes SET category_id = ? WHERE id = ?", (category_id, recipe_id))
    conn.commit()
    return get_recipe(conn, recipe_id)


def update_recipe_extracted(conn: sqlite3.Connection, recipe_id: int, title: str, ingredients: list, directions: list) -> dict:
    conn.execute(
        """
        UPDATE recipes
        SET title = ?, ingredients_json = ?, directions_json = ?, status = 'extracted'
        WHERE id = ?
        """,
        (title, json.dumps(ingredients), json.dumps(directions), recipe_id),
    )
    conn.commit()
    return get_recipe(conn, recipe_id)


def mark_recipe_needs_manual(conn: sqlite3.Connection, recipe_id: int, caption_raw: str = None) -> dict:
    if caption_raw is not None:
        conn.execute("UPDATE recipes SET status = 'needs_manual', caption_raw = ? WHERE id = ?", (caption_raw, recipe_id))
    else:
        conn.execute("UPDATE recipes SET status = 'needs_manual' WHERE id = ?", (recipe_id,))
    conn.commit()
    return get_recipe(conn, recipe_id)


def update_recipe_manual(conn: sqlite3.Connection, recipe_id: int, title: str, ingredients: list, directions: list) -> dict:
    conn.execute(
        """
        UPDATE recipes
        SET title = ?, ingredients_json = ?, directions_json = ?, status = 'extracted'
        WHERE id = ?
        """,
        (title, json.dumps(ingredients), json.dumps(directions), recipe_id),
    )
    conn.commit()
    return get_recipe(conn, recipe_id)


def get_recipes(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        """
        SELECT r.*, c.name as category_name
        FROM recipes r
        LEFT JOIN categories c ON c.id = r.category_id
        ORDER BY r.created_at DESC, r.id DESC
        """
    ).fetchall()
    return [_row_to_recipe(row) for row in rows]


def get_recipes_by_category(conn: sqlite3.Connection, category_id: int) -> list:
    rows = conn.execute(
        """
        SELECT r.*, c.name as category_name
        FROM recipes r
        LEFT JOIN categories c ON c.id = r.category_id
        WHERE r.category_id = ?
        ORDER BY r.created_at DESC, r.id DESC
        """,
        (category_id,),
    ).fetchall()
    return [_row_to_recipe(row) for row in rows]


def get_recipe(conn: sqlite3.Connection, recipe_id: int) -> dict:
    row = conn.execute(
        """
        SELECT r.*, c.name as category_name
        FROM recipes r
        LEFT JOIN categories c ON c.id = r.category_id
        WHERE r.id = ?
        """,
        (recipe_id,),
    ).fetchone()
    if row is None:
        raise RecipeNotFound(f"No recipe with id {recipe_id}")
    return _row_to_recipe(row)


def delete_recipe(conn: sqlite3.Connection, recipe_id: int) -> None:
    cursor = conn.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
    conn.commit()
    if cursor.rowcount == 0:
        raise RecipeNotFound(f"No recipe with id {recipe_id}")

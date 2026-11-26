"""
Recipe storage. status tracks where a recipe is in its lifecycle:
- 'pending': link saved, no caption/extraction yet (Instagram links
  waiting on a manually pasted caption)
- 'extracted': successfully parsed into ingredients/directions
- 'needs_manual': extraction ran but found no recipe, or failed -
  the link and any caption are kept so it can be filled in by hand
  rather than losing the saved link entirely

Every recipe belongs to a user. Pass user_id to limit a read or change to that
person's own recipes - someone else's recipe then behaves exactly like one that
does not exist (RecipeNotFound).
"""

import json

from url_utils import link_key


class RecipeNotFound(Exception):
    pass


def _owned_by(user_id, column: str = "user_id"):
    """SQL to add to a WHERE clause, plus its parameters, limiting it to one user's rows."""
    if user_id is None:
        return "", ()
    return f" AND {column} = ?", (user_id,)


def _row_to_recipe(row) -> dict:
    recipe = dict(row)
    recipe["ingredients"] = json.loads(recipe["ingredients_json"]) if recipe["ingredients_json"] else []
    recipe["directions"] = json.loads(recipe["directions_json"]) if recipe["directions_json"] else []
    del recipe["ingredients_json"]
    del recipe["directions_json"]
    return recipe


def add_recipe(conn, source_url: str, platform: str, caption_raw: str = None,
                category_id: int = None, thumbnail_url: str = None, user_id: int = None) -> dict:
    cursor = conn.execute(
        "INSERT INTO recipes (source_url, platform, caption_raw, status, category_id, thumbnail_url, user_id) VALUES (?, ?, ?, 'pending', ?, ?, ?)",
        (source_url, platform, caption_raw, category_id, thumbnail_url, user_id),
    )
    conn.commit()
    return get_recipe(conn, cursor.lastrowid)


def saved_links(conn, user_id: int = None) -> dict:
    """
    The posts already saved as recipes, as {link_key: recipe id}. A post saved twice is listed with
    its oldest recipe. Recipes whose link does not go to one post are left out.
    """
    owned, owner = _owned_by(user_id)
    rows = conn.execute(f"SELECT id, source_url FROM recipes WHERE 1 = 1{owned} ORDER BY id", owner).fetchall()
    saved = {}
    for row in rows:
        key = link_key(row["source_url"])
        if key:
            saved.setdefault(key, row["id"])
    return saved


def set_recipe_thumbnail(conn, recipe_id: int, thumbnail_url: str) -> dict:
    conn.execute("UPDATE recipes SET thumbnail_url = ? WHERE id = ?", (thumbnail_url, recipe_id))
    conn.commit()
    return get_recipe(conn, recipe_id)


def set_recipe_category(conn, recipe_id: int, category_id: int, user_id: int = None) -> dict:
    owned, owner = _owned_by(user_id)
    conn.execute(f"UPDATE recipes SET category_id = ? WHERE id = ?{owned}", (category_id, recipe_id) + owner)
    conn.commit()
    return get_recipe(conn, recipe_id, user_id=user_id)


def update_recipe_extracted(conn, recipe_id: int, title: str, ingredients: list, directions: list) -> dict:
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


def mark_recipe_needs_manual(conn, recipe_id: int, caption_raw: str = None) -> dict:
    if caption_raw is not None:
        conn.execute("UPDATE recipes SET status = 'needs_manual', caption_raw = ? WHERE id = ?", (caption_raw, recipe_id))
    else:
        conn.execute("UPDATE recipes SET status = 'needs_manual' WHERE id = ?", (recipe_id,))
    conn.commit()
    return get_recipe(conn, recipe_id)


def update_recipe_manual(conn, recipe_id: int, title: str, ingredients: list, directions: list,
                          user_id: int = None) -> dict:
    owned, owner = _owned_by(user_id)
    conn.execute(
        f"""
        UPDATE recipes
        SET title = ?, ingredients_json = ?, directions_json = ?, status = 'extracted'
        WHERE id = ?{owned}
        """,
        (title, json.dumps(ingredients), json.dumps(directions), recipe_id) + owner,
    )
    conn.commit()
    return get_recipe(conn, recipe_id, user_id=user_id)


def get_recipes(conn, user_id: int = None) -> list:
    owned, owner = _owned_by(user_id, "r.user_id")
    rows = conn.execute(
        f"""
        SELECT r.*, c.name as category_name
        FROM recipes r
        LEFT JOIN categories c ON c.id = r.category_id
        WHERE 1 = 1{owned}
        ORDER BY r.created_at DESC, r.id DESC
        """,
        owner,
    ).fetchall()
    return [_row_to_recipe(row) for row in rows]


def get_recipes_by_category(conn, category_id: int, user_id: int = None) -> list:
    owned, owner = _owned_by(user_id, "r.user_id")
    rows = conn.execute(
        f"""
        SELECT r.*, c.name as category_name
        FROM recipes r
        LEFT JOIN categories c ON c.id = r.category_id
        WHERE r.category_id = ?{owned}
        ORDER BY r.created_at DESC, r.id DESC
        """,
        (category_id,) + owner,
    ).fetchall()
    return [_row_to_recipe(row) for row in rows]


def get_recipe(conn, recipe_id: int, user_id: int = None) -> dict:
    owned, owner = _owned_by(user_id, "r.user_id")
    row = conn.execute(
        f"""
        SELECT r.*, c.name as category_name
        FROM recipes r
        LEFT JOIN categories c ON c.id = r.category_id
        WHERE r.id = ?{owned}
        """,
        (recipe_id,) + owner,
    ).fetchone()
    if row is None:
        raise RecipeNotFound(f"No recipe with id {recipe_id}")
    return _row_to_recipe(row)


def delete_recipe(conn, recipe_id: int, user_id: int = None) -> None:
    owned, owner = _owned_by(user_id)
    cursor = conn.execute(f"DELETE FROM recipes WHERE id = ?{owned}", (recipe_id,) + owner)
    conn.commit()
    if cursor.rowcount == 0:
        raise RecipeNotFound(f"No recipe with id {recipe_id}")

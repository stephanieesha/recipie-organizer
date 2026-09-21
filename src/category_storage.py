"""
Category storage - simple named groups recipes can belong to.
"""

from db import IntegrityError


class CategoryNotFound(Exception):
    pass


class CategoryAlreadyExists(Exception):
    pass


def add_category(conn, name: str) -> dict:
    name = name.strip()
    try:
        cursor = conn.execute("INSERT INTO categories (name) VALUES (?)", (name,))
        conn.commit()
    except IntegrityError:
        raise CategoryAlreadyExists(f"A category named '{name}' already exists")
    return get_category(conn, cursor.lastrowid)


def get_categories(conn) -> list:
    rows = conn.execute(
        """
        SELECT c.*, COUNT(r.id) as recipe_count
        FROM categories c
        LEFT JOIN recipes r ON r.category_id = c.id
        GROUP BY c.id
        ORDER BY c.name ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_category(conn, category_id: int) -> dict:
    row = conn.execute("SELECT * FROM categories WHERE id = ?", (category_id,)).fetchone()
    if row is None:
        raise CategoryNotFound(f"No category with id {category_id}")
    return dict(row)


def delete_category(conn, category_id: int) -> None:
    conn.execute("UPDATE recipes SET category_id = NULL WHERE category_id = ?", (category_id,))
    cursor = conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
    conn.commit()
    if cursor.rowcount == 0:
        raise CategoryNotFound(f"No category with id {category_id}")

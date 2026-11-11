"""
Category storage - simple named groups recipes can belong to.

Every category belongs to a user. Pass user_id to limit a read or change to
that person's own categories - someone else's category then behaves exactly
like one that does not exist (CategoryNotFound). Names are unique per user.
"""

from db import IntegrityError


class CategoryNotFound(Exception):
    pass


class CategoryAlreadyExists(Exception):
    pass


def _owned_by(user_id, column: str = "user_id"):
    """SQL to add to a WHERE clause, plus its parameters, limiting it to one user's rows."""
    if user_id is None:
        return "", ()
    return f" AND {column} = ?", (user_id,)


def add_category(conn, name: str, user_id: int = None) -> dict:
    name = name.strip()
    same_owner = "user_id IS NULL" if user_id is None else "user_id = ?"
    params = (name,) if user_id is None else (name, user_id)
    if conn.execute(f"SELECT id FROM categories WHERE name = ? AND {same_owner}", params).fetchone():
        raise CategoryAlreadyExists(f"A category named '{name}' already exists")
    try:
        cursor = conn.execute("INSERT INTO categories (name, user_id) VALUES (?, ?)", (name, user_id))
        conn.commit()
    except IntegrityError:
        conn.rollback()
        raise CategoryAlreadyExists(f"A category named '{name}' already exists")
    return get_category(conn, cursor.lastrowid)


def get_categories(conn, user_id: int = None) -> list:
    owned, owner = _owned_by(user_id, "c.user_id")
    rows = conn.execute(
        f"""
        SELECT c.*, COUNT(r.id) as recipe_count
        FROM categories c
        LEFT JOIN recipes r ON r.category_id = c.id
        WHERE 1 = 1{owned}
        GROUP BY c.id
        ORDER BY c.name ASC
        """,
        owner,
    ).fetchall()
    return [dict(row) for row in rows]


def get_category(conn, category_id: int, user_id: int = None) -> dict:
    owned, owner = _owned_by(user_id)
    row = conn.execute(f"SELECT * FROM categories WHERE id = ?{owned}", (category_id,) + owner).fetchone()
    if row is None:
        raise CategoryNotFound(f"No category with id {category_id}")
    return dict(row)


def delete_category(conn, category_id: int, user_id: int = None) -> None:
    get_category(conn, category_id, user_id=user_id)  # not theirs (or not there) -> CategoryNotFound, nothing touched
    conn.execute("UPDATE recipes SET category_id = NULL WHERE category_id = ?", (category_id,))
    conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
    conn.commit()

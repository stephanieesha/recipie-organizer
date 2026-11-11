"""
User accounts: creating them and checking a log-in. Takes a db connection as a
parameter throughout, so it can be tested against a temporary database.
"""

from werkzeug.security import generate_password_hash, check_password_hash

from db import IntegrityError


class EmailAlreadyExists(Exception):
    pass


class InvalidCredentials(Exception):
    pass


def create_user(conn, email: str, password: str) -> dict:
    try:
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash) VALUES (?, ?)",
            (email, generate_password_hash(password)),
        )
        conn.commit()
    except IntegrityError:
        conn.rollback()
        raise EmailAlreadyExists(f"An account with email '{email}' already exists")

    user = get_user_by_id(conn, cursor.lastrowid)
    _claim_unowned_rows_for_first_user(conn, user["id"])
    return user


def _claim_unowned_rows_for_first_user(conn, user_id: int) -> None:
    """Recipes and categories saved before accounts existed have no owner. The very first
    account takes them over, so nothing saved earlier is lost; later accounts start empty."""
    if conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] != 1:
        return
    conn.execute("UPDATE recipes SET user_id = ? WHERE user_id IS NULL", (user_id,))
    conn.execute("UPDATE categories SET user_id = ? WHERE user_id IS NULL", (user_id,))
    conn.commit()


def authenticate_user(conn, email: str, password: str) -> dict:
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password):
        raise InvalidCredentials("Incorrect email or password")
    return dict(row)


def get_user_by_id(conn, user_id: int) -> dict:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None

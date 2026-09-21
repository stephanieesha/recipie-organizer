"""
SQLite database layer. No accounts/auth for this app (single-user local
tool, per explicit choice) - so no user_id scoping anywhere.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "recipes.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT NOT NULL,
    platform TEXT NOT NULL,
    caption_raw TEXT,
    title TEXT,
    ingredients_json TEXT,
    directions_json TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    thumbnail_url TEXT,
    category_id INTEGER REFERENCES categories(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Columns added after the original release - ALTER TABLE ADD COLUMN keeps
# existing rows intact rather than requiring a fresh database.
MIGRATIONS = [
    ("recipes", "thumbnail_url", "TEXT"),
    ("recipes", "category_id", "INTEGER REFERENCES categories(id)"),
]


def _run_migrations(conn: sqlite3.Connection) -> None:
    for table, column, coltype in MIGRATIONS:
        existing_columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
    conn.commit()


def get_connection(db_path: Path = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = None) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _run_migrations(conn)
    finally:
        conn.close()

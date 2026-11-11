"""
Database layer.

SQLite is used for local runs and the unit tests. When the DATABASE_URL
environment variable is set (as it is in production), PostgreSQL is used
instead, through a small wrapper that behaves like the sqlite3 connection the
rest of the code was written against (execute, commit, close, lastrowid...).

Recipes and categories belong to a user (user_id); rows saved before accounts
existed have no owner and are handed to the first account that signs up.
"""

import os
import re
import sqlite3
from pathlib import Path

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # SQLite-only setups do not need the PostgreSQL driver
    psycopg = None

DB_PATH = Path(__file__).parent.parent / "data" / "recipes.db"

# Catch this instead of sqlite3.IntegrityError so both databases are covered.
IntegrityError = (sqlite3.IntegrityError,) + ((psycopg.IntegrityError,) if psycopg else ())

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    user_id INTEGER REFERENCES users(id),
    UNIQUE (user_id, name)
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
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    user_id INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS usage_counters (
    day TEXT NOT NULL,
    kind TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, kind)
);
"""

# Same tables for PostgreSQL. Timestamps stay text in the same format SQLite produces,
# so ordering and the JSON the app returns are identical on both databases.
POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
    user_id INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS recipes (
    id SERIAL PRIMARY KEY,
    source_url TEXT NOT NULL,
    platform TEXT NOT NULL,
    caption_raw TEXT,
    title TEXT,
    ingredients_json TEXT,
    directions_json TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    thumbnail_url TEXT,
    category_id INTEGER REFERENCES categories(id),
    created_at TEXT NOT NULL DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
    user_id INTEGER REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS usage_counters (
    day TEXT NOT NULL,
    kind TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, kind)
);

-- Accounts were added after the first release: bring an existing database up to date.
-- Category names are now unique per user rather than across everyone.
ALTER TABLE categories ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
ALTER TABLE recipes ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id);
ALTER TABLE categories DROP CONSTRAINT IF EXISTS categories_name_key;
CREATE UNIQUE INDEX IF NOT EXISTS categories_user_name_key ON categories (user_id, name);
"""

# Columns added after the original release - ALTER TABLE ADD COLUMN keeps
# existing rows intact rather than requiring a fresh database (SQLite only;
# PostgreSQL databases are created with the full schema).
MIGRATIONS = [
    ("recipes", "thumbnail_url", "TEXT"),
    ("recipes", "category_id", "INTEGER REFERENCES categories(id)"),
    ("recipes", "user_id", "INTEGER REFERENCES users(id)"),
    ("categories", "user_id", "INTEGER REFERENCES users(id)"),
]

# Tables whose primary key column is called id, so INSERTs can return the new id on PostgreSQL.
_TABLES_WITH_ID = {"categories", "recipes", "users"}
_INSERT_RE = re.compile(r"^\s*INSERT\s+INTO\s+(\w+)", re.IGNORECASE)


class _PgResult:
    """Looks like a sqlite3 cursor: fetchone, fetchall, lastrowid, rowcount."""

    def __init__(self, cursor, lastrowid=None):
        self._cursor = cursor
        self.lastrowid = lastrowid
        self.rowcount = cursor.rowcount

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class PgConnection:
    """A PostgreSQL connection that accepts the sqlite3-style SQL used across this app."""

    def __init__(self, dsn: str):
        self._conn = psycopg.connect(dsn, row_factory=dict_row, prepare_threshold=None)  # no server-side prepared statements, so Neon's pooled connection string works too

    def execute(self, sql: str, params=()):
        pg_sql = sql.replace("%", "%%").replace("?", "%s")
        match = _INSERT_RE.match(pg_sql)
        wants_id = bool(match) and match.group(1).lower() in _TABLES_WITH_ID and "RETURNING" not in pg_sql.upper()
        if wants_id:
            pg_sql += " RETURNING id"
        try:
            cursor = self._conn.execute(pg_sql, params)
            lastrowid = cursor.fetchone()["id"] if wants_id else None
        except psycopg.Error:
            self._conn.rollback()  # PostgreSQL refuses further work in a failed transaction
            raise
        return _PgResult(cursor, lastrowid)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def _run_migrations(conn: sqlite3.Connection) -> None:
    for table, column, coltype in MIGRATIONS:
        existing_columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
    conn.commit()
    _make_category_names_unique_per_user(conn)


def _make_category_names_unique_per_user(conn: sqlite3.Connection) -> None:
    """A database from before accounts has category names unique across everyone. SQLite
    cannot drop that rule in place, so the table is rebuilt once with the per-user rule."""
    table_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'categories'").fetchone()["sql"]
    if "UNIQUE (user_id, name)" in table_sql:
        return
    conn.executescript(
        """
        BEGIN;
        CREATE TABLE categories_rebuilt (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            user_id INTEGER REFERENCES users(id),
            UNIQUE (user_id, name)
        );
        INSERT INTO categories_rebuilt (id, name, created_at, user_id)
            SELECT id, name, created_at, user_id FROM categories;
        DROP TABLE categories;
        ALTER TABLE categories_rebuilt RENAME TO categories;
        COMMIT;
        """
    )


def get_connection(db_path: Path = None):
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        if psycopg is None:
            raise RuntimeError("DATABASE_URL is set but the PostgreSQL driver is missing: pip install 'psycopg[binary]'")
        return PgConnection(database_url)

    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = None) -> None:
    conn = get_connection(db_path)
    try:
        if isinstance(conn, PgConnection):
            conn.execute(POSTGRES_SCHEMA)
            conn.commit()
        else:
            conn.executescript(SQLITE_SCHEMA)
            conn.commit()
            _run_migrations(conn)
    finally:
        conn.close()

"""
Accounts: signing up, logging in, and - the point of having them - that one person
can never see or change another person's recipes or categories.
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import db  # noqa: E402
import limits  # noqa: E402
import app as app_module  # noqa: E402

INSTAGRAM_LINK = "https://www.instagram.com/reel/ABC123/"


@pytest.fixture
def make_client(monkeypatch):
    """Returns a function that opens a fresh browser session against a temporary database."""
    for name in ("WRITE_LIMIT_PER_MINUTE", "AUTH_LIMIT_PER_15_MIN", "DAILY_SIGNUP_LIMIT", "DAILY_AI_LIMIT"):
        monkeypatch.delenv(name, raising=False)
    limits._recent_requests.clear()
    limits._recent_auth_attempts.clear()
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(db, "DB_PATH", Path(tmpdir) / "test.db")
        db.init_db()
        app_module.app.config["TESTING"] = True
        yield app_module.app.test_client


def sign_up(client, email, password="correct-horse"):
    return client.post("/signup", data={"email": email, "password": password})


@pytest.fixture
def ada(make_client):
    client = make_client()
    assert sign_up(client, "ada@example.com").status_code == 302
    return client


@pytest.fixture
def ben(make_client, ada):  # ada signs up first, so ben is never the first account
    client = make_client()
    assert sign_up(client, "ben@example.com").status_code == 302
    return client


def add_recipe(client, **extra):
    response = client.post("/api/recipes", json={"url": INSTAGRAM_LINK, **extra})
    assert response.status_code == 201
    return response.get_json()


# ---------- logged out ----------

@pytest.mark.parametrize("page", ["/", "/categories", "/categories/1", "/recipes/1", "/bulk-review"])
def test_pages_send_a_logged_out_visitor_to_log_in(make_client, page):
    response = make_client().get(page)
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")


@pytest.mark.parametrize("method,path", [
    ("get", "/api/recipes"), ("post", "/api/recipes"), ("get", "/api/recipes/1"),
    ("put", "/api/recipes/1"), ("delete", "/api/recipes/1"),
    ("patch", "/api/recipes/1/caption"), ("patch", "/api/recipes/1/category"),
    ("post", "/api/recipes/bulk-import"),
    ("get", "/api/categories"), ("post", "/api/categories"),
    ("delete", "/api/categories/1"), ("get", "/api/categories/1/recipes"),
])
def test_every_api_route_refuses_a_logged_out_visitor(make_client, method, path):
    response = getattr(make_client(), method)(path, json={})
    assert response.status_code == 401
    assert response.get_json() == {"error": "Please log in"}


def test_every_route_except_the_public_ones_requires_login(make_client):
    """Catches a route added later without @login_required."""
    public = {"/login", "/signup", "/robots.txt"}
    client = make_client()
    for rule in app_module.app.url_map.iter_rules():
        if rule.rule in public or rule.endpoint == "static":
            continue
        path = rule.rule.replace("<int:recipe_id>", "1").replace("<int:category_id>", "1")
        method = next(m for m in ("GET", "POST", "PUT", "PATCH", "DELETE") if m in rule.methods)
        status = client.open(path, method=method).status_code
        assert status in (302, 401), f"{method} {path} answered {status} without a login"


# ---------- signing up and logging in ----------

def test_sign_up_logs_you_in(ada):
    assert ada.get("/").status_code == 200
    assert ada.get("/api/recipes").get_json() == []


def test_sign_up_rejects_a_short_password(make_client):
    client = make_client()
    assert sign_up(client, "ada@example.com", password="short").status_code == 400
    assert client.get("/api/recipes").status_code == 401


def test_sign_up_rejects_an_email_already_in_use(make_client, ada):
    response = sign_up(make_client(), "ADA@example.com")
    assert response.status_code == 400
    assert b"already exists" in response.data


def test_log_in_with_the_right_password(make_client, ada):
    client = make_client()
    response = client.post("/login", data={"email": "Ada@Example.com ", "password": "correct-horse"})
    assert response.status_code == 302
    assert client.get("/api/recipes").status_code == 200


@pytest.mark.parametrize("email,password", [("ada@example.com", "wrong-password"), ("nobody@example.com", "correct-horse")])
def test_log_in_fails_the_same_way_for_a_wrong_password_and_an_unknown_email(make_client, ada, email, password):
    client = make_client()
    response = client.post("/login", data={"email": email, "password": password})
    assert response.status_code == 401
    assert b"Incorrect email or password" in response.data
    assert client.get("/api/recipes").status_code == 401


def test_log_out_ends_the_session(ada):
    assert ada.get("/logout").status_code == 302
    assert ada.get("/api/recipes").status_code == 401


def test_log_in_returns_to_the_page_you_wanted(make_client, ada):
    client = make_client()
    response = client.post("/login?next=/categories", data={"email": "ada@example.com", "password": "correct-horse"})
    assert response.headers["Location"] == "/categories"


@pytest.mark.parametrize("target", ["https://evil.example", "//evil.example", "/\\evil.example"])
def test_log_in_never_redirects_to_another_site(make_client, ada, target):
    client = make_client()
    response = client.post("/login", query_string={"next": target}, data={"email": "ada@example.com", "password": "correct-horse"})
    assert response.headers["Location"] == "/"


def test_passwords_are_stored_hashed(make_client, ada):
    conn = db.get_connection()
    try:
        stored = conn.execute("SELECT password_hash FROM users").fetchone()["password_hash"]
    finally:
        conn.close()
    assert "correct-horse" not in stored


def test_too_many_log_in_attempts_are_slowed_down(make_client, ada, monkeypatch):
    monkeypatch.setenv("AUTH_LIMIT_PER_15_MIN", "3")
    client = make_client()
    for _ in range(3):
        assert client.post("/login", data={"email": "ada@example.com", "password": "guess"}).status_code == 401
    blocked = client.post("/login", data={"email": "ada@example.com", "password": "correct-horse"})
    assert blocked.status_code == 429
    assert client.get("/api/recipes").status_code == 401


def test_daily_sign_up_cap(make_client, monkeypatch):
    monkeypatch.setenv("DAILY_SIGNUP_LIMIT", "1")
    assert sign_up(make_client(), "ada@example.com").status_code == 302
    assert sign_up(make_client(), "ben@example.com").status_code == 429


# ---------- one person's data is invisible to another ----------

def test_recipes_are_private_to_their_owner(ada, ben):
    add_recipe(ada)
    assert len(ada.get("/api/recipes").get_json()) == 1
    assert ben.get("/api/recipes").get_json() == []


def test_someone_elses_recipe_cannot_be_read_changed_or_deleted(ada, ben):
    recipe_id = add_recipe(ada)["id"]

    assert ben.get(f"/api/recipes/{recipe_id}").status_code == 404
    assert ben.put(f"/api/recipes/{recipe_id}", json={"title": "Taken over", "ingredients": [], "directions": []}).status_code == 404
    assert ben.patch(f"/api/recipes/{recipe_id}/caption", json={"caption": "flour, eggs"}).status_code == 404
    assert ben.patch(f"/api/recipes/{recipe_id}/category", json={"category_id": None}).status_code == 404
    assert ben.delete(f"/api/recipes/{recipe_id}").status_code == 404

    untouched = ada.get(f"/api/recipes/{recipe_id}").get_json()
    assert untouched["title"] is None and untouched["status"] == "pending" and untouched["caption_raw"] is None


def test_the_owner_can_still_edit_and_delete_their_recipe(ada):
    recipe_id = add_recipe(ada)["id"]
    edited = ada.put(f"/api/recipes/{recipe_id}", json={"title": "Jollof", "ingredients": ["rice"], "directions": ["cook"]})
    assert edited.status_code == 200 and edited.get_json()["title"] == "Jollof"
    assert ada.delete(f"/api/recipes/{recipe_id}").status_code == 200
    assert ada.get("/api/recipes").get_json() == []


def test_categories_are_private_to_their_owner(ada, ben):
    category_id = ada.post("/api/categories", json={"name": "Dinner"}).get_json()["id"]
    add_recipe(ada, category_id=category_id)

    assert ben.get("/api/categories").get_json() == []
    assert ben.get(f"/api/categories/{category_id}/recipes").status_code == 404
    assert ben.delete(f"/api/categories/{category_id}").status_code == 404

    mine = ada.get("/api/categories").get_json()
    assert [(c["name"], c["recipe_count"]) for c in mine] == [("Dinner", 1)]
    assert ada.get("/api/recipes").get_json()[0]["category_name"] == "Dinner"


def test_a_recipe_cannot_be_filed_under_someone_elses_category(ada, ben):
    adas_category = ada.post("/api/categories", json={"name": "Dinner"}).get_json()["id"]

    assert ben.post("/api/recipes", json={"url": INSTAGRAM_LINK, "category_id": adas_category}).status_code == 404
    assert ben.get("/api/recipes").get_json() == []

    bens_recipe = add_recipe(ben)["id"]
    assert ben.patch(f"/api/recipes/{bens_recipe}/category", json={"category_id": adas_category}).status_code == 404
    assert ada.get("/api/categories").get_json()[0]["recipe_count"] == 0


def test_two_people_can_use_the_same_category_name(ada, ben):
    assert ada.post("/api/categories", json={"name": "Dinner"}).status_code == 201
    assert ben.post("/api/categories", json={"name": "Dinner"}).status_code == 201
    assert ada.post("/api/categories", json={"name": "Dinner"}).status_code == 400  # still unique per person


def test_bulk_import_saves_to_the_person_who_uploaded(ada, ben):
    import io
    upload = {"file": (io.BytesIO(INSTAGRAM_LINK.encode()), "export.txt")}
    summary = ada.post("/api/recipes/bulk-import", data=upload, content_type="multipart/form-data").get_json()
    assert summary["needs_caption"] == 1
    assert len(ada.get("/api/recipes").get_json()) == 1
    assert ben.get("/api/recipes").get_json() == []


# ---------- recipes saved before accounts existed ----------

def test_the_first_account_takes_over_recipes_saved_before_accounts_existed(make_client):
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO categories (name) VALUES ('Old category')")
        conn.execute("INSERT INTO recipes (source_url, platform, category_id) VALUES (?, 'instagram', 1)", (INSTAGRAM_LINK,))
        conn.commit()
    finally:
        conn.close()

    first, second = make_client(), make_client()
    sign_up(first, "ada@example.com")
    sign_up(second, "ben@example.com")

    assert len(first.get("/api/recipes").get_json()) == 1
    assert [c["name"] for c in first.get("/api/categories").get_json()] == ["Old category"]
    assert second.get("/api/recipes").get_json() == []
    assert second.get("/api/categories").get_json() == []


@pytest.mark.skipif(bool(os.environ.get("DATABASE_URL")), reason="SQLite upgrade path; PostgreSQL upgrades through its schema script")
def test_a_database_from_before_accounts_is_upgraded_without_losing_anything():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "old.db"
        old = sqlite3.connect(path)
        old.executescript("""
            CREATE TABLE categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT (datetime('now')));
            CREATE TABLE recipes (id INTEGER PRIMARY KEY AUTOINCREMENT, source_url TEXT NOT NULL, platform TEXT NOT NULL,
                caption_raw TEXT, title TEXT, ingredients_json TEXT, directions_json TEXT,
                status TEXT NOT NULL DEFAULT 'pending', thumbnail_url TEXT,
                category_id INTEGER REFERENCES categories(id), created_at TEXT NOT NULL DEFAULT (datetime('now')));
            INSERT INTO categories (name) VALUES ('Dinner');
            INSERT INTO recipes (source_url, platform, title, category_id) VALUES ('https://example.com', 'tiktok', 'Jollof', 1);
        """)
        old.close()

        db.init_db(path)
        db.init_db(path)  # running it again changes nothing

        conn = db.get_connection(path)
        try:
            recipe = conn.execute("SELECT r.title, r.user_id, c.name FROM recipes r JOIN categories c ON c.id = r.category_id").fetchone()
            assert (recipe["title"], recipe["user_id"], recipe["name"]) == ("Jollof", None, "Dinner")
            conn.execute("INSERT INTO users (email, password_hash) VALUES ('a@example.com', 'x'), ('b@example.com', 'x')")
            conn.execute("INSERT INTO categories (name, user_id) VALUES ('Dinner', 1), ('Dinner', 2)")  # per-user names now allowed
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO categories (name, user_id) VALUES ('Dinner', 1)")
        finally:
            conn.close()

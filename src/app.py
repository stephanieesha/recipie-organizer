"""
Recipe Organizer web app. Each person signs up and sees only their own recipes and categories.

Run with: python src/app.py
Then open: http://localhost:5050
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user

from db import get_connection, init_db
from limits import client_ip, max_bulk_links, too_many_auth_attempts, too_many_requests, use_ai_call, use_signup
from auth import create_user, authenticate_user, get_user_by_id, EmailAlreadyExists, InvalidCredentials
from url_utils import detect_platform, find_recipe_link
from import_parser import MAX_UPLOAD_BYTES, ImportFileError, read_export
from tiktok_oembed import fetch_tiktok_data, TikTokFetchError
from recipe_extractor import extract_recipe, NoRecipeFoundError, ExtractionError
from recipe_storage import (
    add_recipe, update_recipe_extracted, mark_recipe_needs_manual, update_recipe_manual,
    get_recipes, get_recipe, delete_recipe, get_recipes_by_category, set_recipe_category, RecipeNotFound,
)
from category_storage import (
    add_category, get_categories, get_category, delete_category,
    CategoryNotFound, CategoryAlreadyExists,
)

ROOT = Path(__file__).parent.parent
app = Flask(__name__, template_folder=str(ROOT / "templates"))

# The secret key signs the log-in cookie. Render sets RENDER=true on its own, so a deployment
# without a real key refuses to start instead of running with one anybody could read here.
DEV_SECRET_KEY = "dev-only-insecure-key-change-in-env"
app.secret_key = os.environ.get("FLASK_SECRET_KEY", DEV_SECRET_KEY)
if os.environ.get("RENDER") or os.environ.get("PRODUCTION", "").lower() == "true":
    if app.secret_key == DEV_SECRET_KEY:
        raise RuntimeError("Set FLASK_SECRET_KEY to a long random value before running in production")
    app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
# A bigger upload is refused before the server has read all of it.
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

init_db()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


class User(UserMixin):
    def __init__(self, user_row):
        self.id = str(user_row["id"])
        self.email = user_row["email"]


@login_manager.user_loader
def load_user(user_id):
    conn = get_connection()
    try:
        row = get_user_by_id(conn, int(user_id))
        return User(row) if row else None
    finally:
        conn.close()


@login_manager.unauthorized_handler
def not_logged_in():
    # Pages go to the log-in screen; API calls get a plain 401 the page's JavaScript can read.
    if request.path.startswith("/api/"):
        return jsonify({"error": "Please log in"}), 401
    return redirect(url_for("login", next=request.path))


def _user_id() -> int:
    return int(current_user.id)


@app.before_request
def limit_requests_per_visitor():
    ip = client_ip(request)
    if request.path in ("/login", "/signup") and request.method == "POST":
        if too_many_auth_attempts(ip):
            page = "login.html" if request.path == "/login" else "signup.html"
            return render_template(page, error="Too many attempts - please wait a few minutes and try again"), 429
    elif request.method in ("POST", "PUT", "PATCH", "DELETE") and too_many_requests(ip):
        return jsonify({"error": "Too many requests - please slow down and try again in a minute"}), 429


@app.after_request
def keep_out_of_search_engines(response):
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@app.errorhandler(413)
def upload_too_big(error):
    return jsonify({"error": f"That file is too big to import (the limit is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)"}), 413


@app.route("/robots.txt")
def robots():
    return "User-agent: *\nDisallow: /\n", 200, {"Content-Type": "text/plain"}


def _run_extraction(conn, recipe_id: int, caption: str) -> dict:
    if not use_ai_call(conn):
        recipe = mark_recipe_needs_manual(conn, recipe_id)
        recipe["extraction_message"] = (
            "Today's limit for automatic extraction has been reached - the link is saved, "
            "so you can fill in the recipe by hand or try again tomorrow"
        )
        return recipe
    try:
        result = extract_recipe(caption)
        return update_recipe_extracted(conn, recipe_id, result["title"], result["ingredients"], result["directions"])
    except NoRecipeFoundError as e:
        recipe = mark_recipe_needs_manual(conn, recipe_id)
        recipe["extraction_message"] = str(e)
        return recipe
    except ExtractionError as e:
        recipe = mark_recipe_needs_manual(conn, recipe_id)
        recipe["extraction_message"] = f"Could not process this caption: {e}"
        return recipe


def _parse_category_id(data: dict):
    raw = data.get("category_id")
    if raw in (None, "", "null"):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _safe_next_url():
    """The page a visitor was trying to reach before being sent to log in. Only same-site paths are
    followed, so a crafted link cannot bounce someone to another website."""
    target = request.args.get("next", "")
    if target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not email or len(password) < 8:
        return render_template("signup.html", error="Email is required and password must be at least 8 characters"), 400

    conn = get_connection()
    try:
        if not use_signup(conn):
            return render_template("signup.html", error="Sign-ups are paused for today - please try again tomorrow"), 429
        user_row = create_user(conn, email, password)
        login_user(User(user_row))
        return redirect(url_for("index"))
    except EmailAlreadyExists:
        return render_template("signup.html", error="An account with that email already exists"), 400
    finally:
        conn.close()


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    conn = get_connection()
    try:
        user_row = authenticate_user(conn, email, password)
        login_user(User(user_row))
        return redirect(_safe_next_url() or url_for("index"))
    except InvalidCredentials:
        return render_template("login.html", error="Incorrect email or password"), 401
    finally:
        conn.close()


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/recipes/<int:recipe_id>")
@login_required
def recipe_detail_page(recipe_id):
    return render_template("recipe.html", recipe_id=recipe_id)


@app.route("/categories")
@login_required
def categories_page():
    return render_template("categories.html")


@app.route("/categories/<int:category_id>")
@login_required
def category_detail_page(category_id):
    return render_template("category_detail.html", category_id=category_id)


@app.route("/bulk-review")
@login_required
def bulk_review_page():
    return render_template("bulk_review.html")


@app.route("/api/recipes", methods=["GET"])
@login_required
def list_recipes():
    conn = get_connection()
    try:
        return jsonify(get_recipes(conn, user_id=_user_id()))
    finally:
        conn.close()


@app.route("/api/recipes/<int:recipe_id>", methods=["GET"])
@login_required
def get_recipe_route(recipe_id):
    conn = get_connection()
    try:
        return jsonify(get_recipe(conn, recipe_id, user_id=_user_id()))
    except RecipeNotFound:
        return jsonify({"error": "Recipe not found"}), 404
    finally:
        conn.close()


@app.route("/api/recipes", methods=["POST"])
@login_required
def create_recipe():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    pasted = data.get("url")
    pasted = pasted.strip() if isinstance(pasted, str) else ""
    caption = data.get("caption")
    category_id = _parse_category_id(data)

    if not pasted:
        return jsonify({"error": "A link is required"}), 400

    try:
        url = find_recipe_link(pasted)
        platform = detect_platform(url)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    conn = get_connection()
    try:
        if category_id is not None:
            try:
                get_category(conn, category_id, user_id=_user_id())
            except CategoryNotFound:
                return jsonify({"error": "Category not found"}), 404

        if platform == "tiktok":
            recipe = add_recipe(conn, url, platform, category_id=category_id, user_id=_user_id())
            try:
                fetched = fetch_tiktok_data(url)
            except TikTokFetchError as e:
                recipe = mark_recipe_needs_manual(conn, recipe["id"])
                recipe["extraction_message"] = f"The link is saved. {e}"
                return jsonify(recipe), 201

            conn.execute(
                "UPDATE recipes SET caption_raw = ?, thumbnail_url = ? WHERE id = ?",
                (fetched["caption"], fetched["thumbnail_url"], recipe["id"]),
            )
            conn.commit()
            recipe = _run_extraction(conn, recipe["id"], fetched["caption"])
            return jsonify(recipe), 201

        if not caption:
            recipe = add_recipe(conn, url, platform, category_id=category_id, user_id=_user_id())
            recipe["needs_caption"] = True
            return jsonify(recipe), 201

        recipe = add_recipe(conn, url, platform, caption_raw=caption, category_id=category_id, user_id=_user_id())
        recipe = _run_extraction(conn, recipe["id"], caption)
        return jsonify(recipe), 201
    finally:
        conn.close()


@app.route("/api/recipes/<int:recipe_id>/caption", methods=["PATCH"])
@login_required
def submit_caption(recipe_id):
    data = request.get_json() or {}
    caption = (data.get("caption") or "").strip()

    if not caption:
        return jsonify({"error": "Caption text is required"}), 400

    conn = get_connection()
    try:
        try:
            get_recipe(conn, recipe_id, user_id=_user_id())
        except RecipeNotFound:
            return jsonify({"error": "Recipe not found"}), 404

        conn.execute("UPDATE recipes SET caption_raw = ? WHERE id = ?", (caption, recipe_id))
        conn.commit()
        recipe = _run_extraction(conn, recipe_id, caption)
        return jsonify(recipe)
    finally:
        conn.close()


@app.route("/api/recipes/<int:recipe_id>", methods=["PUT"])
@login_required
def edit_recipe(recipe_id):
    data = request.get_json() or {}
    title = (data.get("title") or "").strip()
    ingredients = data.get("ingredients") or []
    directions = data.get("directions") or []

    if not title:
        return jsonify({"error": "Title is required"}), 400

    conn = get_connection()
    try:
        recipe = update_recipe_manual(conn, recipe_id, title, ingredients, directions, user_id=_user_id())
        return jsonify(recipe)
    except RecipeNotFound:
        return jsonify({"error": "Recipe not found"}), 404
    finally:
        conn.close()


@app.route("/api/recipes/<int:recipe_id>/category", methods=["PATCH"])
@login_required
def assign_recipe_category(recipe_id):
    data = request.get_json() or {}
    category_id = _parse_category_id(data)

    conn = get_connection()
    try:
        if category_id is not None:
            get_category(conn, category_id, user_id=_user_id())
        recipe = set_recipe_category(conn, recipe_id, category_id, user_id=_user_id())
        return jsonify(recipe)
    except RecipeNotFound:
        return jsonify({"error": "Recipe not found"}), 404
    except CategoryNotFound:
        return jsonify({"error": "Category not found"}), 404
    finally:
        conn.close()


@app.route("/api/recipes/<int:recipe_id>", methods=["DELETE"])
@login_required
def remove_recipe(recipe_id):
    conn = get_connection()
    try:
        delete_recipe(conn, recipe_id, user_id=_user_id())
        return jsonify({"deleted": recipe_id})
    except RecipeNotFound:
        return jsonify({"error": "Recipe not found"}), 404
    finally:
        conn.close()


@app.route("/api/recipes/bulk-import", methods=["POST"])
@login_required
def bulk_import():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"error": "No file selected"}), 400

    try:
        links = read_export(uploaded.read().decode("utf-8", errors="ignore"))
    except ImportFileError as e:
        return jsonify({"error": str(e)}), 422
    if max_bulk_links() and len(links) > max_bulk_links():
        return jsonify({"error": f"Too many links in one import (the limit is {max_bulk_links()})"}), 400

    conn = get_connection()
    summary = {"total_found": len(links), "extracted": 0, "needs_caption": 0, "needs_manual": 0, "recipe_ids": []}
    try:
        for link in links:
            url, platform = link["url"], link["platform"]
            recipe = add_recipe(conn, url, platform, user_id=_user_id())
            summary["recipe_ids"].append(recipe["id"])

            if platform == "tiktok":
                try:
                    fetched = fetch_tiktok_data(url)
                except TikTokFetchError:
                    mark_recipe_needs_manual(conn, recipe["id"])
                    summary["needs_manual"] += 1
                    continue

                conn.execute(
                    "UPDATE recipes SET caption_raw = ?, thumbnail_url = ? WHERE id = ?",
                    (fetched["caption"], fetched["thumbnail_url"], recipe["id"]),
                )
                conn.commit()
                result = _run_extraction(conn, recipe["id"], fetched["caption"])
                if result["status"] == "extracted":
                    summary["extracted"] += 1
                else:
                    summary["needs_manual"] += 1
            else:
                summary["needs_caption"] += 1

        return jsonify(summary)
    finally:
        conn.close()


# ---------- Categories ----------

@app.route("/api/categories", methods=["GET"])
@login_required
def list_categories():
    conn = get_connection()
    try:
        return jsonify(get_categories(conn, user_id=_user_id()))
    finally:
        conn.close()


@app.route("/api/categories", methods=["POST"])
@login_required
def create_category():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "A category name is required"}), 400

    conn = get_connection()
    try:
        category = add_category(conn, name, user_id=_user_id())
        return jsonify(category), 201
    except CategoryAlreadyExists as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@app.route("/api/categories/<int:category_id>", methods=["DELETE"])
@login_required
def remove_category(category_id):
    conn = get_connection()
    try:
        delete_category(conn, category_id, user_id=_user_id())
        return jsonify({"deleted": category_id})
    except CategoryNotFound:
        return jsonify({"error": "Category not found"}), 404
    finally:
        conn.close()


@app.route("/api/categories/<int:category_id>/recipes", methods=["GET"])
@login_required
def list_category_recipes(category_id):
    conn = get_connection()
    try:
        get_category(conn, category_id, user_id=_user_id())
        return jsonify(get_recipes_by_category(conn, category_id, user_id=_user_id()))
    except CategoryNotFound:
        return jsonify({"error": "Category not found"}), 404
    finally:
        conn.close()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "1") == "1", port=int(os.environ.get("PORT", "5050")))
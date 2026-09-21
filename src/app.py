"""
Recipe Organizer web app. No accounts - single-user local tool.

Run with: python src/app.py
Then open: http://localhost:5050
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, jsonify, render_template, request

from db import get_connection, init_db
from limits import client_ip, max_bulk_links, too_many_requests, use_ai_call
from url_utils import detect_platform, extract_urls_from_text
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

init_db()


@app.before_request
def limit_changes_per_visitor():
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and too_many_requests(client_ip(request)):
        return jsonify({"error": "Too many requests - please slow down and try again in a minute"}), 429


@app.after_request
def keep_out_of_search_engines(response):
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/recipes/<int:recipe_id>")
def recipe_detail_page(recipe_id):
    return render_template("recipe.html", recipe_id=recipe_id)


@app.route("/categories")
def categories_page():
    return render_template("categories.html")


@app.route("/categories/<int:category_id>")
def category_detail_page(category_id):
    return render_template("category_detail.html", category_id=category_id)


@app.route("/bulk-review")
def bulk_review_page():
    return render_template("bulk_review.html")


@app.route("/api/recipes", methods=["GET"])
def list_recipes():
    conn = get_connection()
    try:
        return jsonify(get_recipes(conn))
    finally:
        conn.close()


@app.route("/api/recipes/<int:recipe_id>", methods=["GET"])
def get_recipe_route(recipe_id):
    conn = get_connection()
    try:
        return jsonify(get_recipe(conn, recipe_id))
    except RecipeNotFound:
        return jsonify({"error": "Recipe not found"}), 404
    finally:
        conn.close()


@app.route("/api/recipes", methods=["POST"])
def create_recipe():
    data = request.get_json() or {}
    url = (data.get("url") or "").strip()
    caption = data.get("caption")
    category_id = _parse_category_id(data)

    if not url:
        return jsonify({"error": "A link is required"}), 400

    try:
        platform = detect_platform(url)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    conn = get_connection()
    try:
        if category_id is not None:
            try:
                get_category(conn, category_id)
            except CategoryNotFound:
                return jsonify({"error": "Category not found"}), 404

        if platform == "tiktok":
            recipe = add_recipe(conn, url, platform, category_id=category_id)
            try:
                fetched = fetch_tiktok_data(url)
            except TikTokFetchError as e:
                recipe = mark_recipe_needs_manual(conn, recipe["id"])
                recipe["extraction_message"] = f"Could not fetch this video's caption: {e}"
                return jsonify(recipe), 201

            conn.execute(
                "UPDATE recipes SET caption_raw = ?, thumbnail_url = ? WHERE id = ?",
                (fetched["caption"], fetched["thumbnail_url"], recipe["id"]),
            )
            conn.commit()
            recipe = _run_extraction(conn, recipe["id"], fetched["caption"])
            return jsonify(recipe), 201

        if not caption:
            recipe = add_recipe(conn, url, platform, category_id=category_id)
            recipe["needs_caption"] = True
            return jsonify(recipe), 201

        recipe = add_recipe(conn, url, platform, caption_raw=caption, category_id=category_id)
        recipe = _run_extraction(conn, recipe["id"], caption)
        return jsonify(recipe), 201
    finally:
        conn.close()


@app.route("/api/recipes/<int:recipe_id>/caption", methods=["PATCH"])
def submit_caption(recipe_id):
    data = request.get_json() or {}
    caption = (data.get("caption") or "").strip()

    if not caption:
        return jsonify({"error": "Caption text is required"}), 400

    conn = get_connection()
    try:
        try:
            get_recipe(conn, recipe_id)
        except RecipeNotFound:
            return jsonify({"error": "Recipe not found"}), 404

        conn.execute("UPDATE recipes SET caption_raw = ? WHERE id = ?", (caption, recipe_id))
        conn.commit()
        recipe = _run_extraction(conn, recipe_id, caption)
        return jsonify(recipe)
    finally:
        conn.close()


@app.route("/api/recipes/<int:recipe_id>", methods=["PUT"])
def edit_recipe(recipe_id):
    data = request.get_json() or {}
    title = (data.get("title") or "").strip()
    ingredients = data.get("ingredients") or []
    directions = data.get("directions") or []

    if not title:
        return jsonify({"error": "Title is required"}), 400

    conn = get_connection()
    try:
        recipe = update_recipe_manual(conn, recipe_id, title, ingredients, directions)
        return jsonify(recipe)
    except RecipeNotFound:
        return jsonify({"error": "Recipe not found"}), 404
    finally:
        conn.close()


@app.route("/api/recipes/<int:recipe_id>/category", methods=["PATCH"])
def assign_recipe_category(recipe_id):
    data = request.get_json() or {}
    category_id = _parse_category_id(data)

    conn = get_connection()
    try:
        if category_id is not None:
            get_category(conn, category_id)
        recipe = set_recipe_category(conn, recipe_id, category_id)
        return jsonify(recipe)
    except RecipeNotFound:
        return jsonify({"error": "Recipe not found"}), 404
    except CategoryNotFound:
        return jsonify({"error": "Category not found"}), 404
    finally:
        conn.close()


@app.route("/api/recipes/<int:recipe_id>", methods=["DELETE"])
def remove_recipe(recipe_id):
    conn = get_connection()
    try:
        delete_recipe(conn, recipe_id)
        return jsonify({"deleted": recipe_id})
    except RecipeNotFound:
        return jsonify({"error": "Recipe not found"}), 404
    finally:
        conn.close()


@app.route("/api/recipes/bulk-import", methods=["POST"])
def bulk_import():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"error": "No file selected"}), 400

    try:
        text = uploaded.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return jsonify({"error": f"Could not read this file: {e}"}), 400

    urls = extract_urls_from_text(text)
    if not urls:
        return jsonify({"error": "No TikTok or Instagram links found in this file"}), 422
    if max_bulk_links() and len(urls) > max_bulk_links():
        return jsonify({"error": f"Too many links in one import (the limit is {max_bulk_links()})"}), 400

    conn = get_connection()
    summary = {"total_found": len(urls), "extracted": 0, "needs_caption": 0, "needs_manual": 0, "skipped": 0, "recipe_ids": []}
    try:
        for url in urls:
            try:
                platform = detect_platform(url)
            except ValueError:
                summary["skipped"] += 1
                continue

            recipe = add_recipe(conn, url, platform)
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
def list_categories():
    conn = get_connection()
    try:
        return jsonify(get_categories(conn))
    finally:
        conn.close()


@app.route("/api/categories", methods=["POST"])
def create_category():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "A category name is required"}), 400

    conn = get_connection()
    try:
        category = add_category(conn, name)
        return jsonify(category), 201
    except CategoryAlreadyExists as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@app.route("/api/categories/<int:category_id>", methods=["DELETE"])
def remove_category(category_id):
    conn = get_connection()
    try:
        delete_category(conn, category_id)
        return jsonify({"deleted": category_id})
    except CategoryNotFound:
        return jsonify({"error": "Category not found"}), 404
    finally:
        conn.close()


@app.route("/api/categories/<int:category_id>/recipes", methods=["GET"])
def list_category_recipes(category_id):
    conn = get_connection()
    try:
        get_category(conn, category_id)
        return jsonify(get_recipes_by_category(conn, category_id))
    except CategoryNotFound:
        return jsonify({"error": "Category not found"}), 404
    finally:
        conn.close()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "1") == "1", port=int(os.environ.get("PORT", "5050")))
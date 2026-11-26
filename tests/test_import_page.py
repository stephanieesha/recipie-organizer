"""
The import box on the home page: what it tells a person to upload, and how the upload is sent.
"""

from pathlib import Path

PAGE = Path(__file__).parent.parent / "templates" / "index.html"


def test_the_import_box_says_how_to_get_the_instagram_file():
    html = PAGE.read_text(encoding="utf-8")
    assert "Download your information" in html
    assert "Choose JSON as the format" in html
    assert "saved_posts.json" in html


def test_the_import_box_says_how_to_get_the_tiktok_file_and_what_is_imported_from_it():
    html = PAGE.read_text(encoding="utf-8")
    assert "Download your data" in html
    assert "Choose JSON as the file format" in html
    assert "user_data.json" in html
    assert "Only your favorites" in html
    assert "not your likes or watch history" in html

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

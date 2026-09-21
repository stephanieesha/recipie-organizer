import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tiktok_oembed import fetch_tiktok_caption, fetch_tiktok_data, TikTokFetchError


class FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_fetch_caption_returns_title_field():
    fake_json = b'{"version": "1.0", "title": "Garlic butter mashed potatoes #foodtiktok", "author_name": "chef"}'
    with patch("tiktok_oembed.urllib.request.urlopen", return_value=FakeResponse(fake_json)):
        caption = fetch_tiktok_caption("https://www.tiktok.com/@chef/video/123")
    assert caption == "Garlic butter mashed potatoes #foodtiktok"


def test_fetch_caption_raises_when_title_is_empty():
    fake_json = b'{"version": "1.0", "title": "", "author_name": "chef"}'
    with patch("tiktok_oembed.urllib.request.urlopen", return_value=FakeResponse(fake_json)):
        with pytest.raises(TikTokFetchError):
            fetch_tiktok_caption("https://www.tiktok.com/@chef/video/123")


def test_fetch_caption_raises_when_title_field_missing():
    fake_json = b'{"version": "1.0", "author_name": "chef"}'
    with patch("tiktok_oembed.urllib.request.urlopen", return_value=FakeResponse(fake_json)):
        with pytest.raises(TikTokFetchError):
            fetch_tiktok_caption("https://www.tiktok.com/@chef/video/123")


def test_fetch_caption_handles_malformed_json():
    with patch("tiktok_oembed.urllib.request.urlopen", return_value=FakeResponse(b"not json")):
        with pytest.raises(TikTokFetchError):
            fetch_tiktok_caption("https://www.tiktok.com/@chef/video/123")


def test_fetch_data_returns_caption_and_thumbnail():
    fake_json = b'{"title": "Garlic bread", "thumbnail_url": "https://p16.tiktokcdn.com/cover.jpg"}'
    with patch("tiktok_oembed.urllib.request.urlopen", return_value=FakeResponse(fake_json)):
        data = fetch_tiktok_data("https://www.tiktok.com/@chef/video/123")
    assert data["caption"] == "Garlic bread"
    assert data["thumbnail_url"] == "https://p16.tiktokcdn.com/cover.jpg"


def test_fetch_data_thumbnail_is_none_when_absent():
    fake_json = b'{"title": "Garlic bread"}'
    with patch("tiktok_oembed.urllib.request.urlopen", return_value=FakeResponse(fake_json)):
        data = fetch_tiktok_data("https://www.tiktok.com/@chef/video/123")
    assert data["thumbnail_url"] is None

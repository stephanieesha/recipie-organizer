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


# --- Every failure becomes one plain sentence ------------------------------

import io  # noqa: E402
import socket  # noqa: E402
import urllib.error  # noqa: E402


def _fails_with(**patch_args):
    with patch("tiktok_oembed.urllib.request.urlopen", **patch_args):
        with pytest.raises(TikTokFetchError) as err:
            fetch_tiktok_data("https://vt.tiktok.com/ZSabc/")
    return str(err.value)


def _http_error(code):
    return urllib.error.HTTPError("https://www.tiktok.com/oembed", code, "x", {}, io.BytesIO(b""))


@pytest.mark.parametrize("code, expected", [
    (404, "TikTok says this video doesn't exist or is private."),
    (400, "TikTok didn't accept this link. Open the video in TikTok and copy the link from its Share menu."),
    (429, "TikTok is limiting lookups right now."),
    (500, "TikTok isn't answering right now."),
    (503, "TikTok isn't answering right now."),
    (403, "TikTok refused the lookup (error 403)."),
])
def test_http_errors_are_explained_without_codes_or_jargon(code, expected):
    assert _fails_with(side_effect=_http_error(code)) == expected


def test_a_timeout_while_connecting_is_reported_not_crashed_on():
    assert _fails_with(side_effect=TimeoutError("timed out")) == "TikTok took too long to answer."


def test_a_timeout_while_reading_the_answer_is_reported_not_crashed_on():
    class SlowResponse(FakeResponse):
        def read(self):
            raise socket.timeout("timed out")

    assert _fails_with(return_value=SlowResponse(b"")) == "TikTok took too long to answer."


def test_a_timeout_wrapped_in_a_url_error_is_still_a_timeout():
    assert _fails_with(side_effect=urllib.error.URLError(socket.timeout("timed out"))) == "TikTok took too long to answer."


def test_a_network_failure_does_not_show_technical_details():
    message = _fails_with(side_effect=urllib.error.URLError(OSError(-2, "Name or service not known")))
    assert message == "Could not reach TikTok right now."
    assert "Errno" not in message and "urlopen" not in message


@pytest.mark.parametrize("body", [b"[1, 2]", b"null", b"not json", b'"text"', b"\xff\xfe"])
def test_an_unreadable_answer_is_reported_not_crashed_on(body):
    assert _fails_with(return_value=FakeResponse(body)) == "TikTok sent back something this app could not read."


@pytest.mark.parametrize("body", [b'{"title": null}', b'{"title": 5}', b'{"title": "   "}'])
def test_a_missing_or_empty_caption_is_explained(body):
    assert _fails_with(return_value=FakeResponse(body)) == "TikTok didn't return a caption for this video."


def test_a_thumbnail_that_is_not_text_is_ignored():
    fake_json = b'{"title": "Garlic bread", "thumbnail_url": 7}'
    with patch("tiktok_oembed.urllib.request.urlopen", return_value=FakeResponse(fake_json)):
        assert fetch_tiktok_data("https://www.tiktok.com/@chef/video/1")["thumbnail_url"] is None


# --- Links from TikTok's data download: the ordinary web link is tried first ---------

import urllib.parse  # noqa: E402

SHARE_LINK = "https://www.tiktokv.com/share/video/7123456789/"
WEB_LINK = "https://www.tiktok.com/@_/video/7123456789"
GOOD = b'{"title": "Garlic bread", "thumbnail_url": "https://p16.tiktokcdn.com/cover.jpg"}'


class FakeTikTok:
    """Stands in for TikTok's lookup: answers each link as told and remembers which links were asked about."""

    def __init__(self, answers):
        self.answers = answers
        self.asked = []

    def __call__(self, request_url, timeout=None):
        link = urllib.parse.parse_qs(urllib.parse.urlsplit(request_url).query)["url"][0]
        self.asked.append(link)
        answer = self.answers[link]
        if isinstance(answer, BaseException):
            raise answer
        return FakeResponse(answer)


def test_a_data_download_link_is_looked_up_by_its_web_link_first():
    tiktok = FakeTikTok({WEB_LINK: GOOD})
    with patch("tiktok_oembed.urllib.request.urlopen", side_effect=tiktok):
        data = fetch_tiktok_data(SHARE_LINK)
    assert data == {"caption": "Garlic bread", "thumbnail_url": "https://p16.tiktokcdn.com/cover.jpg"}
    assert tiktok.asked == [WEB_LINK]


@pytest.mark.parametrize("code", [400, 404])
def test_if_tiktok_does_not_know_the_web_link_the_original_is_tried(code):
    tiktok = FakeTikTok({WEB_LINK: _http_error(code), SHARE_LINK: GOOD})
    with patch("tiktok_oembed.urllib.request.urlopen", side_effect=tiktok):
        data = fetch_tiktok_data(SHARE_LINK)
    assert data["caption"] == "Garlic bread"
    assert tiktok.asked == [WEB_LINK, SHARE_LINK]


def test_if_neither_link_is_known_the_answer_about_the_original_is_given():
    tiktok = FakeTikTok({WEB_LINK: _http_error(400), SHARE_LINK: _http_error(404)})
    with patch("tiktok_oembed.urllib.request.urlopen", side_effect=tiktok):
        with pytest.raises(TikTokFetchError) as error:
            fetch_tiktok_data(SHARE_LINK)
    assert str(error.value) == "TikTok says this video doesn't exist or is private."
    assert tiktok.asked == [WEB_LINK, SHARE_LINK]


@pytest.mark.parametrize("failure, message", [
    (TimeoutError("timed out"), "TikTok took too long to answer."),
    (urllib.error.URLError(OSError(-2, "Name or service not known")), "Could not reach TikTok right now."),
    (_http_error(429), "TikTok is limiting lookups right now."),
    (_http_error(503), "TikTok isn't answering right now."),
    (_http_error(403), "TikTok refused the lookup (error 403)."),
])
def test_a_failure_that_is_not_about_the_link_is_reported_without_asking_again(failure, message):
    tiktok = FakeTikTok({WEB_LINK: failure})
    with patch("tiktok_oembed.urllib.request.urlopen", side_effect=tiktok):
        with pytest.raises(TikTokFetchError) as error:
            fetch_tiktok_data(SHARE_LINK)
    assert str(error.value) == message
    assert tiktok.asked == [WEB_LINK]


@pytest.mark.parametrize("body", [b'{"title": ""}', b"not json"])
def test_an_answer_without_a_caption_is_reported_without_asking_again(body):
    tiktok = FakeTikTok({WEB_LINK: body})
    with patch("tiktok_oembed.urllib.request.urlopen", side_effect=tiktok):
        with pytest.raises(TikTokFetchError):
            fetch_tiktok_data(SHARE_LINK)
    assert tiktok.asked == [WEB_LINK]


@pytest.mark.parametrize("link", [
    "https://www.tiktok.com/@chef/video/7123456789",
    "https://vt.tiktok.com/ZSabc/",
    "https://www.tiktok.com/t/ZTabc123/",
])
def test_other_links_are_asked_about_once_as_they_are(link):
    tiktok = FakeTikTok({link: GOOD})
    with patch("tiktok_oembed.urllib.request.urlopen", side_effect=tiktok):
        fetch_tiktok_data(link)
    assert tiktok.asked == [link]


@pytest.mark.parametrize("code", [400, 404])
def test_a_refused_ordinary_link_is_not_asked_about_a_second_time(code):
    link = "https://www.tiktok.com/@chef/video/7123456789"
    tiktok = FakeTikTok({link: _http_error(code)})
    with patch("tiktok_oembed.urllib.request.urlopen", side_effect=tiktok):
        with pytest.raises(TikTokFetchError):
            fetch_tiktok_data(link)
    assert tiktok.asked == [link]

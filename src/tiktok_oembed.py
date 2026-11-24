"""
Fetches a TikTok video's caption and thumbnail via TikTok's official,
public, no-auth-required oEmbed endpoint - a documented, sanctioned use
case (unlike Instagram's oEmbed, which doesn't return caption text at
all and whose terms explicitly prohibit extracting/persisting post
content).

The "thumbnail" is TikTok's own cover image for the video (a field the
oEmbed response already provides), not a frame we extract ourselves -
downloading and processing the actual video file would be a much bigger
technical lift and murkier ground ToS-wise, when TikTok already hands us
a sanctioned cover image for exactly this purpose.
"""

import json
import socket
import urllib.error
import urllib.parse
import urllib.request

TIKTOK_OEMBED_URL = "https://www.tiktok.com/oembed"


class TikTokFetchError(Exception):
    pass


def _http_error_message(code: int) -> str:
    if code == 404:
        return "TikTok says this video doesn't exist or is private."
    if code == 400:
        return "TikTok didn't accept this link. Open the video in TikTok and copy the link from its Share menu."
    if code == 429:
        return "TikTok is limiting lookups right now."
    if code >= 500:
        return "TikTok isn't answering right now."
    return f"TikTok refused the lookup (error {code})."


def fetch_tiktok_data(url: str) -> dict:
    """Every failure raises TikTokFetchError with one plain sentence that is safe to show on the page."""
    params = urllib.parse.urlencode({"url": url})
    request_url = f"{TIKTOK_OEMBED_URL}?{params}"

    try:
        with urllib.request.urlopen(request_url, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise TikTokFetchError(_http_error_message(e.code))
    except (TimeoutError, socket.timeout):
        raise TikTokFetchError("TikTok took too long to answer.")
    except urllib.error.URLError as e:
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            raise TikTokFetchError("TikTok took too long to answer.")
        raise TikTokFetchError("Could not reach TikTok right now.")
    except OSError:
        raise TikTokFetchError("Could not reach TikTok right now.")
    except ValueError:
        raise TikTokFetchError("TikTok sent back something this app could not read.")

    if not isinstance(data, dict):
        raise TikTokFetchError("TikTok sent back something this app could not read.")

    title = data.get("title")
    title = title.strip() if isinstance(title, str) else ""
    if not title:
        raise TikTokFetchError("TikTok didn't return a caption for this video.")

    thumbnail = data.get("thumbnail_url")
    return {
        "caption": title,
        "thumbnail_url": thumbnail if isinstance(thumbnail, str) else None,
    }


def fetch_tiktok_caption(url: str) -> str:
    return fetch_tiktok_data(url)["caption"]

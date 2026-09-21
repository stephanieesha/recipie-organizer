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
import urllib.error
import urllib.parse
import urllib.request

TIKTOK_OEMBED_URL = "https://www.tiktok.com/oembed"


class TikTokFetchError(Exception):
    pass


def fetch_tiktok_data(url: str) -> dict:
    params = urllib.parse.urlencode({"url": url})
    request_url = f"{TIKTOK_OEMBED_URL}?{params}"

    try:
        with urllib.request.urlopen(request_url, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise TikTokFetchError("This TikTok link doesn't seem to exist or is private")
        raise TikTokFetchError(f"TikTok returned an error: HTTP {e.code}")
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        raise TikTokFetchError(f"Could not reach TikTok: {e}")

    title = data.get("title", "").strip()
    if not title:
        raise TikTokFetchError("TikTok didn't return a caption for this video")

    return {
        "caption": title,
        "thumbnail_url": data.get("thumbnail_url"),
    }


def fetch_tiktok_caption(url: str) -> str:
    return fetch_tiktok_data(url)["caption"]

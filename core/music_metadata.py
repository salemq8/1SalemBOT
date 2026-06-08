from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import yt_dlp


@dataclass
class TrackMetadata:
    title: str
    channel: str
    query: str


def clean_youtube_watch_url(url: str) -> str:
    value = str(url or "").strip()
    if "youtube.com/watch" not in value:
        return value

    parsed = urlparse(value)
    video_id = parse_qs(parsed.query).get("v", [""])[0]
    return f"https://www.youtube.com/watch?v={video_id}" if video_id else value


def is_youtube_url(value):
    lowered = str(value or "").lower()
    return "youtube.com" in lowered or "youtu.be" in lowered


def metadata_channel(info):
    if not isinstance(info, dict):
        return ""
    for key in ("channel", "uploader", "creator", "artist", "uploader_id", "channel_id"):
        value = str(info.get(key) or "").strip()
        if value:
            return value
    return ""


def metadata_webpage_url(info, fallback):
    if not isinstance(info, dict):
        return fallback
    value = str(info.get("webpage_url") or "").strip()
    if value:
        return value
    video_id = str(info.get("id") or "").strip()
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    return fallback


def resolve_track_metadata(query_or_url: str) -> TrackMetadata:
    query = str(query_or_url or "").strip()
    if not query:
        raise ValueError("No track query provided.")

    ydl_opts = {
        "quiet": True,
        "noplaylist": True,
        "extract_flat": False,
        "skip_download": True,
        "format": "bestaudio/best",
        "default_search": "ytsearch",
    }

    clean_value = clean_youtube_watch_url(query) if is_youtube_url(query) else query

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        if is_youtube_url(clean_value):
            info = ydl.extract_info(clean_value, download=False)
        else:
            result = ydl.extract_info(f"ytsearch5:{clean_value}", download=False)
            entries = result.get("entries", []) if isinstance(result, dict) else []
            if not entries:
                raise ValueError("No YouTube results found")
            info = entries[0]

    return TrackMetadata(
        title=str((info or {}).get("title") or clean_value).strip(),
        channel=metadata_channel(info),
        query=metadata_webpage_url(info, clean_value),
    )

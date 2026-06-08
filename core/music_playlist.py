from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import yt_dlp

from .music_content_filter import is_track_blocked_by_policy
from .music_metadata import metadata_channel


PLAYLIST_IMPORT_LIMIT = 50
YOUTUBE_PLAYLIST_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
}


@dataclass
class PlaylistTrack:
    title: str
    query: str
    channel: str = ""


@dataclass
class PlaylistImport:
    title: str
    tracks: list[PlaylistTrack]
    truncated: bool = False
    blocked_count: int = 0


def get_youtube_playlist_id(value):
    try:
        parsed = urlparse(str(value or "").strip())
    except Exception:
        return ""

    host = parsed.netloc.lower()
    if host not in YOUTUBE_PLAYLIST_HOSTS:
        return ""

    playlist_id = parse_qs(parsed.query).get("list", [""])[0].strip()
    return playlist_id


def is_youtube_playlist_url(value):
    return bool(get_youtube_playlist_id(value))


def _playlist_url(value):
    playlist_id = get_youtube_playlist_id(value)
    if not playlist_id:
        return ""
    return f"https://www.youtube.com/playlist?list={playlist_id}"


def _entry_query(entry):
    if not isinstance(entry, dict):
        return ""

    webpage_url = str(entry.get("webpage_url") or "").strip()
    if webpage_url:
        return webpage_url

    url = str(entry.get("url") or "").strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url

    video_id = str(entry.get("id") or url).strip()
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    return ""


def _entry_title(entry, fallback_query):
    title = str((entry or {}).get("title") or "").strip()
    return title or fallback_query


def fetch_youtube_playlist_items(value, *, max_tracks=PLAYLIST_IMPORT_LIMIT):
    limit = max(1, min(int(max_tracks or PLAYLIST_IMPORT_LIMIT), PLAYLIST_IMPORT_LIMIT))
    playlist_url = _playlist_url(value)
    if not playlist_url:
        raise ValueError("Not a supported YouTube playlist URL.")

    ydl_opts = {
        "quiet": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "ignoreerrors": True,
        "playlistend": limit + 1,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)

    entries = (info or {}).get("entries") or []
    tracks = []
    blocked_count = 0
    playlist_title = str((info or {}).get("title") or "").strip()
    for entry in entries:
        query = _entry_query(entry)
        if not query:
            continue
        title = _entry_title(entry, query)
        channel = metadata_channel(entry)
        if is_track_blocked_by_policy(title=title, channel=channel, playlist_title=playlist_title):
            blocked_count += 1
            continue
        tracks.append(PlaylistTrack(title=title, query=query, channel=channel))
        if len(tracks) >= limit:
            break

    if not tracks:
        if blocked_count:
            raise ValueError("Track unavailable due to music policy.")
        raise ValueError("Playlist could not be loaded or has no playable videos.")

    return PlaylistImport(
        title=playlist_title or "YouTube playlist",
        tracks=tracks,
        truncated=len(entries) > limit,
        blocked_count=blocked_count,
    )

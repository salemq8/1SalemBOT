import io
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
import vlc
import yt_dlp
from PIL import Image

from .app_paths import APP_NAME, PROJECT_ROOT, WINDOW_ICON_ICO
from .music_metadata import clean_youtube_watch_url, metadata_channel
from .ui.constants import APP_VERSION

try:
    from pycaw.pycaw import AudioUtilities
except Exception:
    AudioUtilities = None


DEFAULT_VLC_PATH = Path(r"C:\Program Files\VideoLAN\VLC")


def resolve_vlc_path():
    configured_path = os.environ.get("VLC_PATH", "").strip()
    candidates = []
    if configured_path:
        candidates.append(Path(configured_path))

    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "vlc")

    candidates.extend(
        [
            PROJECT_ROOT / "vlc",
            DEFAULT_VLC_PATH,
        ]
    )

    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return Path(configured_path) if configured_path else DEFAULT_VLC_PATH


VLC_PATH = resolve_vlc_path()

if VLC_PATH.is_dir():
    os.environ["PATH"] = str(VLC_PATH) + os.pathsep + os.environ.get("PATH", "")


@dataclass
class TrackInfo:
    title: str
    webpage_url: str
    audio_url: str
    thumbnail_url: str
    channel_name: str = ""


class MusicPlayer:
    def __init__(self, initial_volume: int = 100, initial_muted: bool = False):
        if not VLC_PATH.is_dir():
            raise FileNotFoundError(
                f"VLC folder not found: {VLC_PATH}\nSet VLC_PATH or install VLC in the default location."
            )

        plugin_path = VLC_PATH / "plugins"
        if not plugin_path.is_dir():
            raise FileNotFoundError(f"VLC plugins folder not found: {plugin_path}")

        try:
            self.instance = vlc.Instance(
                "--no-video",
                "--quiet",
                "--network-caching=2000",
                "--file-caching=2000",
            )
            icon_path = str(WINDOW_ICON_ICO) if WINDOW_ICON_ICO.exists() else str(Path(sys.executable).resolve())
            try:
                self.instance.set_app_id(APP_NAME, APP_VERSION, icon_path)
                self.instance.set_user_agent(APP_NAME, APP_NAME)
            except Exception:
                pass
            self.player = self.instance.media_player_new()
            self.player.audio_set_volume(100)
            self.player.audio_set_mute(False)
        except Exception as exc:
            raise RuntimeError(
                "Failed to initialize VLC from Python. Make sure VLC matches your Python architecture."
            ) from exc

        self.current_track: Optional[TrackInfo] = None
        self.current_media = None
        self.target_volume = max(0, min(100, int(initial_volume)))
        self.target_muted = bool(initial_muted)
        self.audio_session = None
        self.audio_session_identity_applied = False
        self.audio_session_name = APP_NAME
        self.audio_session_icon = icon_path
        self._apply_player_fallback_audio_state()

    def _apply_player_fallback_audio_state(self):
        try:
            volume = 100 if self.audio_session is not None else self.target_volume
            self.player.audio_set_volume(volume)
            self.player.audio_set_mute(self.target_muted)
        except Exception:
            pass

    def _get_process_audio_session(self):
        if AudioUtilities is None or os.name != "nt":
            return None
        try:
            return AudioUtilities.GetProcessSession(os.getpid())
        except Exception:
            return None

    def _apply_audio_session_identity(self):
        if self.audio_session is None:
            return False
        try:
            self.audio_session.DisplayName = self.audio_session_name
            self.audio_session.IconPath = self.audio_session_icon
            self.audio_session_identity_applied = True
            return True
        except Exception:
            return False

    def _apply_master_state_to_session(self):
        if self.audio_session is None:
            return False
        try:
            volume_control = self.audio_session.SimpleAudioVolume
            volume_control.SetMasterVolume(self.target_volume / 100.0, None)
            volume_control.SetMute(self.target_muted, None)
            self._apply_player_fallback_audio_state()
            return True
        except Exception:
            return False

    def refresh_audio_session(self, force=False):
        if force or self.audio_session is None:
            self.audio_session = self._get_process_audio_session()
            if self.audio_session is not None:
                self._apply_audio_session_identity()
                self._apply_master_state_to_session()
        elif self.audio_session is not None and not self.audio_session_identity_applied:
            self._apply_audio_session_identity()
        return self.audio_session

    def get_audio_state(self):
        session = self.refresh_audio_session()
        if session is not None:
            try:
                session_state = getattr(session, "State", None)
                if session_state == 1:
                    volume = int(round(session.SimpleAudioVolume.GetMasterVolume() * 100))
                    muted = bool(session.SimpleAudioVolume.GetMute())
                    self.target_volume = max(0, min(100, volume))
                    self.target_muted = muted
            except Exception:
                self.audio_session = None
                self.audio_session_identity_applied = False
                session = None
        return {
            "volume": self.target_volume,
            "muted": self.target_muted,
            "session_bound": session is not None,
            "identity_applied": self.audio_session_identity_applied,
            "display_name": self.audio_session_name if session is not None else "",
        }

    def _clean_youtube_url(self, url: str) -> str:
        return clean_youtube_watch_url(url)

    def _extract_info(self, query_or_url: str) -> TrackInfo:
        ydl_opts = {
            "quiet": True,
            "noplaylist": True,
            "extract_flat": False,
            "skip_download": True,
            "format": "bestaudio/best",
            "default_search": "ytsearch",
        }

        clean_value = query_or_url.strip()
        if "youtube.com" in clean_value or "youtu.be" in clean_value:
            clean_value = self._clean_youtube_url(clean_value)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            if "youtube.com" in clean_value or "youtu.be" in clean_value:
                info = ydl.extract_info(clean_value, download=False)
            else:
                result = ydl.extract_info(f"ytsearch5:{clean_value}", download=False)
                entries = result.get("entries", [])
                if not entries:
                    raise ValueError("No YouTube results found")
                info = entries[0]

        audio_url = info.get("url")
        if not audio_url:
            raise ValueError("Could not extract audio stream URL")

        return TrackInfo(
            title=info.get("title", "Unknown title"),
            webpage_url=info.get("webpage_url", clean_value),
            audio_url=audio_url,
            thumbnail_url=info.get("thumbnail") or "",
            channel_name=metadata_channel(info),
        )

    def load(self, query_or_url: str) -> TrackInfo:
        self.current_track = self._extract_info(query_or_url)
        return self.current_track

    def play_loaded(self) -> TrackInfo:
        if self.current_track is None:
            raise RuntimeError("No track is loaded")
        self.current_media = self.instance.media_new(self.current_track.audio_url)
        self.player.set_media(self.current_media)
        result = self.player.play()
        if result == -1:
            raise RuntimeError("VLC refused to start playback")
        self.refresh_audio_session(force=True)
        return self.current_track

    def play(self, query_or_url: str) -> TrackInfo:
        track = self.load(query_or_url)
        self.play_loaded()
        return track

    def stop(self):
        self.player.stop()
        self.current_media = None

    def clear_current_track(self):
        self.current_track = None
        self.current_media = None

    def pause(self):
        self.player.pause()

    def set_volume(self, volume: int):
        self.target_volume = max(0, min(100, int(volume)))
        self._apply_player_fallback_audio_state()
        self.refresh_audio_session()
        self._apply_master_state_to_session()

    def adjust_volume(self, delta: int):
        self.set_volume(self.target_volume + int(delta))

    def get_volume(self) -> int:
        return int(self.get_audio_state()["volume"])

    def set_muted(self, muted: bool):
        self.target_muted = bool(muted)
        self._apply_player_fallback_audio_state()
        self.refresh_audio_session()
        self._apply_master_state_to_session()

    def toggle_mute(self):
        self.set_muted(not self.target_muted)

    def is_muted(self) -> bool:
        return bool(self.get_audio_state()["muted"])

    def is_playing(self) -> bool:
        try:
            return bool(self.player.is_playing())
        except Exception:
            return False

    def get_state(self):
        try:
            return self.player.get_state()
        except Exception:
            return None

    def get_thumbnail_image(self, max_size=(640, 360)) -> Optional[Image.Image]:
        if not self.current_track or not self.current_track.thumbnail_url:
            return None

        try:
            response = requests.get(self.current_track.thumbnail_url, timeout=15)
            response.raise_for_status()
            image = Image.open(io.BytesIO(response.content)).convert("RGB")
            image.thumbnail(max_size)
            return image
        except Exception:
            return None

import threading
import time
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.music_commands import looks_like_implicit_music_text, parse_music_command, parse_music_intent
from core.app_state import default_dashboard_state, save_json
from core.eventsub_bot import chatter_can_control_music, create_message_handler, find_trigger, format_music_queue_reply, parse_chat_music_request, remove_trigger
from core import music_playlist
from core.music_player import MusicPlayer
from core.ui.music_mixin import DashboardMusicMixin


class FakeLineEdit:
    def __init__(self):
        self.text_value = ""

    def setText(self, value):
        self.text_value = value


class FakePlayer:
    def __init__(self, playing=False, stop_delay=0.0):
        self.playing = playing
        self.stop_delay = stop_delay
        self.stop_calls = 0
        self.clear_calls = 0
        self.volume = 100
        self.backend_volume = None
        self.muted = False
        self.backend_muted = None
        self.stop_started = threading.Event()
        self.stop_done = threading.Event()

    def is_playing(self):
        return self.playing

    def stop(self):
        self.stop_started.set()
        if self.stop_delay:
            time.sleep(self.stop_delay)
        self.stop_calls += 1
        self.playing = False
        self.stop_done.set()

    def clear_current_track(self):
        self.clear_calls += 1

    def set_volume(self, volume):
        self.volume = max(0, min(100, int(volume)))
        if self.backend_volume is None:
            self.backend_volume = self.volume

    def set_muted(self, muted):
        self.muted = bool(muted)
        if self.backend_muted is None:
            self.backend_muted = self.muted

    def get_audio_state(self):
        return {
            "volume": self.volume,
            "muted": self.muted,
            "backend_volume": self.volume if self.backend_volume is None else self.backend_volume,
            "backend_muted": self.muted if self.backend_muted is None else self.backend_muted,
            "session_bound": True,
        }


class MusicHarness(DashboardMusicMixin):
    def __init__(self, *, queue=None, active=False, loading=False, playing=False, stop_delay=0.0):
        self.logs = []
        self.started = []
        self.skip_advance_scheduled = False
        self.skip_advance_max_delay_ms = None
        self.ui_cleared = False
        self.queue_refreshes = 0
        self.music_queue = list(queue or [])
        self.music_queue_titles = {}
        self.prevent_duplicate_tracks = True
        self.current_track_query = "Current track" if active or loading else ""
        self.current_track_active = active
        self.music_loading = loading
        self.current_track_title = "Current track" if active or loading else ""
        self.current_track_started_at = 123.0
        self.music_player_initialized = True
        self.music_player = FakePlayer(playing=playing, stop_delay=stop_delay)
        self.music_playback_generation = 0
        self.music_playback_lock = threading.RLock()
        self.music_skip_in_progress = False
        self._closing = False
        self.music_enabled = True
        self.playlist_import_loading = False
        self.playlist_import_requests = []
        self.playlist_payload = None
        self.track_request_payloads = {}
        self.music_entry = FakeLineEdit()
        self.music_page_input = FakeLineEdit()
        self.settings = {}
        self.audio_volume = 30
        self.audio_muted = False
        self.audio_session_attached = False
        self.volume_slider_widgets = []
        self.volume_value_labels = []
        self.volume_mute_buttons = []
        self.persisted_audio_settings = []

    def append_log(self, message):
        self.logs.append(message)

    def ensure_music_player(self):
        return self.music_player

    def refresh_queue_list_widgets(self):
        self.queue_refreshes += 1

    def publish_music_queue_state(self):
        self.published_queue_state = list(self.music_queue)

    def sync_volume_controls(self):
        for slider in getattr(self, "volume_slider_widgets", []):
            slider.blockSignals(True)
            slider.setValue(self.audio_volume)
            slider.blockSignals(False)

    def persist_audio_settings(self):
        self.settings["audio_volume"] = int(self.audio_volume)
        self.settings["audio_muted"] = bool(self.audio_muted)
        self.persisted_audio_settings.append((self.audio_volume, self.audio_muted))

    def clear_current_track_ui(self):
        self.ui_cleared = True
        self.current_track_title = ""

    def schedule_play_next_in_queue(self):
        self.play_next_in_queue()

    def schedule_skip_queue_advance(self, stop_completed):
        self.skip_advance_scheduled = True
        self.skip_advance_max_delay_ms = self.SKIP_NEXT_TRACK_MAX_DELAY_MS
        self.play_next_in_queue()

    def start_track_playback(self, query):
        self.apply_master_volume_to_player("test_track_start", persist=False)
        self.started.append(query)
        self.current_track_active = True
        self.music_loading = False
        self.current_track_title = query
        self.current_track_query = query
        self.current_track_started_at = 456.0

    def start_playlist_import(self, query):
        self.playlist_import_requests.append(query)
        if self.playlist_payload is not None:
            self.apply_playlist_import_result(self.playlist_payload)

    def start_track_request_inspection(self, query):
        payload = self.track_request_payloads.get(
            query,
            {
                "ok": True,
                "query": query,
                "title": query,
                "channel": "",
                "blocked": False,
            },
        )
        self.apply_track_request_result(payload)


class PendingSkipHarness(MusicHarness):
    def schedule_skip_queue_advance(self, stop_completed):
        self.skip_advance_scheduled = True
        self.skip_advance_max_delay_ms = self.SKIP_NEXT_TRACK_MAX_DELAY_MS
        self.pending_stop_completed = stop_completed


class FakeSignal:
    def __init__(self):
        self.items = []

    def emit(self, *args):
        self.items.append(args)


class FakeBridge:
    def __init__(self):
        self.log_signal = FakeSignal()
        self.title_signal = FakeSignal()
        self.cover_signal = FakeSignal()
        self.clear_cover_signal = FakeSignal()


class FakeSlider:
    def __init__(self, on_change=None):
        self.value = 0
        self.signals_blocked = False
        self.on_change = on_change

    def blockSignals(self, blocked):
        self.signals_blocked = bool(blocked)

    def setValue(self, value):
        self.value = int(value)
        if self.on_change is not None and not self.signals_blocked:
            self.on_change(self.value)

    def setLayoutDirection(self, _direction):
        pass

    def setInvertedAppearance(self, _value):
        pass

    def setInvertedControls(self, _value):
        pass


class FakeCoreVlcPlayer:
    def __init__(self, volume=100, muted=False):
        self.volume = int(volume)
        self.muted = bool(muted)
        self.volume_writes = []
        self.mute_writes = []

    def audio_set_volume(self, volume):
        self.volume = int(volume)
        self.volume_writes.append(self.volume)

    def audio_get_volume(self):
        return self.volume

    def audio_set_mute(self, muted):
        self.muted = bool(muted)
        self.mute_writes.append(self.muted)

    def audio_get_mute(self):
        return self.muted


class FakeSimpleAudioVolume:
    def __init__(self, volume=1.0, muted=False):
        self.volume = float(volume)
        self.muted = bool(muted)
        self.set_volume_calls = []
        self.set_mute_calls = []

    def SetMasterVolume(self, volume, _event_context):
        self.volume = float(volume)
        self.set_volume_calls.append(self.volume)

    def GetMasterVolume(self):
        return self.volume

    def SetMute(self, muted, _event_context):
        self.muted = bool(muted)
        self.set_mute_calls.append(self.muted)

    def GetMute(self):
        return self.muted


class FakeAudioSession:
    def __init__(self, volume=1.0, muted=False):
        self.State = 1
        self.SimpleAudioVolume = FakeSimpleAudioVolume(volume=volume, muted=muted)
        self.DisplayName = ""
        self.IconPath = ""


class BlockingPlaybackPlayer:
    def __init__(self, *, block_load=False):
        self.block_load = block_load
        self.load_started = threading.Event()
        self.release_load = threading.Event()
        self.playing = False
        self.stop_calls = 0
        self.clear_calls = 0
        self.play_loaded_calls = 0
        self.loaded_queries = []
        self.volume = 100
        self.muted = False

    def load(self, query):
        self.loaded_queries.append(query)
        self.load_started.set()
        if self.block_load:
            self.release_load.wait(1.0)
        return SimpleNamespace(title=f"Title for {query}")

    def play_loaded(self):
        self.play_loaded_calls += 1
        self.playing = True

    def is_playing(self):
        return self.playing

    def get_state(self):
        return "Playing" if self.playing else "Opening"

    def get_audio_state(self):
        return {"volume": self.volume, "muted": self.muted, "session_bound": False}

    def get_thumbnail_image(self):
        return None

    def stop(self):
        self.stop_calls += 1
        self.playing = False

    def clear_current_track(self):
        self.clear_calls += 1

    def set_volume(self, volume):
        self.volume = max(0, min(100, int(volume)))

    def set_muted(self, muted):
        self.muted = bool(muted)


class PlaybackHarness(DashboardMusicMixin):
    def __init__(self, player):
        self.logs = []
        self.bridge = FakeBridge()
        self.music_player = player
        self.music_player_initialized = True
        self.music_playback_generation = 0
        self.music_playback_lock = threading.RLock()
        self.music_skip_in_progress = False
        self.music_queue = []
        self.music_queue_titles = {}
        self.current_track_query = ""
        self.current_track_active = False
        self.music_loading = False
        self.current_track_title = ""
        self.current_track_started_at = 0.0
        self._closing = False
        self.audio_volume = 30
        self.audio_muted = False
        self.audio_session_attached = False
        self.volume_slider_widgets = []
        self.volume_value_labels = []
        self.volume_mute_buttons = []
        self.settings = {}

    def append_log(self, message):
        self.logs.append(message)

    def ensure_music_player(self):
        return self.music_player

    def refresh_queue_list_widgets(self, *args, **kwargs):
        pass

    def clear_current_track_ui(self):
        self.current_track_title = ""

    def set_localized_text(self, *args, **kwargs):
        pass


class FakePersistence:
    def update_lock(self):
        return nullcontext()

    def mark_users_dirty(self):
        pass

    def mark_dashboard_dirty(self):
        pass


class MusicQueueV16Tests(unittest.TestCase):
    def wait_until(self, predicate, timeout=1.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return predicate()

    def parse_addressed_music_command(self, message, bot_login="1SalemGPT"):
        trigger = find_trigger(bot_login, ["bot", "بوت", "سلام"], message)
        self.assertIsNotNone(trigger)
        cleaned = remove_trigger(bot_login, message, trigger)
        return parse_chat_music_request(bot_login, trigger, cleaned)

    def run_music_chat_message(self, chatter_name, text, *, badges=None, channel_login="channel", bot_login="1SalemGPT"):
        replies = []
        commands = []

        def fake_write_music_command(_path, action, query="", **kwargs):
            commands.append({"action": action, "query": query, **kwargs})

        handler = create_message_handler(
            "twitch",
            bot_login,
            ["bot", "بوت", "سلام"],
            None,
            {},
            default_dashboard_state(),
            "",
            lambda reply, username, cleaned_text, message_id=None: replies.append(
                {
                    "reply": reply,
                    "username": username,
                    "cleaned_text": cleaned_text,
                    "message_id": message_id,
                }
            ),
            persistence=FakePersistence(),
            channel_login=channel_login,
        )

        with patch("core.eventsub_bot.write_music_command", fake_write_music_command), patch(
            "core.eventsub_bot.get_configured_music_command_aliases",
            return_value=[],
        ), patch("core.eventsub_bot.is_music_enabled", return_value=True):
            handler(chatter_name, text, badges=badges or [], message_id=f"{chatter_name}:{text}")

        return replies, commands

    def test_skip_with_three_songs_starts_next_without_corrupting_queue(self):
        app = MusicHarness(queue=["song 1", "song 2", "song 3"], active=True, playing=True)

        app.skip_current_track()

        self.assertTrue(self.wait_until(lambda: app.music_player.stop_calls == 1))
        self.assertEqual(app.started, ["song 1"])
        self.assertEqual(app.music_queue, ["song 2", "song 3"])
        self.assertTrue(app.current_track_active)
        self.assertFalse(app.music_loading)
        self.assertIn("[Music] Track skipped", app.logs)

    def test_skip_with_one_song_starts_that_song_and_empties_queue(self):
        app = MusicHarness(queue=["only queued song"], active=True, playing=True)

        app.skip_current_track()

        self.assertTrue(self.wait_until(lambda: app.music_player.stop_calls == 1))
        self.assertEqual(app.started, ["only queued song"])
        self.assertEqual(app.music_queue, [])
        self.assertTrue(app.current_track_active)
        self.assertFalse(app.music_loading)

    def test_skip_when_no_song_loaded_resets_cleanly(self):
        app = MusicHarness(queue=[], active=False, loading=False, playing=False)

        app.skip_current_track()

        self.assertEqual(app.music_player.stop_calls, 0)
        self.assertEqual(app.started, [])
        self.assertEqual(app.music_queue, [])
        self.assertFalse(app.current_track_active)
        self.assertFalse(app.music_loading)
        self.assertTrue(any("No current track to skip" in message for message in app.logs))

    def test_skip_starts_next_queued_track_within_five_seconds(self):
        app = MusicHarness(queue=["next song"], active=True, playing=True, stop_delay=0.1)
        started_at = time.monotonic()

        app.skip_current_track()

        self.assertTrue(self.wait_until(lambda: app.started == ["next song"]))
        elapsed = time.monotonic() - started_at
        self.assertLess(elapsed, 5)
        self.assertTrue(app.skip_advance_scheduled)
        self.assertLessEqual(app.skip_advance_max_delay_ms, 5000)

    def test_skip_moves_to_next_playlist_item_within_five_seconds(self):
        app = MusicHarness(queue=["playlist item 2", "playlist item 3"], active=True, playing=True, stop_delay=0.1)
        started_at = time.monotonic()

        app.skip_current_track()

        self.assertTrue(self.wait_until(lambda: app.started == ["playlist item 2"]))
        self.assertLess(time.monotonic() - started_at, 5)
        self.assertEqual(app.music_queue, ["playlist item 3"])

    def test_repeated_skip_is_ignored_while_handoff_is_pending(self):
        app = PendingSkipHarness(queue=["next song"], active=True, playing=True, stop_delay=0.1)

        app.skip_current_track()
        app.skip_current_track()

        self.assertTrue(app.skip_advance_scheduled)
        self.assertTrue(app.music_skip_in_progress)
        self.assertTrue(self.wait_until(lambda: app.music_player.stop_calls == 1))
        self.assertEqual(app.music_player.stop_calls, 1)
        self.assertTrue(any("Skip already in progress" in message for message in app.logs))

    def test_stale_playback_worker_does_not_start_after_stop(self):
        player = BlockingPlaybackPlayer(block_load=True)
        app = PlaybackHarness(player)

        app.start_track_playback("slow song")
        self.assertTrue(self.wait_until(player.load_started.is_set))
        app.stop_youtube_audio()
        player.release_load.set()

        self.assertTrue(self.wait_until(lambda: not app.music_loading))
        self.assertEqual(player.play_loaded_calls, 0)
        self.assertFalse(app.current_track_active)
        self.assertEqual(app.current_track_query, "")
        self.assertEqual(app.bridge.title_signal.items, [])

    def test_current_playback_worker_still_applies_result(self):
        player = BlockingPlaybackPlayer(block_load=False)
        app = PlaybackHarness(player)

        app.start_track_playback("fresh song")

        self.assertTrue(self.wait_until(lambda: app.current_track_active))
        self.assertEqual(player.play_loaded_calls, 1)
        self.assertEqual(app.current_track_query, "fresh song")
        self.assertEqual(app.current_track_title, "Title for fresh song")
        self.assertEqual(app.bridge.title_signal.items, [("Title for fresh song",)])

    def test_single_video_url_still_starts_one_track(self):
        app = MusicHarness()
        video_url = "https://www.youtube.com/watch?v=abc123"

        app.queue_or_play_music(video_url)

        self.assertEqual(app.playlist_import_requests, [])
        self.assertEqual(app.started, [video_url])
        self.assertEqual(app.music_queue, [])

    def test_policy_blocked_title_is_not_added(self):
        app = MusicHarness()
        app.track_request_payloads["blocked song"] = {
            "ok": True,
            "query": "https://www.youtube.com/watch?v=blocked",
            "title": "שיר יפה",
            "channel": "Allowed Channel",
            "blocked": False,
        }

        app.queue_or_play_music("blocked song")

        self.assertEqual(app.started, [])
        self.assertEqual(app.music_queue, [])
        self.assertIn("Track blocked by content policy.", app.logs)

    def test_policy_blocked_channel_is_not_added(self):
        app = MusicHarness(active=True, playing=True)
        app.track_request_payloads["blocked channel"] = {
            "ok": True,
            "query": "https://www.youtube.com/watch?v=blocked",
            "title": "Instrumental",
            "channel": "מוזיקה ישראל",
            "blocked": False,
        }

        app.queue_or_play_music("blocked channel")

        self.assertEqual(app.started, [])
        self.assertEqual(app.music_queue, [])
        self.assertIn("Track blocked by content policy.", app.logs)

    def test_arabic_track_allowed(self):
        app = MusicHarness()
        app.track_request_payloads["arabic song"] = {
            "ok": True,
            "query": "https://www.youtube.com/watch?v=arabic",
            "title": "قصله",
            "channel": "قناة عربية",
            "blocked": False,
        }

        app.queue_or_play_music("arabic song")

        self.assertEqual(app.started, ["https://www.youtube.com/watch?v=arabic"])
        self.assertEqual(app.music_queue, [])

    def test_english_track_allowed(self):
        app = MusicHarness(active=True, playing=True)
        app.track_request_payloads["english song"] = {
            "ok": True,
            "query": "https://www.youtube.com/watch?v=english",
            "title": "Clean Pop Song",
            "channel": "Music Channel",
            "blocked": False,
        }

        app.queue_or_play_music("english song")

        self.assertEqual(app.started, [])
        self.assertEqual(app.music_queue, ["https://www.youtube.com/watch?v=english"])
        self.assertEqual(app.display_track_name("https://www.youtube.com/watch?v=english"), "Clean Pop Song")

    def test_playlist_url_adds_multiple_tracks_and_starts_first_when_idle(self):
        app = MusicHarness()
        app.playlist_payload = {
            "ok": True,
            "tracks": [
                {"title": "One", "query": "https://www.youtube.com/watch?v=one"},
                {"title": "Two", "query": "https://www.youtube.com/watch?v=two"},
                {"title": "Three", "query": "https://www.youtube.com/watch?v=three"},
            ],
            "truncated": False,
        }

        app.queue_or_play_music("https://www.youtube.com/playlist?list=PL123")

        self.assertEqual(app.started, ["https://www.youtube.com/watch?v=one"])
        self.assertEqual(
            app.music_queue,
            [
                "https://www.youtube.com/watch?v=two",
                "https://www.youtube.com/watch?v=three",
            ],
        )
        self.assertEqual(app.display_track_name("https://www.youtube.com/watch?v=two"), "Two")
        self.assertEqual(app.display_track_name("https://www.youtube.com/watch?v=three"), "Three")
        self.assertTrue(any("Added 3 tracks from playlist" in message for message in app.logs))

    def test_playlist_url_queues_all_tracks_when_current_track_is_busy(self):
        app = MusicHarness(active=True, playing=True)
        app.playlist_payload = {
            "ok": True,
            "tracks": [
                {"title": "One", "query": "https://www.youtube.com/watch?v=one"},
                {"title": "Two", "query": "https://www.youtube.com/watch?v=two"},
            ],
            "truncated": False,
        }

        app.queue_or_play_music("https://music.youtube.com/playlist?list=PL123")

        self.assertEqual(app.started, [])
        self.assertEqual(
            app.music_queue,
            [
                "https://www.youtube.com/watch?v=one",
                "https://www.youtube.com/watch?v=two",
            ],
        )
        self.assertEqual(app.display_track_name("https://www.youtube.com/watch?v=one"), "One")
        self.assertEqual(app.display_track_name("https://www.youtube.com/watch?v=two"), "Two")

    def test_queued_youtube_url_displays_resolved_title_not_raw_link(self):
        url = "https://www.youtube.com/watch?v=abc123"
        app = MusicHarness(queue=[], active=True, playing=True)
        app.track_request_payloads[url] = {
            "ok": True,
            "query": url,
            "title": "Resolved Video Title",
            "channel": "Allowed Channel",
            "blocked": False,
        }

        app.queue_or_play_music(url)

        self.assertEqual(app.music_queue, [url])
        self.assertEqual(app.display_track_name(url), "Resolved Video Title")
        self.assertNotEqual(app.display_track_name(url), url)

    def test_youtube_url_without_title_uses_clean_fallback(self):
        url = "https://www.youtube.com/watch?v=missing"
        app = MusicHarness(queue=[], active=True, playing=True)

        app.queue_track_query(url, url)

        self.assertEqual(app.music_queue, [url])
        self.assertEqual(app.display_track_name(url), "YouTube Track")

    def test_playlist_with_mixed_tracks_adds_allowed_only(self):
        app = MusicHarness()
        app.playlist_payload = {
            "ok": True,
            "title": "Mixed playlist",
            "tracks": [
                {"title": "Arabic allowed", "channel": "قناة عربية", "query": "https://www.youtube.com/watch?v=arabic"},
                {"title": "שיר חסום", "channel": "Allowed", "query": "https://www.youtube.com/watch?v=blocked-title"},
                {"title": "English allowed", "channel": "Music Channel", "query": "https://www.youtube.com/watch?v=english"},
                {"title": "Instrumental", "channel": "\u05de\u05d5\u05d6\u05d9\u05e7\u05d4", "query": "https://www.youtube.com/watch?v=blocked-channel"},
            ],
            "truncated": False,
            "blocked_count": 0,
        }

        app.queue_or_play_music("https://www.youtube.com/playlist?list=PL123")

        self.assertEqual(app.started, ["https://www.youtube.com/watch?v=arabic"])
        self.assertEqual(app.music_queue, ["https://www.youtube.com/watch?v=english"])
        self.assertIn("Track blocked by content policy.", app.logs)
        self.assertTrue(any("Skipped 2 playlist tracks" in message for message in app.logs))

    def test_playlist_max_limit_is_enforced(self):
        class FakeYoutubeDL:
            def __init__(self, options):
                self.options = options

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def extract_info(self, url, download=False):
                return {
                    "title": "Big playlist",
                    "entries": [
                        {"id": f"video{i:02d}", "title": f"Video {i}"}
                        for i in range(55)
                    ],
                }

        with patch.object(music_playlist.yt_dlp, "YoutubeDL", FakeYoutubeDL):
            playlist = music_playlist.fetch_youtube_playlist_items(
                "https://youtube.com/playlist?list=PL123",
                max_tracks=50,
            )

        self.assertEqual(len(playlist.tracks), 50)
        self.assertTrue(playlist.truncated)
        self.assertEqual(playlist.tracks[0].query, "https://www.youtube.com/watch?v=video00")

    def test_invalid_private_playlist_shows_clean_error(self):
        app = MusicHarness()

        app.apply_playlist_import_result({"ok": False, "error": "Private playlist"})

        self.assertFalse(app.playlist_import_loading)
        self.assertTrue(any("Playlist could not be loaded: Private playlist" in message for message in app.logs))

    def test_playlist_url_formats_are_detected(self):
        accepted = (
            "https://www.youtube.com/playlist?list=PL123",
            "https://www.youtube.com/watch?v=VIDEO_ID&list=PL123",
            "https://youtube.com/playlist?list=PL123",
            "https://music.youtube.com/playlist?list=PL123",
        )

        for url in accepted:
            with self.subTest(url=url):
                self.assertTrue(music_playlist.is_youtube_playlist_url(url))

        self.assertFalse(music_playlist.is_youtube_playlist_url("https://www.youtube.com/watch?v=VIDEO_ID"))

    def test_normal_chat_message_does_not_parse_as_music_request(self):
        self.assertEqual(parse_music_command("despacito"), (None, ""))
        self.assertEqual(parse_music_command("play despacito"), (None, ""))
        self.assertIsNone(find_trigger("bot", ["bot"], "play despacito"))
        self.assertTrue(looks_like_implicit_music_text("play despacito"))

    def test_explicit_music_command_is_detected_by_chat_trigger(self):
        self.assertEqual(find_trigger("bot", ["bot"], "!sr song name"), "command")

    def test_sr_command_enters_queue_correctly(self):
        action, query = parse_music_command("!sr song name")
        app = MusicHarness(queue=[], active=True, playing=True)

        app.handle_music_action(action, query, source="chat_test")

        self.assertEqual(action, "play")
        self.assertEqual(query, "song name")
        self.assertEqual(app.music_queue, ["song name"])
        self.assertEqual(app.started, [])
        self.assertTrue(any("Track added to queue" in message for message in app.logs))

    def test_duplicate_track_is_ignored_by_default(self):
        app = MusicHarness(queue=["song name"], active=True, playing=True)

        app.handle_music_action("play", "song name", source="chat_test")

        self.assertEqual(app.music_queue, ["song name"])
        self.assertTrue(any("Duplicate track ignored" in message for message in app.logs))

    def test_duplicate_prevention_can_be_disabled(self):
        app = MusicHarness(queue=["song name"], active=True, playing=True)
        app.prevent_duplicate_tracks = False

        app.handle_music_action("play", "song name", source="chat_test")

        self.assertEqual(app.music_queue, ["song name", "song name"])

    def test_volume_command_updates_slider_source_of_truth_and_player(self):
        app = MusicHarness(queue=[], active=False, playing=False)
        app.audio_volume = 30

        app.handle_music_action("volume", "40", source="chat_test")

        self.assertEqual(app.audio_volume, 40)
        self.assertEqual(app.music_player.volume, 40)
        self.assertEqual(app.persisted_audio_settings[-1], (40, False))
        self.assertEqual(app.settings["audio_volume"], 40)
        self.assertTrue(any("Volume set to 40%" in message for message in app.logs))

    def test_vlc_backend_default_100_is_reapplied_to_saved_master_volume(self):
        app = MusicHarness(queue=[], active=False, playing=False)
        app.audio_volume = 30
        app.music_player.backend_volume = 100

        app.handle_music_action("volume", "40", source="chat_test")
        app.poll_audio_state()

        self.assertEqual(app.audio_volume, 40)
        self.assertEqual(app.settings["audio_volume"], 40)
        self.assertEqual(app.music_player.volume, 40)
        self.assertNotIn((100, False), app.persisted_audio_settings)

    def test_programmatic_slider_sync_does_not_rewrite_volume_to_vlc_backend_100(self):
        app = MusicHarness(queue=[], active=False, playing=False)
        app.audio_volume = 40
        app.music_player.backend_volume = 100
        slider_changes = []
        slider = FakeSlider(on_change=lambda value: slider_changes.append(value))
        app.volume_slider_widgets = [slider]

        app.sync_volume_controls()
        app.poll_audio_state()

        self.assertEqual(slider.value, 40)
        self.assertEqual(slider_changes, [])
        self.assertEqual(app.audio_volume, 40)
        self.assertEqual(app.settings.get("audio_volume"), None)

    def test_windows_session_100_does_not_trigger_audio_reapply_loop(self):
        app = MusicHarness(queue=[], active=False, playing=False)
        app.audio_volume = 40
        app.audio_session_attached = True
        app.music_player.backend_volume = 40
        original_set_volume = app.music_player.set_volume
        volume_writes = []

        def record_set_volume(value):
            volume_writes.append(int(value))
            original_set_volume(value)

        app.music_player.set_volume = record_set_volume
        app.music_player.get_audio_state = lambda: {
            "volume": 40,
            "muted": False,
            "backend_volume": 40,
            "backend_muted": False,
            "vlc_volume": 40,
            "windows_session_volume": 100,
            "windows_session_muted": False,
            "session_bound": True,
        }

        app.poll_audio_state()

        self.assertEqual(app.audio_volume, 40)
        self.assertEqual(app.settings.get("audio_volume"), None)
        self.assertEqual(volume_writes, [])

    def test_relative_volume_commands_stay_saved(self):
        app = MusicHarness(queue=[], active=False, playing=False)
        app.audio_volume = 40

        app.handle_music_action("volume", "+10", source="chat_test")
        self.assertEqual(app.audio_volume, 50)
        self.assertEqual(app.settings["audio_volume"], 50)

        app.handle_music_action("volume", "-10", source="chat_test")
        self.assertEqual(app.audio_volume, 40)
        self.assertEqual(app.settings["audio_volume"], 40)

    def test_invalid_volume_command_does_not_change_saved_value(self):
        app = MusicHarness(queue=[], active=False, playing=False)
        app.audio_volume = 40
        app.settings["audio_volume"] = 40

        app.handle_music_action("volume", "loud", source="chat_test")

        self.assertEqual(app.audio_volume, 40)
        self.assertEqual(app.settings["audio_volume"], 40)
        self.assertEqual(app.persisted_audio_settings, [])

    def test_volume_command_clamps_to_zero_and_hundred(self):
        app = MusicHarness(queue=[], active=False, playing=False)
        app.audio_volume = 40

        app.handle_music_action("volume", "150", source="chat_test")
        self.assertEqual(app.audio_volume, 100)
        self.assertEqual(app.settings["audio_volume"], 100)

        app.handle_music_action("volume", "-150", source="chat_test")
        self.assertEqual(app.audio_volume, 0)
        self.assertEqual(app.settings["audio_volume"], 0)

    def test_new_track_applies_saved_volume_before_playback(self):
        player = BlockingPlaybackPlayer(block_load=False)
        app = PlaybackHarness(player)
        app.audio_volume = 30

        app.start_track_playback("fresh song")

        self.assertTrue(self.wait_until(lambda: app.current_track_active))
        self.assertEqual(player.volume, 30)

    def test_skip_next_track_keeps_saved_volume(self):
        app = MusicHarness(queue=["next song"], active=True, playing=True)
        app.audio_volume = 40
        app.music_player.set_volume(40)

        app.skip_current_track()

        self.assertTrue(self.wait_until(lambda: app.started == ["next song"]))
        self.assertEqual(app.audio_volume, 40)
        self.assertEqual(app.music_player.volume, 40)

    def test_player_recreation_applies_saved_volume(self):
        app = MusicHarness(queue=[], active=False, playing=False)
        app.audio_volume = 40
        app.music_player = FakePlayer(playing=False)
        app.music_player_initialized = True

        app.apply_master_volume_to_player("player_recreate", persist=False)

        self.assertEqual(app.audio_volume, 40)
        self.assertEqual(app.music_player.volume, 40)

    def test_music_player_uses_vlc_volume_not_windows_session_writer(self):
        player = object.__new__(MusicPlayer)
        player.player = FakeCoreVlcPlayer(volume=100, muted=False)
        player.target_volume = 100
        player.target_muted = False
        player.audio_session = FakeAudioSession(volume=1.0, muted=False)
        player.audio_session_identity_applied = True
        player.audio_session_name = "1SalemBOT"
        player.last_audio_diagnostic_signature = ""

        with patch("core.music_player.write_diagnostics_line"):
            player.set_volume(40)
            state = player.get_audio_state()

        self.assertEqual(player.target_volume, 40)
        self.assertEqual(player.player.volume_writes, [40])
        self.assertEqual(player.audio_session.SimpleAudioVolume.set_volume_calls, [])
        self.assertEqual(state["vlc_volume"], 40)
        self.assertEqual(state["windows_session_volume"], 100)

    def test_music_player_get_audio_state_does_not_copy_windows_100_into_target(self):
        player = object.__new__(MusicPlayer)
        player.player = FakeCoreVlcPlayer(volume=40, muted=False)
        player.target_volume = 40
        player.target_muted = False
        player.audio_session = FakeAudioSession(volume=1.0, muted=False)
        player.audio_session_identity_applied = True
        player.audio_session_name = "1SalemBOT"
        player.last_audio_diagnostic_signature = ""

        with patch("core.music_player.write_diagnostics_line"):
            state = player.get_audio_state()

        self.assertEqual(player.target_volume, 40)
        self.assertEqual(state["volume"], 40)
        self.assertEqual(state["vlc_volume"], 40)
        self.assertEqual(state["windows_session_volume"], 100)
        self.assertEqual(player.audio_session.SimpleAudioVolume.set_volume_calls, [])

    def test_remove_command_removes_first_queued_item_not_current_track(self):
        app = MusicHarness(queue=["queued one", "queued two"], active=True, playing=True)
        app.current_track_query = "current song"

        app.handle_music_action("remove", "1", source="chat_test")

        self.assertEqual(app.current_track_query, "current song")
        self.assertEqual(app.music_queue, ["queued two"])
        self.assertTrue(any("Removed queue position 1" in message for message in app.logs))

    def test_role_music_command_parsing(self):
        self.assertEqual(parse_music_command("!queue"), ("queue", ""))
        self.assertEqual(parse_music_command("!q"), ("queue", ""))
        self.assertEqual(parse_music_command("!playlist"), ("queue", ""))
        self.assertEqual(parse_music_command("!القائمة"), ("queue", ""))
        self.assertEqual(parse_music_command("!الطابور"), ("queue", ""))
        self.assertEqual(parse_music_command("!skip"), ("skip", ""))
        self.assertEqual(parse_music_command("!تخطي"), ("skip", ""))
        self.assertEqual(parse_music_command("!volume 50"), ("volume", "50"))
        self.assertEqual(parse_music_command("!volume +10"), ("volume", "+10"))
        self.assertEqual(parse_music_command("!volume -10"), ("volume", "-10"))
        self.assertEqual(parse_music_command("!vol +10"), ("volume", "+10"))
        self.assertEqual(parse_music_command("!صوت 50"), ("volume", "50"))
        self.assertEqual(parse_music_command("!remove 3"), ("remove", "3"))
        self.assertEqual(parse_music_command("!rm 3"), ("remove", "3"))
        self.assertEqual(parse_music_command("!حذف 3"), ("remove", "3"))
        self.assertEqual(parse_music_command("!شيل 3"), ("remove", "3"))
        self.assertEqual(parse_music_command("!سكيب"), ("skip", ""))
        self.assertEqual(parse_music_command("!رفع الصوت"), ("volume", "+10"))
        self.assertEqual(parse_music_command("!خفض الصوت"), ("volume", "-10"))

    def test_explicit_music_command_intents_are_semantic(self):
        examples = {
            "!queue": ("queue", None),
            "!q": ("queue", None),
            "!playlist": ("queue", None),
            "!القائمة": ("queue", None),
            "!الطابور": ("queue", None),
            "!skip": ("skip", None),
            "!سكيب": ("skip", None),
            "!تخطي": ("skip", None),
            "!volume 50": ("volume_set", 50),
            "!volume +10": ("volume_up", 10),
            "!volume -10": ("volume_down", 10),
            "!صوت 50": ("volume_set", 50),
            "!رفع الصوت": ("volume_up", 10),
            "!خفض الصوت": ("volume_down", 10),
            "!remove 3": ("remove", 3),
            "!حذف 3": ("remove", 3),
            "!شيل 3": ("remove", 3),
        }

        for message, expected in examples.items():
            with self.subTest(message=message):
                intent = parse_music_intent(message)
                self.assertEqual((intent.action, intent.value), expected)

    def test_natural_bot_addressed_music_controls_parse(self):
        examples = {
            "بوت سكب الأغنية": ("skip", ""),
            "يا بوت تخطى": ("skip", ""),
            "@1salemgpt skip song": ("skip", ""),
            "بوت طوف الأغنية": ("skip", ""),
            "بوت شنو بالقائمة": ("queue", ""),
            "بوت شنو بالطابور": ("queue", ""),
            "بوت شنو بالليستة": ("queue", ""),
            "بوت شنو باقي بالأغاني": ("queue", ""),
            "بوت عرض القائمة": ("queue", ""),
            "بوت عرض الطابور": ("queue", ""),
            "بوت queue": ("queue", ""),
            "بوت علي الصوت": ("volume", "+10"),
            "بوت علّي الصوت": ("volume", "+10"),
            "بوت ارفع الصوت": ("volume", "+10"),
            "بوت رفع الصوت": ("volume", "+10"),
            "بوت زيد الصوت 10": ("volume", "+10"),
            "بوت volume +10": ("volume", "+10"),
            "بوت قصر الصوت": ("volume", "-10"),
            "بوت قصّر الصوت": ("volume", "-10"),
            "بوت خفض الصوت": ("volume", "-10"),
            "بوت نزل الصوت": ("volume", "-10"),
            "بوت وطي الصوت 10": ("volume", "-10"),
            "بوت volume -10": ("volume", "-10"),
            "بوت خلي الصوت 40": ("volume", "40"),
            "بوت الصوت ٤٠": ("volume", "40"),
            "بوت حط الصوت 40": ("volume", "40"),
            "بوت volume 40": ("volume", "40"),
            "بوت vol 40": ("volume", "40"),
            "بوت شيل رقم 3": ("remove", "3"),
            "بوت حذف الأغنية ٣": ("remove", "3"),
            "بوت امسح رقم 3": ("remove", "3"),
            "بوت remove 3": ("remove", "3"),
            "1SalemBOT skip": ("skip", ""),
            "@1SalemGPT سكب هالأغنية": ("skip", ""),
        }

        for message, expected in examples.items():
            with self.subTest(message=message):
                self.assertEqual(self.parse_addressed_music_command(message), expected)

    def test_natural_music_controls_require_bot_address(self):
        ignored_messages = (
            "علي الصوت",
            "قصر الصوت",
            "سكب الأغنية",
            "شنو بالقائمة",
            "شيل رقم 3",
            "الصوت عالي",
            "القائمة طويلة",
            "علي الصوت حلو",
        )

        for message in ignored_messages:
            with self.subTest(message=message):
                trigger = find_trigger("1SalemGPT", ["bot", "بوت", "سلام"], message)
                self.assertIsNone(trigger)

    def test_music_control_roles_allow_mod_vip_broadcaster_and_deny_viewer(self):
        self.assertTrue(chatter_can_control_music("1salemq8", "1salemq8", []))
        self.assertTrue(chatter_can_control_music("mod", "channel", [{"set_id": "moderator", "id": "1"}]))
        self.assertTrue(chatter_can_control_music("lead", "channel", [{"set_id": "lead-moderator", "id": "1"}]))
        self.assertTrue(chatter_can_control_music("vip", "channel", [{"set_id": "vip", "id": "1"}]))
        self.assertFalse(chatter_can_control_music("viewer", "channel", [{"set_id": "subscriber", "id": "1"}]))

    def test_natural_skip_permission_allows_privileged_roles(self):
        allowed_cases = (
            ("channel", "channel", []),
            ("vip_user", "channel", [{"set_id": "vip", "id": "1"}]),
            ("mod_user", "channel", [{"set_id": "moderator", "id": "1"}]),
            ("head_mod", "channel", [{"set_id": "head-moderator", "id": "1"}]),
        )

        for chatter_name, channel_login, badges in allowed_cases:
            with self.subTest(chatter_name=chatter_name):
                replies, commands = self.run_music_chat_message(
                    chatter_name,
                    "بوت سكب الأغنية",
                    badges=badges,
                    channel_login=channel_login,
                )
                self.assertEqual([command["action"] for command in commands], ["skip"])
                self.assertTrue(replies)

    def test_natural_restricted_controls_deny_normal_viewer(self):
        for message in ("بوت سكب الأغنية", "بوت خلي الصوت 40", "بوت شيل رقم 3"):
            with self.subTest(message=message):
                replies, commands = self.run_music_chat_message(
                    "viewer",
                    message,
                    badges=[{"set_id": "subscriber", "id": "1"}],
                    channel_login="channel",
                )
                self.assertEqual(commands, [])
                self.assertTrue(any("VIP" in item["reply"] for item in replies))

    def test_normal_viewer_can_use_natural_queue(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            queue_file = Path(temp_dir) / "music_queue_state.json"
            save_json(queue_file, {"queue": []})
            with patch("core.eventsub_bot.MUSIC_QUEUE_STATE_FILE", queue_file):
                replies, commands = self.run_music_chat_message(
                    "viewer",
                    "بوت شنو بالقائمة",
                    badges=[{"set_id": "subscriber", "id": "1"}],
                    channel_login="channel",
                )

        self.assertEqual(commands, [])
        self.assertEqual(len(replies), 1)
        self.assertIn("@viewer", replies[0]["reply"])

    def test_bot_ignores_own_natural_music_messages(self):
        replies, commands = self.run_music_chat_message(
            "1SalemGPT",
            "بوت سكب الأغنية",
            badges=[{"set_id": "moderator", "id": "1"}],
        )

        self.assertEqual(replies, [])
        self.assertEqual(commands, [])

    def test_queue_reply_shows_first_ten_and_total_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            queue_file = Path(temp_dir) / "music_queue_state.json"
            save_json(
                queue_file,
                {
                    "queue": [
                        {"position": index, "title": f"Track {index}", "query": f"query {index}"}
                        for index in range(1, 13)
                    ]
                },
            )
            with patch("core.eventsub_bot.MUSIC_QUEUE_STATE_FILE", queue_file):
                reply = format_music_queue_reply("viewer")

        self.assertIn("@viewer", reply)
        self.assertIn("1. Track 1", reply)
        self.assertIn("10. Track 10", reply)
        self.assertNotIn("11. Track 11", reply)
        self.assertIn("total 12", reply)

    def test_arabic_bot_addressed_requests_enter_music_queue(self):
        examples = {
            "بوت شغل قصله": "قصله",
            "يا بوت شغل قصله": "قصله",
            "بوت شغل اغنية قصله": "قصله",
            "1SalemGPT شغل قصله": "قصله",
            "@1SalemGPT شغل قصله": "قصله",
        }

        for message, expected_query in examples.items():
            with self.subTest(message=message):
                trigger = find_trigger("1SalemGPT", ["bot", "بوت", "سلام"], message)
                cleaned = remove_trigger("1SalemGPT", message, trigger)
                action, query = parse_chat_music_request("1SalemGPT", trigger, cleaned)
                self.assertEqual(action, "play")
                self.assertEqual(query, expected_query)

    def test_explicit_music_commands_still_work_with_arabic_query(self):
        for message in ("!sr قصله", "!songrequest قصله", "!play قصله"):
            with self.subTest(message=message):
                trigger = find_trigger("1SalemGPT", ["bot", "بوت", "سلام"], message)
                cleaned = remove_trigger("1SalemGPT", message, trigger)
                action, query = parse_chat_music_request("1SalemGPT", trigger, cleaned)
                self.assertEqual(action, "play")
                self.assertEqual(query, "قصله")

    def test_normal_arabic_chat_does_not_enter_music_queue(self):
        ignored_messages = ("شغل قصله", "play قصله", "قصله", "ابي اغنية قصله")

        for message in ignored_messages:
            with self.subTest(message=message):
                trigger = find_trigger("1SalemGPT", ["bot", "بوت", "سلام"], message)
                self.assertIsNone(trigger)


if __name__ == "__main__":
    unittest.main()

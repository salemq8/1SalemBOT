import threading
import time
import unittest
from unittest.mock import patch

from core.music_commands import looks_like_implicit_music_text, parse_music_command
from core.eventsub_bot import find_trigger, parse_chat_music_request, remove_trigger
from core import music_playlist
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
        self.music_enabled = True
        self.playlist_import_loading = False
        self.playlist_import_requests = []
        self.playlist_payload = None
        self.track_request_payloads = {}
        self.music_entry = FakeLineEdit()
        self.music_page_input = FakeLineEdit()

    def append_log(self, message):
        self.logs.append(message)

    def ensure_music_player(self):
        return self.music_player

    def refresh_queue_list_widgets(self):
        self.queue_refreshes += 1

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


class MusicQueueV16Tests(unittest.TestCase):
    def wait_until(self, predicate, timeout=1.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return predicate()

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

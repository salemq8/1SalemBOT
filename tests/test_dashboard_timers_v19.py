import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.app_state import save_json
from core.ui import window as window_module
from core.ui.music_mixin import DashboardMusicMixin
from core.ui.viewers_mixin import DashboardViewersMixin
from core.ui.window import DashboardApp


class FakeTimer:
    def __init__(self):
        self._active = False
        self._interval = 0

    def interval(self):
        return self._interval

    def setInterval(self, value):
        self._interval = int(value)

    def isActive(self):
        return self._active

    def start(self):
        self._active = True

    def stop(self):
        self._active = False


class DashboardCacheHarness:
    file_signature = DashboardApp.file_signature
    cached_file_changed = DashboardApp.cached_file_changed
    refresh_cached_runtime_state = DashboardApp.refresh_cached_runtime_state

    def __init__(self):
        self.file_signature_cache = {}
        self.dashboard_state = {}
        self.users_data = {}


class FakeChart:
    def __init__(self):
        self.calls = 0

    def set_series_data(self, *args, **kwargs):
        self.calls += 1


class FakeChatRenderer:
    def __init__(self):
        self.calls = 0

    def build_chat_html(self, entries, channel_login, fetch_remote_assets=False):
        self.calls += 1
        return f"{channel_login}:{len(entries)}"


class DashboardSectionHarness:
    set_label_text_if_changed = DashboardApp.set_label_text_if_changed
    refresh_dashboard_chart = DashboardApp.refresh_dashboard_chart
    refresh_dashboard_top_chatters = DashboardApp.refresh_dashboard_top_chatters
    refresh_dashboard_chat_preview = DashboardApp.refresh_dashboard_chat_preview
    refresh_dashboard_alert_card = DashboardApp.refresh_dashboard_alert_card

    def __init__(self):
        self.dashboard_state = {
            "analytics_history": [
                {"date": "2026-06-17", "messages": 10, "commands": 2, "timeouts": 0},
            ],
            "top_chatters": {"hayouna6": 5},
            "recent_chat": [
                {"username": "hayouna6", "text": "hello", "timestamp": "now", "platform": "twitch"},
            ],
        }
        self.dashboard_ui_signatures = {}
        self.dashboard_chart = FakeChart()
        self.table_calls = 0
        self.synced_html = []
        self.asset_warmup_calls = 0
        self.chat_renderer = FakeChatRenderer()
        self.chat_live = object()
        self.chat_page_text = object()
        self.top_chatters_table = object()
        self.dashboard_alert_rows_layout = object()
        self.alert_card_refreshes = 0
        self.alert_items = [{"id": "one"}]
        self.alert_load_calls = 0

    def populate_dashboard_table(self, *args, **kwargs):
        self.table_calls += 1

    def current_channel_login(self):
        return "channel"

    def sync_scroll_html(self, widget, html):
        self.synced_html.append((widget, html))

    def request_chat_asset_warmup(self, entries):
        self.asset_warmup_calls += 1

    def load_alert_feed_items(self, force=False):
        self.alert_load_calls += 1
        return self.alert_items

    def get_latest_alert_feed_items(self, limit=3):
        return self.alert_items[:limit]

    def alert_render_log_key(self, item):
        return item.get("id", "")

    def refresh_dashboard_alerts(self):
        self.alert_card_refreshes += 1


class TimerPolicyHarness:
    set_timer_policy_state = DashboardApp.set_timer_policy_state
    music_runtime_active = DashboardApp.music_runtime_active
    update_runtime_timer_policy = DashboardApp.update_runtime_timer_policy

    def __init__(self):
        self.current_page_name = "Dashboard"
        self.process = None
        self.alerts_process = None
        self.external_bot_runtime_active = False
        self.external_alert_runtime_active = False
        self.music_loading = False
        self.current_track_active = False
        self.music_player = None
        self.audio_session_attached = False
        self.auth_health_state = {
            window_module.BOT_AUTH_ROLE: {"state": "disconnected"},
            window_module.CHANNEL_AUTH_ROLE: {"state": "disconnected"},
        }
        self.timer_dashboard = FakeTimer()
        self.timer_music = FakeTimer()
        self.timer_player = FakeTimer()
        self.timer_audio = FakeTimer()
        self.timer_process = FakeTimer()
        self.timer_alerts = FakeTimer()


class MusicCommandHarness:
    file_signature = DashboardApp.file_signature
    cached_file_changed = DashboardApp.cached_file_changed
    process_music_command = DashboardMusicMixin.process_music_command
    refresh_queue_list_widgets = DashboardMusicMixin.refresh_queue_list_widgets
    refresh_queue_count_labels = DashboardMusicMixin.refresh_queue_count_labels

    def __init__(self):
        self.file_signature_cache = {}
        self.last_music_command_timestamp = ""
        self.music_enabled = True
        self.logs = []
        self.music_queue = []
        self.music_queue_render_signature = None
        self.queue_count_labels = []
        self.queue_listbox = None
        self.music_page_queue = None
        self.language = "en"

    def append_log(self, message):
        self.logs.append(message)

    def handle_music_action(self, action, query, source=""):
        self.last_action = (action, query, source)

    def display_track_name(self, item):
        return f"title:{item}"

    def set_dynamic_text(self, label, text):
        label.setText(text)

    def localize(self, text):
        return text


class FakeQueueWidget:
    def __init__(self):
        self.items = []
        self.clear_calls = 0
        self.current_row = None

    def clear(self):
        self.clear_calls += 1
        self.items = []

    def addItem(self, text):
        self.items.append(text)

    def setCurrentRow(self, index):
        self.current_row = index


class FakeLabel:
    def __init__(self):
        self.text_value = ""

    def setText(self, text):
        self.text_value = text


class ViewerSearchHarness:
    on_viewer_search_changed = DashboardViewersMixin.on_viewer_search_changed
    apply_viewer_search_changed = DashboardViewersMixin.apply_viewer_search_changed

    def __init__(self):
        self.viewer_current_page = 4
        self.refresh_count = 0

    def refresh_viewers_dashboard(self):
        self.refresh_count += 1


class DashboardTimersV19Tests(unittest.TestCase):
    def setUp(self):
        self.app = QApplication.instance() or QApplication([])

    def test_dashboard_cached_state_skips_unchanged_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            dashboard_file = Path(temp_dir) / "dashboard_state.json"
            users_file = Path(temp_dir) / "users.json"
            save_json(dashboard_file, {"messages_today": 1})
            save_json(users_file, {"user": {"messages": 1}})
            harness = DashboardCacheHarness()

            with (
                patch.object(window_module, "DASHBOARD_STATE_FILE", dashboard_file),
                patch.object(window_module, "USERS_FILE", users_file),
                patch.object(window_module, "load_dashboard_state", return_value={"messages_today": 1}) as dashboard_load,
                patch.object(window_module, "load_json", return_value={"user": {"messages": 1}}) as json_load,
            ):
                self.assertEqual(harness.refresh_cached_runtime_state(), {"dashboard": True, "users": True})
                self.assertEqual(harness.refresh_cached_runtime_state(), {"dashboard": False, "users": False})
                self.assertEqual(dashboard_load.call_count, 1)
                self.assertEqual(json_load.call_count, 1)

                save_json(dashboard_file, {"messages_today": 2})
                self.assertEqual(harness.refresh_cached_runtime_state()["dashboard"], True)
                self.assertEqual(dashboard_load.call_count, 2)

    def test_dashboard_sections_skip_unchanged_signatures(self):
        harness = DashboardSectionHarness()

        self.assertTrue(harness.refresh_dashboard_chart())
        self.assertFalse(harness.refresh_dashboard_chart())
        self.assertEqual(harness.dashboard_chart.calls, 1)

        self.assertTrue(harness.refresh_dashboard_top_chatters())
        self.assertFalse(harness.refresh_dashboard_top_chatters())
        self.assertEqual(harness.table_calls, 1)

        self.assertTrue(harness.refresh_dashboard_chat_preview())
        self.assertFalse(harness.refresh_dashboard_chat_preview())
        self.assertEqual(harness.chat_renderer.calls, 1)
        self.assertEqual(harness.asset_warmup_calls, 1)

        self.assertTrue(harness.refresh_dashboard_alert_card())
        self.assertFalse(harness.refresh_dashboard_alert_card())
        self.assertEqual(harness.alert_card_refreshes, 1)

    def test_dashboard_sections_update_when_signatures_change(self):
        harness = DashboardSectionHarness()
        harness.refresh_dashboard_chart()
        harness.refresh_dashboard_top_chatters()
        harness.refresh_dashboard_chat_preview()
        harness.refresh_dashboard_alert_card()

        harness.dashboard_state["analytics_history"][0]["messages"] = 11
        harness.dashboard_state["top_chatters"]["newviewer"] = 9
        harness.dashboard_state["recent_chat"].append(
            {"username": "newviewer", "text": "hi", "timestamp": "later", "platform": "twitch"}
        )
        harness.alert_items = [{"id": "two"}]

        self.assertTrue(harness.refresh_dashboard_chart())
        self.assertTrue(harness.refresh_dashboard_top_chatters())
        self.assertTrue(harness.refresh_dashboard_chat_preview())
        self.assertTrue(harness.refresh_dashboard_alert_card())
        self.assertEqual(harness.dashboard_chart.calls, 2)
        self.assertEqual(harness.table_calls, 2)
        self.assertEqual(harness.chat_renderer.calls, 2)
        self.assertEqual(harness.alert_card_refreshes, 2)

    def test_timer_policy_stops_inactive_timers(self):
        harness = TimerPolicyHarness()
        harness.update_runtime_timer_policy()

        self.assertTrue(harness.timer_dashboard.isActive())
        self.assertEqual(harness.timer_dashboard.interval(), 5000)
        self.assertFalse(harness.timer_music.isActive())
        self.assertFalse(harness.timer_player.isActive())
        self.assertFalse(harness.timer_audio.isActive())
        self.assertFalse(harness.timer_process.isActive())
        self.assertFalse(harness.timer_alerts.isActive())

    def test_timer_policy_wakes_for_music_page_and_channel_alerts(self):
        harness = TimerPolicyHarness()
        harness.current_page_name = "Music"
        harness.auth_health_state[window_module.CHANNEL_AUTH_ROLE] = {"state": "connected"}
        harness.music_loading = True
        harness.update_runtime_timer_policy()

        self.assertTrue(harness.timer_dashboard.isActive())
        self.assertEqual(harness.timer_dashboard.interval(), 10000)
        self.assertTrue(harness.timer_music.isActive())
        self.assertTrue(harness.timer_player.isActive())
        self.assertTrue(harness.timer_audio.isActive())
        self.assertTrue(harness.timer_alerts.isActive())

    def test_music_command_poll_skips_unchanged_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            command_file = Path(temp_dir) / "music_command.json"
            save_json(command_file, {"timestamp": "one", "action": "play", "query": "song", "source": "test"})
            harness = MusicCommandHarness()
            with patch("core.ui.music_mixin.MUSIC_COMMAND_FILE", command_file):
                harness.process_music_command()
                harness.process_music_command()

            self.assertEqual(harness.last_action, ("play", "song", "command_file:test"))

    def test_queue_refresh_skips_unchanged_queue(self):
        harness = MusicCommandHarness()
        queue_widget = FakeQueueWidget()
        page_widget = FakeQueueWidget()
        count_label = FakeLabel()
        harness.queue_listbox = queue_widget
        harness.music_page_queue = page_widget
        harness.queue_count_labels = [count_label]
        harness.music_queue = ["a", "b"]

        harness.refresh_queue_list_widgets()
        harness.refresh_queue_list_widgets()

        self.assertEqual(queue_widget.clear_calls, 1)
        self.assertEqual(page_widget.clear_calls, 1)
        self.assertEqual(queue_widget.items, ["1. title:a", "2. title:b"])
        self.assertEqual(count_label.text_value, "Queue: 2 tracks")

        harness.music_queue.append("c")
        harness.refresh_queue_list_widgets(selected_index=2)
        self.assertEqual(queue_widget.clear_calls, 2)
        self.assertEqual(queue_widget.current_row, 2)

    def test_viewer_search_is_debounced(self):
        harness = ViewerSearchHarness()
        harness.on_viewer_search_changed()
        self.assertEqual(harness.viewer_current_page, 1)
        self.assertEqual(harness.refresh_count, 0)
        self.assertTrue(harness.viewer_search_debounce_timer.isActive())
        harness.viewer_search_debounce_timer.stop()
        harness.apply_viewer_search_changed()
        self.assertEqual(harness.refresh_count, 1)


if __name__ == "__main__":
    unittest.main()

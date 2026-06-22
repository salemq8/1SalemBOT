import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from core.ui.window import DashboardApp


class RestartHarness:
    def __init__(self):
        self.logs = []
        self.stop_calls = 0
        self.start_calls = 0
        self.alert_ensure_calls = 0
        self.restart_in_progress = False
        self.startup_auto_restart_scheduled = False
        self.startup_auto_restart_ran = False
        self.restart_sources = []
        self.startup_timer_scheduled = False
        self.auto_restart_bot_on_startup = True
        self.bot_health_reconnect_attempts = 0
        self.bot_health_next_reconnect_at = 0.0
        self.bot_health_last_reason = ""
        self.settings = {"openai_api_key": "test-key"}
        self.bot_login = "1SalemGPT"
        self.channel_login = "1SalemQ8"

    def append_log(self, message):
        self.logs.append(message)

    def request_bot_restart(self, source="manual"):
        return DashboardApp.request_bot_restart(self, source=source)

    def stop_bot(self):
        self.stop_calls += 1

    def start_bot(self):
        self.start_calls += 1
        return True

    def ensure_alerts_listener(self):
        self.alert_ensure_calls += 1

    def current_bot_login(self):
        return self.bot_login

    def current_channel_login(self):
        return self.channel_login

    def schedule_restart_start(self, source):
        self.restart_sources.append(source)
        DashboardApp.complete_bot_restart(self, source)

    def schedule_startup_auto_restart_timer(self):
        self.startup_timer_scheduled = True


class RestartV16Tests(unittest.TestCase):
    def test_manual_restart_uses_existing_stop_start_sequence(self):
        app = RestartHarness()

        result = DashboardApp.request_bot_restart(app, source="manual")

        self.assertTrue(result)
        self.assertEqual(app.stop_calls, 1)
        self.assertEqual(app.start_calls, 1)
        self.assertEqual(app.alert_ensure_calls, 0)
        self.assertFalse(app.restart_in_progress)
        self.assertEqual(app.restart_sources, ["manual"])
        self.assertIn("[BOT] Manual restart requested.", app.logs)
        self.assertIn("[BOT] Manual restart completed.", app.logs)

    def test_overlapping_restart_is_blocked_until_current_finishes(self):
        app = RestartHarness()
        app.restart_in_progress = True

        result = DashboardApp.request_bot_restart(app, source="manual")

        self.assertFalse(result)
        self.assertEqual(app.stop_calls, 0)
        self.assertEqual(app.start_calls, 0)
        self.assertEqual(app.alert_ensure_calls, 0)
        self.assertIn("[BOT] Manual restart ignored because another restart is already running.", app.logs)

    def test_startup_auto_restart_schedules_once_and_runs_once(self):
        app = RestartHarness()

        DashboardApp.schedule_startup_auto_restart(app)
        DashboardApp.schedule_startup_auto_restart(app)

        self.assertTrue(app.startup_timer_scheduled)
        self.assertTrue(app.startup_auto_restart_scheduled)
        self.assertEqual(app.logs.count("[BOOT] Startup auto restart scheduled."), 1)

        with patch("core.ui.window.load_token_details", return_value={"access_token": "bot-token"}):
            DashboardApp.run_startup_auto_restart(app)
            DashboardApp.run_startup_auto_restart(app)

        self.assertTrue(app.startup_auto_restart_ran)
        self.assertEqual(app.stop_calls, 1)
        self.assertEqual(app.start_calls, 1)
        self.assertEqual(app.alert_ensure_calls, 0)
        self.assertEqual(app.restart_sources, ["startup"])
        self.assertIn("[BOOT] Startup auto restart scheduled.", app.logs)
        self.assertIn("[BOOT] Startup auto restart starting bot.", app.logs)
        self.assertIn("[BOOT] Startup auto restart completed.", app.logs)

    def test_startup_auto_restart_blocks_when_manual_restart_is_running(self):
        app = RestartHarness()
        app.restart_in_progress = True

        DashboardApp.run_startup_auto_restart(app)

        self.assertTrue(app.startup_auto_restart_ran)
        self.assertEqual(app.stop_calls, 0)
        self.assertEqual(app.start_calls, 0)
        self.assertIn("[BOOT] Startup auto restart skipped: another restart is already running.", app.logs)

    def test_startup_auto_restart_setting_can_disable_schedule(self):
        app = RestartHarness()
        app.auto_restart_bot_on_startup = False

        DashboardApp.schedule_startup_auto_restart(app)

        self.assertFalse(app.startup_timer_scheduled)
        self.assertFalse(app.startup_auto_restart_scheduled)
        self.assertIn("[BOOT] Startup auto restart skipped: disabled.", app.logs)

    def test_startup_auto_restart_missing_bot_account_skips_cleanly(self):
        app = RestartHarness()

        with patch("core.ui.window.load_token_details", return_value={"access_token": ""}):
            result = DashboardApp.run_startup_auto_restart(app)

        self.assertFalse(result)
        self.assertTrue(app.startup_auto_restart_ran)
        self.assertEqual(app.stop_calls, 0)
        self.assertEqual(app.start_calls, 0)
        self.assertIn("[BOOT] Startup auto restart skipped: Bot Account not connected.", app.logs)

    def test_startup_auto_restart_missing_config_skips_before_restart_sequence(self):
        app = RestartHarness()
        app.channel_login = ""

        with patch("core.ui.window.load_token_details", return_value={"access_token": "bot-token"}):
            result = DashboardApp.run_startup_auto_restart(app)

        self.assertFalse(result)
        self.assertEqual(app.stop_calls, 0)
        self.assertEqual(app.start_calls, 0)
        self.assertIn("[BOOT] Startup auto restart skipped: Bot Login or Channel Login missing.", app.logs)

    def test_startup_auto_restart_existing_running_bot_uses_safe_restart_sequence(self):
        app = RestartHarness()

        with patch("core.ui.window.load_token_details", return_value={"access_token": "bot-token"}):
            result = DashboardApp.run_startup_auto_restart(app)

        self.assertTrue(result)
        self.assertEqual(app.stop_calls, 1)
        self.assertEqual(app.start_calls, 1)
        self.assertEqual(app.restart_sources, ["startup"])

    def test_bot_health_reconnect_uses_restart_sequence(self):
        app = RestartHarness()
        runtime_state = {
            "pid": 123,
            "status": "stale",
            "heartbeat_at": datetime.now().isoformat(timespec="seconds"),
        }

        result = DashboardApp.maybe_reconnect_stale_bot_runtime(app, runtime_state)

        self.assertTrue(result)
        self.assertEqual(app.stop_calls, 1)
        self.assertEqual(app.start_calls, 1)
        self.assertEqual(app.restart_sources, ["health"])
        self.assertIn("[BOT] Bot connection stale, reconnecting", app.logs)
        self.assertIn("[BOT] Bot reconnected", app.logs)

    def test_bot_health_heartbeat_age_triggers_reconnect(self):
        app = RestartHarness()
        old_heartbeat = (datetime.now() - timedelta(seconds=120)).isoformat(timespec="seconds")
        runtime_state = {"pid": 123, "status": "connected", "heartbeat_at": old_heartbeat}

        result = DashboardApp.maybe_reconnect_stale_bot_runtime(app, runtime_state)

        self.assertTrue(result)
        self.assertEqual(app.restart_sources, ["health"])

    def test_bot_health_reconnect_respects_backoff(self):
        app = RestartHarness()
        app.bot_health_next_reconnect_at = 999999999.0
        runtime_state = {"pid": 123, "status": "stale", "heartbeat_at": datetime.now().isoformat(timespec="seconds")}

        with patch("core.ui.window.time.monotonic", return_value=1.0):
            result = DashboardApp.maybe_reconnect_stale_bot_runtime(app, runtime_state)

        self.assertFalse(result)
        self.assertEqual(app.stop_calls, 0)
        self.assertEqual(app.start_calls, 0)


if __name__ == "__main__":
    unittest.main()

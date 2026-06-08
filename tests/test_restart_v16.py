import unittest

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

    def append_log(self, message):
        self.logs.append(message)

    def request_bot_restart(self, source="manual"):
        return DashboardApp.request_bot_restart(self, source=source)

    def stop_bot(self):
        self.stop_calls += 1

    def start_bot(self):
        self.start_calls += 1

    def ensure_alerts_listener(self):
        self.alert_ensure_calls += 1

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
        self.assertEqual(app.logs.count("[BOOT] Waiting 3 seconds before automatic startup restart..."), 1)

        DashboardApp.run_startup_auto_restart(app)
        DashboardApp.run_startup_auto_restart(app)

        self.assertTrue(app.startup_auto_restart_ran)
        self.assertEqual(app.stop_calls, 1)
        self.assertEqual(app.start_calls, 1)
        self.assertEqual(app.alert_ensure_calls, 0)
        self.assertEqual(app.restart_sources, ["startup"])
        self.assertIn("[BOOT] Automatic startup restart triggered.", app.logs)
        self.assertIn("[BOOT] Automatic startup restart completed.", app.logs)

    def test_startup_auto_restart_blocks_when_manual_restart_is_running(self):
        app = RestartHarness()
        app.restart_in_progress = True

        DashboardApp.run_startup_auto_restart(app)

        self.assertTrue(app.startup_auto_restart_ran)
        self.assertEqual(app.stop_calls, 0)
        self.assertEqual(app.start_calls, 0)
        self.assertIn("[BOOT] Automatic startup restart ignored because another restart is already running.", app.logs)

    def test_startup_auto_restart_setting_can_disable_schedule(self):
        app = RestartHarness()
        app.auto_restart_bot_on_startup = False

        DashboardApp.schedule_startup_auto_restart(app)

        self.assertFalse(app.startup_timer_scheduled)
        self.assertFalse(app.startup_auto_restart_scheduled)
        self.assertIn("[BOOT] Automatic startup restart disabled in settings.", app.logs)


if __name__ == "__main__":
    unittest.main()

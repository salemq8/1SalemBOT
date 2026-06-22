import unittest

from core.ui.window import DashboardApp


class AlertLogHarness:
    alert_render_log_key = DashboardApp.alert_render_log_key
    log_rendered_alert_events = DashboardApp.log_rendered_alert_events

    def __init__(self):
        self.rendered_alert_log_ids = set()
        self.logs = []

    def append_log(self, text):
        self.logs.append(text)


class AlertLoggingV19Tests(unittest.TestCase):
    def test_cached_alert_render_logs_one_summary_and_dedupes_by_event_id(self):
        harness = AlertLogHarness()
        items = [
            {"id": "a1", "event_type": "channel.follow", "username": "one"},
            {"id": "a2", "event_type": "channel.follow", "username": "two"},
            {"id": "a3", "event_type": "channel.cheer", "username": "three"},
        ]

        harness.log_rendered_alert_events(items, source="cached")
        harness.log_rendered_alert_events(items, source="cached")
        harness.log_rendered_alert_events(
            [
                {"id": "a4", "event_type": "channel.raid", "username": "four"},
            ],
            source="cached",
        )

        self.assertEqual(len(harness.logs), 1)
        self.assertIn("[Alerts] Rendered 3 cached events:", harness.logs[0])
        self.assertIn("2 channel.follow", harness.logs[0])
        self.assertIn("1 channel.cheer", harness.logs[0])

    def test_same_type_alerts_without_ids_use_stable_full_event_keys(self):
        harness = AlertLogHarness()
        items = [
            {"event_type": "channel.follow", "username": "one", "occurred_at": "2026-06-16T01:00:00Z"},
            {"event_type": "channel.follow", "username": "two", "occurred_at": "2026-06-16T01:00:01Z"},
        ]

        harness.log_rendered_alert_events(items, source="cached")

        self.assertEqual(len(harness.logs), 1)
        self.assertIn("2 channel.follow", harness.logs[0])


if __name__ == "__main__":
    unittest.main()

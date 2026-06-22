import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import runtime_logging
from core.eventsub_bot import send_twitch_reply
from core.ui.window import DashboardApp


class RuntimeLoggingV19Tests(unittest.TestCase):
    def tearDown(self):
        runtime_logging.reset_repeated_log_state()

    def test_verbose_lines_are_classified_as_diagnostics(self):
        self.assertTrue(runtime_logging.is_diagnostic_log_line(r"[TWITCH AUTH] Bot token path: C:\Users\name\AppData\Roaming\1SalemBOT\twitch_bot_auth.json"))
        self.assertTrue(runtime_logging.is_diagnostic_log_line("[EVENTSUB] Connecting to WebSocket: wss://eventsub.wss.twitch.tv/ws"))
        self.assertTrue(runtime_logging.is_diagnostic_log_line("[TWITCH CHAT] hayouna6: raw chat text"))
        self.assertTrue(runtime_logging.is_diagnostic_log_line("[VIEWERS] Counted message from hayouna6"))
        self.assertFalse(runtime_logging.is_diagnostic_log_line("[TWITCH] Connected"))

    def test_diagnostics_are_rotated_and_secrets_redacted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "diagnostics.log"
            log_file.write_text("x" * 128, encoding="utf-8")

            runtime_logging.write_diagnostics_line(
                "Authorization: Bearer secret-token access_token=abc123",
                log_file=log_file,
                max_bytes=32,
            )

            self.assertTrue(log_file.with_name("diagnostics.log.1").exists())
            content = log_file.read_text(encoding="utf-8")
            self.assertIn("Authorization: Bearer <redacted>", content)
            self.assertIn("access_token=<redacted>", content)
            self.assertNotIn("secret-token", content)
            self.assertNotIn("abc123", content)

    def test_high_frequency_chat_lines_are_suppressed_and_summarized(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "diagnostics.log"
            for index in range(1000):
                routed = runtime_logging.route_diagnostic_line(
                    f"[TWITCH CHAT] user{index % 25}: message {index}",
                    log_file=log_file,
                )
                self.assertTrue(routed)
            runtime_logging.flush_repeated_log_summaries(log_file=log_file)

            lines = log_file.read_text(encoding="utf-8").splitlines()
            self.assertLess(len(lines), 20)
            self.assertIn("[TWITCH CHAT] user0: message 0", lines[0])
            self.assertTrue(any("Repeated" in line and "chat message received" in line for line in lines))

    def test_sensitive_auth_details_route_to_redacted_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "diagnostics.log"
            self.assertTrue(
                runtime_logging.route_diagnostic_line(
                    r"[TWITCH AUTH] Bot token path: C:\Users\name\AppData\Roaming\1SalemBOT\twitch_bot_auth.json user_id=123 scopes=chat:read chat:edit",
                    log_file=log_file,
                )
            )
            content = log_file.read_text(encoding="utf-8")
            self.assertIn("user_id=<redacted>", content)
            self.assertIn("scopes=<redacted>", content)
            self.assertIn("<path>", content)
            self.assertNotIn("123", content)
            self.assertNotIn("AppData", content)


class LiveLogPolicyHarness:
    append_log = DashboardApp.append_log
    prepare_live_log_line = DashboardApp.prepare_live_log_line

    def __init__(self):
        self.pending_log_lines = []
        self.live_log_repeat_state = {}
        self.live_log = None
        self.log_flush_timer = None


class LiveLogRoutingV19Tests(unittest.TestCase):
    def test_chat_debug_lines_do_not_enter_normal_live_log(self):
        harness = LiveLogPolicyHarness()
        with patch("core.ui.window.route_diagnostic_line", return_value=True):
            for index in range(1000):
                harness.append_log(f"[TWITCH CHAT] user{index}: raw message {index}")
        self.assertEqual(harness.pending_log_lines, [])

    def test_repeated_normal_lines_are_collapsed(self):
        harness = LiveLogPolicyHarness()
        with patch("core.ui.window.route_diagnostic_line", return_value=False), patch("builtins.print"):
            for _index in range(30):
                harness.append_log("[BOT] Bot replied to @hayouna6")

        visible_lines = [entry[1] for entry in harness.pending_log_lines]
        self.assertEqual(visible_lines[0], "[BOT] Bot replied to @hayouna6")
        self.assertIn("Repeated 25 times: [BOT] Bot replied to @hayouna6", visible_lines)
        self.assertLess(len(visible_lines), 4)

    def test_successful_reply_logs_concise_normal_event_only(self):
        with (
            patch("core.eventsub_bot.send_chat_message", return_value={"ok": True}),
            patch("core.eventsub_bot.log_chat"),
            patch("core.eventsub_bot.safe_print") as safe_print,
        ):
            send_twitch_reply("token", "channel-id", "bot-id", "@hayouna6 هلا فيك", "hayouna6", "هلا")

        printed = [" ".join(str(part) for part in call.args) for call in safe_print.call_args_list]
        self.assertIn("[BOT] Bot replied to @hayouna6", printed)
        self.assertTrue(any(line.startswith("[TWITCH SEND]") for line in printed))


if __name__ == "__main__":
    unittest.main()

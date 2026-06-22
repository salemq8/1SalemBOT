import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import chat_storage


class FlakyAppendPath:
    def __init__(self, path, fail_appends=0):
        self.path = Path(path)
        self.fail_appends = fail_appends
        self.append_attempts = 0

    def __fspath__(self):
        return str(self.path)

    @property
    def parent(self):
        return self.path.parent

    def exists(self):
        return self.path.exists()

    def stat(self):
        return self.path.stat()

    def read_text(self, *args, **kwargs):
        return self.path.read_text(*args, **kwargs)

    def open(self, mode="r", *args, **kwargs):
        if "a" in mode:
            self.append_attempts += 1
            if self.append_attempts <= self.fail_appends:
                raise PermissionError(5, "Access is denied")
        return self.path.open(mode, *args, **kwargs)


class ChatLogAppendV19Tests(unittest.TestCase):
    def setUp(self):
        self.original_lines_signature = chat_storage._CHAT_LINES_CACHE_SIGNATURE
        self.original_lines_payload = chat_storage._CHAT_LINES_CACHE_PAYLOAD
        chat_storage._CHAT_LINES_CACHE_SIGNATURE = None
        chat_storage._CHAT_LINES_CACHE_PAYLOAD = None

    def tearDown(self):
        chat_storage._CHAT_LINES_CACHE_SIGNATURE = self.original_lines_signature
        chat_storage._CHAT_LINES_CACHE_PAYLOAD = self.original_lines_payload

    def test_log_chat_appends_user_and_reply_lines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "chat_log.txt"
            with patch.object(chat_storage, "CHAT_LOG_FILE", log_path):
                chat_storage.log_chat("hayouna6", "hello", "reply", platform="twitch")

            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn("PLATFORM=twitch USER=hayouna6 MESSAGE=hello", lines[0])
            self.assertIn("PLATFORM=twitch BOT=reply", lines[1])

    def test_append_chat_log_lines_retries_transient_permission_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "chat_log.txt"
            flaky_path = FlakyAppendPath(log_path, fail_appends=2)

            with patch.object(chat_storage, "CHAT_LOG_FILE", flaky_path), patch(
                "core.chat_storage.write_diagnostics_line"
            ):
                chat_storage._append_chat_log_lines(["one\n", "two\n"], retry_delays=(0.001, 0.001, 0.001))

            self.assertGreaterEqual(flaky_path.append_attempts, 3)
            self.assertEqual(log_path.read_text(encoding="utf-8").splitlines(), ["one", "two"])

    def test_log_chat_invalidates_recent_line_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "chat_log.txt"
            log_path.write_text(
                "[2026-06-19 10:00:00] PLATFORM=twitch USER=hayouna6 MESSAGE=first\n",
                encoding="utf-8",
            )

            with patch.object(chat_storage, "CHAT_LOG_FILE", log_path):
                self.assertEqual(chat_storage.get_recent_user_only_messages("hayouna6"), ["first"])
                self.assertIsNotNone(chat_storage._CHAT_LINES_CACHE_PAYLOAD)
                chat_storage.log_chat("hayouna6", "second", platform="twitch")
                self.assertIsNone(chat_storage._CHAT_LINES_CACHE_PAYLOAD)
                self.assertEqual(chat_storage.get_recent_user_only_messages("hayouna6"), ["first", "second"])


if __name__ == "__main__":
    unittest.main()

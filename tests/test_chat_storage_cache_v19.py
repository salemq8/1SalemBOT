import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core import chat_storage


class FakeChatLogPath:
    def __init__(self, content=""):
        self.content = content
        self.read_count = 0
        self.mtime_ns = 1

    def exists(self):
        return True

    def stat(self):
        return SimpleNamespace(st_size=len(self.content.encode("utf-8")), st_mtime_ns=self.mtime_ns, st_mtime=0)

    def read_text(self, encoding="utf-8"):
        self.read_count += 1
        return self.content

    def replace_content(self, content):
        self.content = content
        self.mtime_ns += 1


class ChatStorageCacheV19Tests(unittest.TestCase):
    def setUp(self):
        self.original_lines_signature = chat_storage._CHAT_LINES_CACHE_SIGNATURE
        self.original_lines_payload = chat_storage._CHAT_LINES_CACHE_PAYLOAD
        chat_storage._CHAT_LINES_CACHE_SIGNATURE = None
        chat_storage._CHAT_LINES_CACHE_PAYLOAD = None

    def tearDown(self):
        chat_storage._CHAT_LINES_CACHE_SIGNATURE = self.original_lines_signature
        chat_storage._CHAT_LINES_CACHE_PAYLOAD = self.original_lines_payload

    def test_recent_user_message_lookup_reuses_unchanged_chat_log_cache(self):
        fake_log = FakeChatLogPath(
            "[2026-06-19 10:00:00] PLATFORM=twitch USER=hayouna6 MESSAGE=first\n"
            "[2026-06-19 10:00:01] PLATFORM=twitch USER=salem MESSAGE=other\n"
        )

        with patch.object(chat_storage, "CHAT_LOG_FILE", fake_log):
            self.assertEqual(chat_storage.get_recent_user_only_messages("hayouna6"), ["first"])
            self.assertEqual(chat_storage.get_recent_user_only_messages("hayouna6"), ["first"])

        self.assertEqual(fake_log.read_count, 1)

    def test_recent_user_message_lookup_rereads_when_chat_log_signature_changes(self):
        fake_log = FakeChatLogPath(
            "[2026-06-19 10:00:00] PLATFORM=twitch USER=hayouna6 MESSAGE=first\n"
        )

        with patch.object(chat_storage, "CHAT_LOG_FILE", fake_log):
            self.assertEqual(chat_storage.get_recent_user_only_messages("hayouna6"), ["first"])
            fake_log.replace_content(
                "[2026-06-19 10:00:00] PLATFORM=twitch USER=hayouna6 MESSAGE=first\n"
                "[2026-06-19 10:00:02] PLATFORM=twitch USER=hayouna6 MESSAGE=second\n"
            )
            self.assertEqual(chat_storage.get_recent_user_only_messages("hayouna6"), ["first", "second"])

        self.assertEqual(fake_log.read_count, 2)


if __name__ == "__main__":
    unittest.main()

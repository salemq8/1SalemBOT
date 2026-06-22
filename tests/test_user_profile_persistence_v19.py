import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import chat_storage
from core.app_state import load_json, save_json


class UserProfilePersistenceV19Tests(unittest.TestCase):
    def test_bot_snapshot_preserves_manual_viewer_fields_from_disk(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            users_path = Path(temp_dir) / "users.json"
            save_json(
                users_path,
                {
                    "hayouna6": {
                        "messages": 5,
                        "last_seen": "2026-06-19 10:00:00",
                        "last_message": "old",
                        "manual_role": "VIP",
                        "muted": True,
                    }
                },
            )

            with patch.object(chat_storage, "USERS_FILE", users_path):
                chat_storage.save_user_profiles(
                    {
                        "hayouna6": {
                            "messages": 6,
                            "last_seen": "2026-06-19 10:01:00",
                            "last_message": "new chat",
                            "manual_role": "",
                            "muted": False,
                        }
                    }
                )

            saved = load_json(users_path, {})
            self.assertEqual(saved["hayouna6"]["messages"], 6)
            self.assertEqual(saved["hayouna6"]["last_message"], "new chat")
            self.assertEqual(saved["hayouna6"]["manual_role"], "VIP")
            self.assertTrue(saved["hayouna6"]["muted"])

    def test_stale_snapshot_does_not_lower_message_count_or_last_seen(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            users_path = Path(temp_dir) / "users.json"
            save_json(
                users_path,
                {
                    "viewer": {
                        "messages": 10,
                        "last_seen": "2026-06-19 10:05:00",
                        "last_message": "latest",
                        "behavior": "good",
                        "notes": "latest notes",
                    }
                },
            )

            with patch.object(chat_storage, "USERS_FILE", users_path):
                chat_storage.save_user_profiles(
                    {
                        "viewer": {
                            "messages": 8,
                            "last_seen": "2026-06-19 10:00:00",
                            "last_message": "stale",
                            "behavior": "neutral",
                            "notes": "old notes",
                        }
                    }
                )

            saved = load_json(users_path, {})
            self.assertEqual(saved["viewer"]["messages"], 10)
            self.assertEqual(saved["viewer"]["last_seen"], "2026-06-19 10:05:00")
            self.assertEqual(saved["viewer"]["last_message"], "latest")
            self.assertEqual(saved["viewer"]["notes"], "latest notes")

    def test_viewer_profile_patch_can_clear_manual_role(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            users_path = Path(temp_dir) / "users.json"
            save_json(
                users_path,
                {
                    "hayouna6": {
                        "messages": 3,
                        "last_seen": "2026-06-19 10:00:00",
                        "manual_role": "VIP",
                        "muted": False,
                    }
                },
            )

            with patch.object(chat_storage, "USERS_FILE", users_path):
                _changed, profile = chat_storage.save_user_profile_changes(
                    "hayouna6",
                    {"manual_role": "", "muted": True},
                    current_profiles={"hayouna6": {"messages": 1, "manual_role": "VIP"}},
                )

            saved = load_json(users_path, {})
            self.assertEqual(profile["manual_role"], "")
            self.assertEqual(saved["hayouna6"]["manual_role"], "")
            self.assertTrue(saved["hayouna6"]["muted"])
            self.assertEqual(saved["hayouna6"]["messages"], 3)


if __name__ == "__main__":
    unittest.main()

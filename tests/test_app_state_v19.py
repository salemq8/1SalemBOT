import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path

from core.app_state import load_json, save_json


class AppStateIoTests(unittest.TestCase):
    def test_save_json_writes_atomically_and_skips_unchanged_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"

            self.assertTrue(save_json(path, {"theme": "blue"}))
            self.assertEqual(load_json(path, {}), {"theme": "blue"})
            self.assertFalse(save_json(path, {"theme": "blue"}))

    def test_save_json_retries_permission_error_and_keeps_valid_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "users.json"
            self.assertTrue(save_json(path, {"messages": 1}))

            import os

            real_replace = os.replace
            attempts = {"count": 0}

            def flaky_replace(source, target):
                attempts["count"] += 1
                if attempts["count"] <= 2:
                    raise PermissionError(5, "Access is denied")
                return real_replace(source, target)

            with patch("core.json_store.os.replace", side_effect=flaky_replace):
                self.assertTrue(save_json(path, {"messages": 2}))

            self.assertGreaterEqual(attempts["count"], 3)
            self.assertEqual(load_json(path, {}), {"messages": 2})

    def test_save_json_failure_does_not_corrupt_existing_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "dashboard_state.json"
            self.assertTrue(save_json(path, {"messages_today": 5}))

            with patch("core.json_store.os.replace", side_effect=PermissionError(5, "Access is denied")):
                with self.assertRaises(PermissionError):
                    save_json(path, {"messages_today": 6},)

            self.assertEqual(load_json(path, {}), {"messages_today": 5})
            self.assertTrue((Path(temp_dir) / "dashboard_state.json.last-good.bak").exists())

    def test_save_json_unchanged_payload_does_not_replace_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            self.assertTrue(save_json(path, {"theme": "blue"}))

            with patch("core.json_store.os.replace") as replace_mock:
                self.assertFalse(save_json(path, {"theme": "blue"}))

            replace_mock.assert_not_called()

    def test_concurrent_writes_to_same_json_file_remain_valid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "users.json"
            errors = []

            def writer(index):
                try:
                    save_json(path, {"writer": index, "messages": index + 1})
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=writer, args=(index,)) for index in range(12)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])
            loaded = load_json(path, {})
            self.assertIn("writer", loaded)
            self.assertIn("messages", loaded)

    def test_load_json_backs_up_corrupted_file_and_returns_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "users.json"
            path.write_text("{broken json", encoding="utf-8")

            loaded = load_json(path, {"safe": True})

            self.assertEqual(loaded, {"safe": True})
            backups = list(Path(temp_dir).glob("users.json.corrupt-*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "{broken json")


if __name__ == "__main__":
    unittest.main()

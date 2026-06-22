import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from core.secure_storage import atomic_write_bytes


class SecureStorageWriteV19Tests(unittest.TestCase):
    def test_atomic_write_bytes_retries_permission_error_and_keeps_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "token.dpapi"
            self.assertTrue(atomic_write_bytes(path, b"old-secret"))

            real_replace = os.replace
            attempts = {"count": 0}

            def flaky_replace(source, target):
                attempts["count"] += 1
                if attempts["count"] <= 2:
                    raise PermissionError(5, "Access is denied")
                return real_replace(source, target)

            with patch("core.secure_storage.os.replace", side_effect=flaky_replace):
                self.assertTrue(atomic_write_bytes(path, b"new-secret"))

            self.assertGreaterEqual(attempts["count"], 3)
            self.assertEqual(path.read_bytes(), b"new-secret")

    def test_atomic_write_bytes_failure_does_not_corrupt_existing_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "token.dpapi"
            self.assertTrue(atomic_write_bytes(path, b"valid-secret"))

            with patch("core.secure_storage.os.replace", side_effect=PermissionError(5, "Access is denied")):
                with self.assertRaises(PermissionError):
                    atomic_write_bytes(path, b"lost-secret", retry_delays=(0.001, 0.001))

            self.assertEqual(path.read_bytes(), b"valid-secret")
            self.assertEqual((Path(temp_dir) / "token.dpapi.last-good.bak").read_bytes(), b"valid-secret")

    def test_atomic_write_bytes_unchanged_payload_does_not_replace_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "token.dpapi"
            self.assertTrue(atomic_write_bytes(path, b"same-secret"))

            with patch("core.secure_storage.os.replace") as replace_mock:
                self.assertFalse(atomic_write_bytes(path, b"same-secret"))

            replace_mock.assert_not_called()

    def test_concurrent_secure_writes_to_same_file_remain_valid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "token.dpapi"
            errors = []

            def writer(index):
                try:
                    atomic_write_bytes(path, f"secret-{index}".encode("utf-8"))
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=writer, args=(index,)) for index in range(12)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])
            self.assertTrue(path.read_bytes().startswith(b"secret-"))


if __name__ == "__main__":
    unittest.main()

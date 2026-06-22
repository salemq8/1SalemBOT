import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import telemetry


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("No JSON")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error


class FakeRequester:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if not self.responses:
            raise AssertionError("No fake response queued")
        return self.responses.pop(0)


class TelemetryV18Tests(unittest.TestCase):
    def test_install_id_is_generated_once_and_persisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_file = Path(temp_dir) / "telemetry.json"

            first = telemetry.load_or_create_install_id(storage_file)
            second = telemetry.load_or_create_install_id(storage_file)

            self.assertEqual(first, second)
            self.assertTrue(telemetry.valid_install_id(first))
            saved = json.loads(storage_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["install_id"], first)

    def test_payload_contains_only_allowed_usage_fields(self):
        settings = {
            "channel_login": "1SalemQ8",
            "bot_login": "1SalemGPT",
            "openai_api_key": "sk-secret",
            "access_token": "twitch-secret",
            "password": "private",
            "chat_log": "hello chat",
        }

        with patch("core.telemetry.platform.platform", return_value="Windows-Test"):
            payload = telemetry.build_installation_payload(
                settings,
                "11111111-1111-4111-8111-111111111111",
                include_first_seen=True,
                timestamp="2026-06-15T00:00:00Z",
            )

        self.assertEqual(
            set(payload),
            {"install_id", "channel_name", "bot_name", "app_version", "os_version", "first_seen", "last_seen"},
        )
        self.assertEqual(payload["channel_name"], "1SalemQ8")
        self.assertEqual(payload["bot_name"], "1SalemGPT")
        serialized = json.dumps(payload)
        self.assertNotIn("sk-secret", serialized)
        self.assertNotIn("twitch-secret", serialized)
        self.assertNotIn("private", serialized)
        self.assertNotIn("hello chat", serialized)

    def test_existing_installation_uses_insert_ignore_then_update(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_file = Path(temp_dir) / "telemetry.json"
            log_file = Path(temp_dir) / "logs" / "telemetry.log"
            storage_file.write_text('{"install_id": "22222222-2222-4222-8222-222222222222"}', encoding="utf-8")
            requester = FakeRequester([FakeResponse(201, None), FakeResponse(204, None)])
            service = telemetry.SupabaseTelemetryService(storage_file=storage_file, log_file=log_file, request_func=requester)

            result = service.sync_installation({"channel_login": "channel", "bot_login": "bot"})

            self.assertTrue(result.ok)
            self.assertEqual(result.action, "upserted")
            self.assertEqual([call["method"] for call in requester.calls], ["POST", "PATCH"])
            self.assertIn("on_conflict=install_id", requester.calls[0]["url"])
            self.assertIn("resolution=ignore-duplicates", requester.calls[0]["headers"]["Prefer"])
            self.assertIn("first_seen", requester.calls[0]["json"])
            self.assertNotIn("first_seen", requester.calls[1]["json"])
            content = log_file.read_text(encoding="utf-8")
            self.assertIn("Telemetry sync requested", content)
            self.assertIn("Telemetry sync succeeded: upserted (insert=201, update=204)", content)
            self.assertNotIn("22222222-2222-4222-8222-222222222222", content)
            self.assertNotIn("channel_name: channel", content)
            self.assertNotIn("bot_name: bot", content)
            self.assertNotIn("Supabase URL present", content)
            self.assertNotIn("Insert request payload", content)
            self.assertNotIn("Telemetry exception stack trace", content)

    def test_developer_diagnostics_are_detailed_but_redacted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_file = Path(temp_dir) / "telemetry.json"
            log_file = Path(temp_dir) / "logs" / "telemetry.log"
            storage_file.write_text('{"install_id": "44444444-4444-4444-8444-444444444444"}', encoding="utf-8")
            requester = FakeRequester([FakeResponse(201, None, text='{"ok":true}'), FakeResponse(204, None)])
            service = telemetry.SupabaseTelemetryService(
                storage_file=storage_file,
                log_file=log_file,
                request_func=requester,
                developer_diagnostics=True,
            )

            result = service.sync_installation({"channel_login": "channel", "bot_login": "bot"})

            self.assertTrue(result.ok)
            content = log_file.read_text(encoding="utf-8")
            self.assertIn("Supabase URL present: yes", content)
            self.assertIn("Supabase key loaded: yes (masked)", content)
            self.assertIn("install_id loaded: <masked>...444444", content)
            self.assertIn("Insert request payload fields:", content)
            self.assertIn("Update request payload fields:", content)
            self.assertIn("Insert HTTP status code: 201", content)
            self.assertIn("Insert response body:", content)
            self.assertNotIn("44444444-4444-4444-8444-444444444444", content)
            self.assertNotIn("channel_name: channel", content)
            self.assertNotIn("bot_name: bot", content)

    def test_missing_installation_inserts_then_reuses_same_install_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_file = Path(temp_dir) / "telemetry.json"
            log_file = Path(temp_dir) / "logs" / "telemetry.log"
            storage_file.write_text('{"install_id": "33333333-3333-4333-8333-333333333333"}', encoding="utf-8")
            requester = FakeRequester([FakeResponse(201, None), FakeResponse(204, None)])
            service = telemetry.SupabaseTelemetryService(storage_file=storage_file, log_file=log_file, request_func=requester)

            result = service.sync_installation({"channel_login": "channel", "bot_login": "bot"})

            self.assertTrue(result.ok)
            self.assertEqual(result.action, "upserted")
            self.assertEqual([call["method"] for call in requester.calls], ["POST", "PATCH"])
            self.assertIn("first_seen", requester.calls[0]["json"])
            self.assertEqual(result.install_id, telemetry.load_or_create_install_id(storage_file))

    def test_failed_insert_recreates_telemetry_log_with_error_details(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_file = Path(temp_dir) / "telemetry.json"
            log_file = Path(temp_dir) / "logs" / "telemetry.log"
            requester = FakeRequester([FakeResponse(401, {"message": "permission denied"}, text='{"message":"permission denied"}')])
            service = telemetry.SupabaseTelemetryService(storage_file=storage_file, log_file=log_file, request_func=requester)

            result = service.sync_installation({"channel_login": "channel", "bot_login": "bot"})

            self.assertFalse(result.ok)
            self.assertTrue(log_file.exists())
            content = log_file.read_text(encoding="utf-8")
            self.assertIn("Telemetry sync requested", content)
            self.assertIn("Telemetry sync failed: category=http status=401", content)
            self.assertNotIn("Insert request payload", content)
            self.assertNotIn('{"message":"permission denied"}', content)
            self.assertNotIn("Telemetry exception stack trace", content)

    def test_telemetry_log_rotates_when_size_limit_is_reached(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "logs" / "telemetry.log"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_file.write_text("x" * 128, encoding="utf-8")

            telemetry.append_telemetry_log("after rotation", log_file=log_file, max_bytes=32)

            self.assertTrue(log_file.exists())
            self.assertTrue(log_file.with_name("telemetry.log.1").exists())
            self.assertIn("after rotation", log_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

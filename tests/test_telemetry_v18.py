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
            self.assertIn("Telemetry startup", content)
            self.assertIn("install_id loaded", content)
            self.assertIn("Supabase URL present: yes", content)
            self.assertIn("Supabase URL loaded", content)
            self.assertIn("Supabase key present: yes", content)
            self.assertIn("Supabase key loaded: yes (masked)", content)
            self.assertIn("channel_name: channel", content)
            self.assertIn("bot_name: bot", content)
            self.assertIn("app_version:", content)
            self.assertIn("os_version:", content)
            self.assertIn("Insert/update attempt", content)
            self.assertIn("Insert request payload", content)
            self.assertIn("Update request payload", content)
            self.assertIn("Insert HTTP status code: 201", content)
            self.assertIn("Insert response body", content)
            self.assertIn("Update HTTP status code: 204", content)

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
            self.assertIn("Telemetry startup", content)
            self.assertIn("install_id generated", content)
            self.assertIn("Supabase URL present: yes", content)
            self.assertIn("Supabase URL loaded", content)
            self.assertIn("Supabase key present: yes", content)
            self.assertIn("Supabase key loaded: yes (masked)", content)
            self.assertIn("Insert/update attempt", content)
            self.assertIn("Insert request payload", content)
            self.assertIn("Update request payload prepared", content)
            self.assertIn("Insert HTTP status code: 401", content)
            self.assertIn('Insert response body: {"message":"permission denied"}', content)
            self.assertIn("Telemetry exception stack trace", content)


if __name__ == "__main__":
    unittest.main()

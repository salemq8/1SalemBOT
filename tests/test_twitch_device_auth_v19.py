import os
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core import auth
from core.auth import BOT_AUTH_ROLE, CHANNEL_AUTH_ROLE
from core.secure_storage import load_encrypted_json, save_encrypted_json
from core.ui.themes import THEMES
from core.ui.twitch_device_dialog import TwitchDeviceAuthDialog


def qt_app():
    return QApplication.instance() or QApplication([])


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text
        self.ok = status_code < 400

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error


class FakePost:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self.responses:
            raise AssertionError("No response queued")
        return self.responses.pop(0)


def validation(login="botlogin", scopes=None):
    return {
        "client_id": auth.CLIENT_ID,
        "login": login,
        "user_id": "123",
        "scopes": scopes or auth.get_role_scopes(BOT_AUTH_ROLE),
        "expires_in": 3600,
    }


class TwitchDeviceAuthV19Tests(unittest.TestCase):
    def setUp(self):
        auth._auth_log_once_keys.clear()
        auth._auth_log_last_at.clear()
        auth._migration_attempted_roles.clear()

    @contextmanager
    def auth_file_patches(self, temp):
        token_files = {BOT_AUTH_ROLE: temp / "bot.json", CHANNEL_AUTH_ROLE: temp / "channel.json"}
        secure_files = {BOT_AUTH_ROLE: temp / "bot.dpapi", CHANNEL_AUTH_ROLE: temp / "channel.dpapi"}
        with (
            patch.dict(auth.TOKEN_FILES, token_files, clear=False),
            patch.dict(auth.SECURE_TOKEN_FILES, secure_files, clear=False),
            patch("core.auth.AUTH_STATE_FILE", temp / "auth_state.json"),
            patch("core.auth.LEGACY_APPDATA_BOT_TOKEN_FILE", temp / "legacy_appdata_bot.json"),
            patch("core.auth.LEGACY_APPDATA_CHANNEL_TOKEN_FILE", temp / "legacy_appdata_channel.json"),
            patch("core.auth.LEGACY_TOKEN_FILE", temp / "legacy_root_token.json"),
        ):
            yield

    def test_device_code_request_uses_existing_client_id_and_role_scopes(self):
        requester = FakePost(
            [
                FakeResponse(
                    200,
                    {
                        "device_code": "private-device-code",
                        "user_code": "ABCD-EFGH",
                        "verification_uri": "https://www.twitch.tv/activate?device-code=ABCD",
                        "expires_in": 1800,
                        "interval": 5,
                    },
                )
            ]
        )

        session = auth.start_device_code_authorization(BOT_AUTH_ROLE, request_func=requester)

        self.assertEqual(session["user_code"], "ABCD-EFGH")
        self.assertEqual(requester.calls[0]["url"], auth.DEVICE_CODE_URL)
        self.assertEqual(requester.calls[0]["data"]["client_id"], auth.CLIENT_ID)
        self.assertEqual(requester.calls[0]["data"]["scopes"], " ".join(auth.get_role_scopes(BOT_AUTH_ROLE)))

    def test_device_code_exchange_handles_pending_slow_down_and_success(self):
        pending = FakePost([FakeResponse(400, {"message": "authorization_pending"})])
        slow = FakePost([FakeResponse(400, {"message": "slow_down"})])
        success = FakePost([FakeResponse(200, {"access_token": "access123", "refresh_token": "refresh456", "expires_in": 3600})])

        self.assertEqual(auth.exchange_device_code("device", BOT_AUTH_ROLE, request_func=pending)["error"], "authorization_pending")
        self.assertEqual(auth.exchange_device_code("device", BOT_AUTH_ROLE, request_func=slow)["error"], "slow_down")
        token = auth.exchange_device_code("device", BOT_AUTH_ROLE, request_func=success)
        self.assertTrue(token["ok"])
        self.assertEqual(token["access_token"], "access123")

    def test_secure_storage_encrypts_token_payload(self):
        if os.name != "nt":
            self.skipTest("DPAPI secure storage is Windows-only")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "token.dpapi"
            save_encrypted_json(path, {"access_token": "plain-access", "refresh_token": "plain-refresh"})

            raw = path.read_bytes()
            self.assertNotIn(b"plain-access", raw)
            self.assertNotIn(b"plain-refresh", raw)
            self.assertEqual(load_encrypted_json(path)["access_token"], "plain-access")

    def test_bot_and_channel_tokens_save_to_separate_secure_files(self):
        if os.name != "nt":
            self.skipTest("DPAPI secure storage is Windows-only")
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            token_files = {
                BOT_AUTH_ROLE: temp / "bot.json",
                CHANNEL_AUTH_ROLE: temp / "channel.json",
            }
            secure_files = {
                BOT_AUTH_ROLE: temp / "bot.dpapi",
                CHANNEL_AUTH_ROLE: temp / "channel.dpapi",
            }
            with (
                patch.dict(auth.TOKEN_FILES, token_files, clear=False),
                patch.dict(auth.SECURE_TOKEN_FILES, secure_files, clear=False),
                patch("core.auth.validate_token", side_effect=[
                    validation("botlogin", auth.get_role_scopes(BOT_AUTH_ROLE)),
                    validation("channel", auth.get_role_scopes(CHANNEL_AUTH_ROLE)),
                ]),
                patch("core.auth.fetch_user_profile", side_effect=[
                    {"login": "botlogin", "display_name": "BotLogin", "profile_image_url": ""},
                    {"login": "channel", "display_name": "Channel", "profile_image_url": ""},
                ]),
            ):
                bot = auth.save_token_response({"access_token": "bot-access", "refresh_token": "bot-refresh", "expires_in": 3600}, BOT_AUTH_ROLE)
                channel = auth.save_token_response({"access_token": "channel-access", "refresh_token": "channel-refresh", "expires_in": 3600}, CHANNEL_AUTH_ROLE)

                self.assertEqual(bot["access_token"], "bot-access")
                self.assertEqual(channel["access_token"], "channel-access")
                self.assertNotIn("bot-access", token_files[BOT_AUTH_ROLE].read_text(encoding="utf-8"))
                self.assertNotIn("channel-refresh", token_files[CHANNEL_AUTH_ROLE].read_text(encoding="utf-8"))
                self.assertNotIn(b"bot-access", secure_files[BOT_AUTH_ROLE].read_bytes())
                self.assertNotIn(b"channel-refresh", secure_files[CHANNEL_AUTH_ROLE].read_bytes())

    def test_refresh_role_token_is_single_flight_and_rotates_pair(self):
        if os.name != "nt":
            self.skipTest("DPAPI secure storage is Windows-only")
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            token_files = {BOT_AUTH_ROLE: temp / "bot.json", CHANNEL_AUTH_ROLE: temp / "channel.json"}
            secure_files = {BOT_AUTH_ROLE: temp / "bot.dpapi", CHANNEL_AUTH_ROLE: temp / "channel.dpapi"}
            calls = []
            release = threading.Event()

            def fake_post(_url, **_kwargs):
                calls.append(_kwargs["data"]["refresh_token"])
                release.wait(1.0)
                return FakeResponse(200, {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600})

            with (
                patch.dict(auth.TOKEN_FILES, token_files, clear=False),
                patch.dict(auth.SECURE_TOKEN_FILES, secure_files, clear=False),
                patch("core.auth.validate_token", return_value=validation("botlogin", auth.get_role_scopes(BOT_AUTH_ROLE))),
                patch("core.auth.fetch_user_profile", return_value={"login": "botlogin", "display_name": "BotLogin", "profile_image_url": ""}),
            ):
                auth.save_token_response({"access_token": "old-access", "refresh_token": "old-refresh", "expires_in": 3600}, BOT_AUTH_ROLE)
                results = []
                errors = []
                threads = [
                    threading.Thread(target=lambda: results.append(auth.refresh_role_token(BOT_AUTH_ROLE, request_func=fake_post))),
                    threading.Thread(target=lambda: results.append(auth.refresh_role_token(BOT_AUTH_ROLE, request_func=fake_post))),
                ]
                for thread in threads:
                    thread.start()
                time.sleep(0.05)
                release.set()
                for thread in threads:
                    thread.join(2.0)

                self.assertEqual(errors, [])
                self.assertEqual(calls, ["old-refresh"])
                self.assertEqual(len(results), 2)
                self.assertEqual(auth.load_token_details(BOT_AUTH_ROLE)["refresh_token"], "new-refresh")

    def test_device_dialog_shows_role_and_user_code_ltr(self):
        app = qt_app()
        dialog = TwitchDeviceAuthDialog(role=BOT_AUTH_ROLE, theme=THEMES["blue"], localize=lambda text, **_: text)
        with patch("core.ui.twitch_device_dialog.QDesktopServices.openUrl", return_value=True):
            dialog.update_state(
                {
                    "state": "waiting",
                    "message": "Waiting for Twitch authorization...",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://www.twitch.tv/activate?device-code=ABCD",
                    "expires_at": time.time() + 60,
                }
            )
        app.processEvents()

        self.assertIn("Bot Account", dialog.windowTitle())
        self.assertEqual(dialog.code_label.text(), "ABCD-EFGH")
        self.assertEqual(dialog.code_label.layoutDirection(), Qt.LeftToRight)
        self.assertTrue(dialog.copy_button.isEnabled())
        dialog.close()

    def test_disconnected_role_skips_plaintext_migration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            with self.auth_file_patches(temp):
                auth.TOKEN_FILES[CHANNEL_AUTH_ROLE].write_text(
                    '{"access_token":"stale-channel","refresh_token":"stale-refresh","role":"channel"}',
                    encoding="utf-8",
                )
                auth.mark_role_disconnected(CHANNEL_AUTH_ROLE)
                with patch("core.auth.validate_token", side_effect=AssertionError("migration should be skipped")):
                    details = auth.load_token_details(CHANNEL_AUTH_ROLE)

                self.assertEqual(details["access_token"], "")
                self.assertEqual(details["auth_state"], "disconnected")

    def test_failed_plaintext_migration_is_not_retried_or_exposed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            with self.auth_file_patches(temp):
                auth.TOKEN_FILES[CHANNEL_AUTH_ROLE].write_text(
                    '{"access_token":"bad-channel","refresh_token":"bad-refresh","role":"channel"}',
                    encoding="utf-8",
                )
                with (
                    patch("core.auth.validate_token", side_effect=ValueError("Missing required Twitch scopes")),
                    patch("core.auth.write_diagnostics_line") as diagnostics,
                ):
                    first = auth.load_token_details(CHANNEL_AUTH_ROLE)
                    second = auth.load_token_details(CHANNEL_AUTH_ROLE)

                self.assertEqual(first["access_token"], "")
                self.assertEqual(second["access_token"], "")
                self.assertEqual(auth.get_role_auth_runtime_state(CHANNEL_AUTH_ROLE)["state"], "migration_failed")
                self.assertEqual(auth.get_role_auth_runtime_state(CHANNEL_AUTH_ROLE)["migration_failed_reason"], "missing_scopes")
                migration_logs = [
                    call.args[0]
                    for call in diagnostics.call_args_list
                    if "migration failed once" in call.args[0]
                ]
                self.assertEqual(len(migration_logs), 1)

    def test_secure_token_prevents_legacy_migration_attempt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            with self.auth_file_patches(temp):
                auth.TOKEN_FILES[CHANNEL_AUTH_ROLE].write_text(
                    '{"login":"channel","role":"channel","secure_storage":"windows_dpapi_current_user"}',
                    encoding="utf-8",
                )
                with (
                    patch("core.auth._load_secure_token_payload", return_value={"role": CHANNEL_AUTH_ROLE, "access_token": "secure-access", "refresh_token": "secure-refresh"}),
                    patch("core.auth.validate_token", side_effect=AssertionError("legacy migration should not run")),
                ):
                    details = auth.load_token_details(CHANNEL_AUTH_ROLE)

                self.assertEqual(details["access_token"], "secure-access")

    def test_channel_logout_preserves_bot_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            with self.auth_file_patches(temp):
                auth.TOKEN_FILES[BOT_AUTH_ROLE].write_text('{"login":"bot","role":"bot"}', encoding="utf-8")
                auth.TOKEN_FILES[CHANNEL_AUTH_ROLE].write_text('{"login":"channel","role":"channel"}', encoding="utf-8")
                auth.SECURE_TOKEN_FILES[BOT_AUTH_ROLE].write_text("bot-secret", encoding="utf-8")
                auth.SECURE_TOKEN_FILES[CHANNEL_AUTH_ROLE].write_text("channel-secret", encoding="utf-8")

                auth.clear_token(CHANNEL_AUTH_ROLE)

                self.assertTrue(auth.TOKEN_FILES[BOT_AUTH_ROLE].exists())
                self.assertTrue(auth.SECURE_TOKEN_FILES[BOT_AUTH_ROLE].exists())
                self.assertFalse(auth.TOKEN_FILES[CHANNEL_AUTH_ROLE].exists())
                self.assertFalse(auth.SECURE_TOKEN_FILES[CHANNEL_AUTH_ROLE].exists())

    def test_bot_logout_preserves_channel_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            with self.auth_file_patches(temp):
                auth.TOKEN_FILES[BOT_AUTH_ROLE].write_text('{"login":"bot","role":"bot"}', encoding="utf-8")
                auth.TOKEN_FILES[CHANNEL_AUTH_ROLE].write_text('{"login":"channel","role":"channel"}', encoding="utf-8")
                auth.SECURE_TOKEN_FILES[BOT_AUTH_ROLE].write_text("bot-secret", encoding="utf-8")
                auth.SECURE_TOKEN_FILES[CHANNEL_AUTH_ROLE].write_text("channel-secret", encoding="utf-8")

                auth.clear_token(BOT_AUTH_ROLE)

                self.assertFalse(auth.TOKEN_FILES[BOT_AUTH_ROLE].exists())
                self.assertFalse(auth.SECURE_TOKEN_FILES[BOT_AUTH_ROLE].exists())
                self.assertTrue(auth.TOKEN_FILES[CHANNEL_AUTH_ROLE].exists())
                self.assertTrue(auth.SECURE_TOKEN_FILES[CHANNEL_AUTH_ROLE].exists())

    def test_device_code_reconnect_clears_migration_failed_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            with self.auth_file_patches(temp):
                auth.mark_role_migration_failed(CHANNEL_AUTH_ROLE, "validation_failed")
                auth.begin_role_auth_flow(CHANNEL_AUTH_ROLE)
                state = auth.get_role_auth_runtime_state(CHANNEL_AUTH_ROLE)

                self.assertEqual(state["state"], "waiting_for_device_code")
                self.assertFalse(state.get("explicitly_disconnected"))
                self.assertNotIn("migration_failed_at", state)

    def test_stale_token_save_is_blocked_after_disconnect_during_profile_lookup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            with self.auth_file_patches(temp):
                auth.begin_role_auth_flow(CHANNEL_AUTH_ROLE)

                def disconnect_during_profile(*_args, **_kwargs):
                    auth.mark_role_disconnected(CHANNEL_AUTH_ROLE)
                    return {"login": "channel", "display_name": "Channel", "profile_image_url": ""}

                with (
                    patch("core.auth.validate_token", return_value=validation("channel", auth.get_role_scopes(CHANNEL_AUTH_ROLE))),
                    patch("core.auth.fetch_user_profile", side_effect=disconnect_during_profile),
                    patch("core.auth.save_encrypted_json") as secure_save,
                    patch("core.auth.write_diagnostics_line"),
                ):
                    with self.assertRaisesRegex(ValueError, "Role disconnected"):
                        auth.save_token_response(
                            {"access_token": "stale-access", "refresh_token": "stale-refresh", "expires_in": 3600},
                            CHANNEL_AUTH_ROLE,
                        )

                self.assertFalse(auth.TOKEN_FILES[CHANNEL_AUTH_ROLE].exists())
                self.assertFalse(auth.SECURE_TOKEN_FILES[CHANNEL_AUTH_ROLE].exists())
                secure_save.assert_not_called()

    def test_disconnect_after_secure_write_rolls_back_secret_and_skips_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            with self.auth_file_patches(temp):
                auth.begin_role_auth_flow(BOT_AUTH_ROLE)

                def save_then_disconnect(path, _payload):
                    Path(path).write_text("temporary-secure-token", encoding="utf-8")
                    auth.mark_role_disconnected(BOT_AUTH_ROLE)
                    return True

                with (
                    patch("core.auth.validate_token", return_value=validation("botlogin", auth.get_role_scopes(BOT_AUTH_ROLE))),
                    patch("core.auth.fetch_user_profile", return_value={"login": "botlogin", "display_name": "Bot", "profile_image_url": ""}),
                    patch("core.auth.save_encrypted_json", side_effect=save_then_disconnect),
                    patch("core.auth._load_secure_token_payload", return_value={"access_token": "stale-access", "refresh_token": "stale-refresh"}),
                    patch("core.auth.write_diagnostics_line"),
                ):
                    with self.assertRaisesRegex(ValueError, "Role disconnected"):
                        auth.save_token_response(
                            {"access_token": "stale-access", "refresh_token": "stale-refresh", "expires_in": 3600},
                            BOT_AUTH_ROLE,
                        )

                self.assertFalse(auth.TOKEN_FILES[BOT_AUTH_ROLE].exists())
                self.assertFalse(auth.SECURE_TOKEN_FILES[BOT_AUTH_ROLE].exists())

    def test_clear_token_retries_transient_file_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            with self.auth_file_patches(temp):
                auth.TOKEN_FILES[BOT_AUTH_ROLE].write_text('{"login":"bot","role":"bot"}', encoding="utf-8")
                auth.SECURE_TOKEN_FILES[BOT_AUTH_ROLE].write_text("bot-secret", encoding="utf-8")
                token_target = auth.TOKEN_FILES[BOT_AUTH_ROLE].resolve()
                attempts = {"token": 0}
                real_unlink = Path.unlink

                def flaky_unlink(self, *args, **kwargs):
                    if Path(self).resolve() == token_target and attempts["token"] < 2:
                        attempts["token"] += 1
                        raise PermissionError(5, "Access is denied")
                    return real_unlink(self, *args, **kwargs)

                with (
                    patch.object(auth, "TOKEN_DELETE_RETRY_DELAYS", (0.001, 0.001, 0.001)),
                    patch("core.auth.Path.unlink", new=flaky_unlink),
                    patch("core.auth.write_diagnostics_line"),
                ):
                    auth.clear_token(BOT_AUTH_ROLE)

                self.assertEqual(attempts["token"], 2)
                self.assertFalse(auth.TOKEN_FILES[BOT_AUTH_ROLE].exists())
                self.assertFalse(auth.SECURE_TOKEN_FILES[BOT_AUTH_ROLE].exists())


if __name__ == "__main__":
    unittest.main()

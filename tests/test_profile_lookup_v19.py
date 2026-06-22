import os
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from core.auth import BOT_AUTH_ROLE, CHANNEL_AUTH_ROLE
from core.tasks import BackgroundTaskManager
from core.ui import twitch_mixin
from core.ui.twitch_mixin import DashboardTwitchMixin
from core.ui.widgets import Bridge


def qt_app():
    return QApplication.instance() or QApplication([])


def process_until(predicate, timeout=2.0):
    app = qt_app()
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return predicate()


class ProfileLookupHarness(DashboardTwitchMixin):
    def __init__(self):
        self.bridge = Bridge()
        self.logs = []
        self.accounts = []
        self.bridge.log_signal.connect(self.logs.append)
        self.bridge.account_signal.connect(self.accounts.append)
        self.task_manager = BackgroundTaskManager()
        self.account_profile_request_ids = {BOT_AUTH_ROLE: 0, CHANNEL_AUTH_ROLE: 0}
        self.account_profile_lookup_signatures = {BOT_AUTH_ROLE: "", CHANNEL_AUTH_ROLE: ""}
        self.account_profile_failure_state = {
            BOT_AUTH_ROLE: {"error": "", "next_retry_at": 0.0},
            CHANNEL_AUTH_ROLE: {"error": "", "next_retry_at": 0.0},
        }
        self._closing = False

    def current_bot_login(self):
        return "1salemgpt"

    def current_channel_login(self):
        return "1salemq8"

    def get_sidebar_account_card(self, _role):
        return None

    def build_avatar_pixmap(self, *args, **kwargs):
        return QPixmap()


def token_details(login="1salemgpt"):
    return {
        "access_token": "token",
        "login": login,
        "display_name": "",
        "profile_image_url": "",
    }


class ProfileLookupV19Tests(unittest.TestCase):
    def setUp(self):
        qt_app()

    def test_profile_lookup_runtime_path_has_canonical_function(self):
        self.assertTrue(callable(twitch_mixin.get_user_by_login))

    def test_profile_lookup_succeeds_without_name_error(self):
        harness = ProfileLookupHarness()
        calls = []

        def fake_get_user(_client_id, token, login):
            calls.append((token, login))
            return {"display_name": "1SalemGPT", "login": login, "profile_image_url": ""}

        with (
            patch("core.ui.twitch_mixin.load_token_details", return_value=token_details("1salemgpt")),
            patch("core.ui.twitch_mixin.get_user_by_login", side_effect=fake_get_user),
        ):
            harness._refresh_sidebar_account(BOT_AUTH_ROLE)
            self.assertTrue(process_until(lambda: bool(harness.accounts)))

        self.assertEqual(calls, [("token", "1salemgpt")])
        self.assertEqual(harness.accounts[-1]["display_name"], "1SalemGPT")
        self.assertFalse(any("get_user_by_login" in line and "not defined" in line for line in harness.logs))

    def test_duplicate_profile_lookup_task_is_not_started_for_same_role(self):
        harness = ProfileLookupHarness()
        started = threading.Event()
        release = threading.Event()
        calls = []

        def fake_get_user(_client_id, _token, login):
            calls.append(login)
            started.set()
            release.wait(1.0)
            return {"display_name": login, "login": login, "profile_image_url": ""}

        with (
            patch("core.ui.twitch_mixin.load_token_details", return_value=token_details("1salemgpt")),
            patch("core.ui.twitch_mixin.get_user_by_login", side_effect=fake_get_user),
        ):
            harness._refresh_sidebar_account(BOT_AUTH_ROLE)
            self.assertTrue(process_until(started.is_set))
            harness._refresh_sidebar_account(BOT_AUTH_ROLE)
            self.assertEqual(calls, ["1salemgpt"])
            release.set()
            self.assertTrue(process_until(lambda: bool(harness.accounts)))

        self.assertEqual(calls, ["1salemgpt"])

    def test_profile_lookup_failure_is_cooled_down_and_manual_refresh_bypasses(self):
        harness = ProfileLookupHarness()
        calls = []

        def fake_get_user(_client_id, _token, login):
            calls.append(login)
            raise RuntimeError("temporary lookup failure")

        with (
            patch("core.ui.twitch_mixin.load_token_details", return_value=token_details("1salemq8")),
            patch("core.ui.twitch_mixin.get_user_by_login", side_effect=fake_get_user),
        ):
            harness._refresh_sidebar_account(CHANNEL_AUTH_ROLE)
            self.assertTrue(process_until(lambda: bool(harness.logs)))
            harness._refresh_sidebar_account(CHANNEL_AUTH_ROLE)
            time.sleep(0.05)
            qt_app().processEvents()
            self.assertEqual(calls, ["1salemq8"])
            harness._refresh_sidebar_account(CHANNEL_AUTH_ROLE, force=True)
            self.assertTrue(process_until(lambda: len(calls) == 2))

        failure_logs = [line for line in harness.logs if "profile lookup failed" in line]
        self.assertEqual(len(failure_logs), 1)


if __name__ == "__main__":
    unittest.main()

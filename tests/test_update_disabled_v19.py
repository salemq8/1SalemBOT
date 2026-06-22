import unittest
from unittest.mock import patch

from core.ui.window import DashboardApp
from core.update_manager import UpdateManager


class FakeButton:
    def __init__(self):
        self.enabled = None
        self.tooltip = ""

    def setEnabled(self, value):
        self.enabled = bool(value)

    def setToolTip(self, value):
        self.tooltip = str(value or "")


class UpdateDisabledHarness:
    check_for_updates = DashboardApp.check_for_updates
    sync_update_controls = DashboardApp.sync_update_controls

    def __init__(self):
        self.settings = {"updates": {"enabled": False, "auto_update_enabled": False}}
        self.update_check_inflight = False
        self.update_download_inflight = False
        self.update_install_inflight = False
        self.installing_update = False
        self.update_manager = None
        self.update_config = None
        self.check_updates_button = FakeButton()
        self.cancel_update_button = FakeButton()
        self.auto_update_checkbox = FakeButton()
        self.statuses = []
        self.logs = []

    def localize(self, text):
        return str(text)

    def set_update_status(self, text, progress=None):
        self.statuses.append((text, progress))

    def append_log(self, text):
        self.logs.append(text)


class UpdateDisabledV19Tests(unittest.TestCase):
    def test_disabled_update_check_does_not_start_network_task(self):
        harness = UpdateDisabledHarness()

        with patch.object(UpdateManager, "check_for_updates", side_effect=AssertionError("network should not start")):
            harness.check_for_updates(auto=False)

        self.assertFalse(harness.update_check_inflight)
        self.assertEqual(harness.statuses[-1][0], "Update checks are disabled")
        self.assertIn("[Updates] Update checks are disabled", harness.logs)
        self.assertFalse(harness.check_updates_button.enabled)
        self.assertEqual(harness.check_updates_button.tooltip, "Update checks are disabled")


if __name__ == "__main__":
    unittest.main()

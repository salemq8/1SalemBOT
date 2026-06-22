import unittest

from core.update_manager import UpdateAsset, UpdateConfig, UpdateError, UpdateManager, UpdateRelease, normalize_update_channel


class UpdateManagerChannelTests(unittest.TestCase):
    def test_stable_channel_rejects_prerelease(self):
        manager = UpdateManager(UpdateConfig(current_version="1.8", release_channel="stable"))
        release = UpdateRelease(version="1.9", prerelease=True, channel="preview")

        self.assertFalse(manager.release_is_applicable(release))

    def test_preview_channel_accepts_prerelease(self):
        manager = UpdateManager(UpdateConfig(current_version="1.9", release_channel="preview"))
        release = UpdateRelease(version="2.0", prerelease=True, channel="preview")

        self.assertTrue(manager.release_is_applicable(release))

    def test_beta_alias_normalizes_to_preview(self):
        self.assertEqual(normalize_update_channel("beta"), "preview")

    def test_installer_download_requires_sha256(self):
        manager = UpdateManager(UpdateConfig(current_version="1.8", release_channel="stable"))
        asset = UpdateAsset(name="1SalemBOT_Setup.exe", download_url="https://example.invalid/setup.exe")

        with self.assertRaises(UpdateError):
            manager.download_installer(asset)


if __name__ == "__main__":
    unittest.main()

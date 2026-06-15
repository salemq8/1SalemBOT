import unittest
from pathlib import Path

from core import version


class VersionChannelTests(unittest.TestCase):
    def test_beta_label_and_artifact_tags(self):
        self.assertEqual(version.version_label("1.8", "beta"), "1.8 Beta")
        self.assertEqual(version.artifact_version_tag("1.8", "beta"), "1.8_Beta")
        self.assertEqual(version.source_version_tag("1.8", "beta"), "1.8-Beta")

    def test_stable_label_and_artifact_tags(self):
        self.assertEqual(version.version_label("1.8", "stable"), "1.8")
        self.assertEqual(version.artifact_version_tag("1.8", "stable"), "1.8")
        self.assertEqual(version.source_version_tag("1.8", "stable"), "1.8")

    def test_channel_aliases_are_normalized(self):
        self.assertEqual(version.normalize_version_channel("Development"), version.CHANNEL_BETA)
        self.assertEqual(version.normalize_version_channel("release"), version.CHANNEL_STABLE)

    def test_runtime_version_matches_version_files(self):
        root = Path(__file__).resolve().parent.parent
        expected_version = (root / "VERSION").read_text(encoding="utf-8").strip()
        expected_channel = version.normalize_version_channel((root / "VERSION_CHANNEL").read_text(encoding="utf-8").strip())
        self.assertEqual(version.APP_VERSION, expected_version)
        self.assertEqual(version.APP_VERSION_CHANNEL, expected_channel)
        self.assertEqual(version.APP_VERSION_LABEL, version.version_label(expected_version, expected_channel))
        self.assertEqual(version.APP_ARTIFACT_VERSION_TAG, version.artifact_version_tag(expected_version, expected_channel))
        self.assertEqual(version.APP_SOURCE_VERSION_TAG, version.source_version_tag(expected_version, expected_channel))


if __name__ == "__main__":
    unittest.main()

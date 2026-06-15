import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.app_state import load_json
from core import legal
from core.ui.legal_dialog import LegalAcceptanceDialog


def _app():
    return QApplication.instance() or QApplication([])


class LegalAcceptanceV18Tests(unittest.TestCase):
    def test_missing_acceptance_is_not_current(self):
        self.assertFalse(legal.legal_acceptance_current({}))
        self.assertFalse(
            legal.legal_acceptance_current(
                {
                    "terms_version": legal.TERMS_VERSION,
                    "privacy_version": legal.PRIVACY_VERSION,
                    "accepted_terms": True,
                    "accepted_privacy": False,
                }
            )
        )

    def test_current_acceptance_requires_matching_versions(self):
        settings = {
            "terms_version": legal.TERMS_VERSION,
            "privacy_version": legal.PRIVACY_VERSION,
            "accepted_terms": True,
            "accepted_privacy": True,
            "accepted_at": "2026-06-15T00:00:00Z",
        }
        self.assertTrue(legal.legal_acceptance_current(settings))
        self.assertFalse(legal.legal_acceptance_current(settings, terms_version="1.1"))
        self.assertFalse(legal.legal_acceptance_current(settings, privacy_version="1.1"))

    def test_save_legal_acceptance_writes_required_settings_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            settings_file.write_text('{"theme": "blue"}', encoding="utf-8")

            saved = legal.save_legal_acceptance(settings_file, accepted_at="2026-06-15T00:00:00Z")

            self.assertEqual(saved["theme"], "blue")
            self.assertEqual(saved["terms_version"], "1.0")
            self.assertEqual(saved["privacy_version"], "1.0")
            self.assertTrue(saved["accepted_terms"])
            self.assertTrue(saved["accepted_privacy"])
            self.assertEqual(saved["accepted_at"], "2026-06-15T00:00:00Z")
            disk = json.loads(settings_file.read_text(encoding="utf-8"))
            self.assertTrue(legal.legal_acceptance_current(disk))

    def test_settings_loader_accepts_utf8_bom_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            settings_file.write_text('\ufeff{"accepted_terms": true}', encoding="utf-8")

            loaded = load_json(settings_file, {})

            self.assertTrue(loaded["accepted_terms"])

    def test_dialog_requires_both_checkboxes_before_continue(self):
        app = _app()
        dialog = LegalAcceptanceDialog()
        try:
            self.assertFalse(dialog.continue_button.isEnabled())
            dialog.terms_checkbox.setChecked(True)
            app.processEvents()
            self.assertFalse(dialog.continue_button.isEnabled())
            dialog.privacy_checkbox.setChecked(True)
            app.processEvents()
            self.assertTrue(dialog.continue_button.isEnabled())
        finally:
            dialog.close()
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()

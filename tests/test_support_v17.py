import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from core.support import (
    SUPPORT_EMAIL,
    clear_pending_crash_report,
    create_outlook_email_draft,
    crash_mailto_url,
    pending_crash_report,
    redact_sensitive_text,
    support_mailto_url,
    write_crash_report,
)


class SupportV17Tests(unittest.TestCase):
    def test_redacts_tokens_auth_headers_and_private_paths(self):
        text = (
            "Authorization: Bearer abc123\n"
            "openai_api_key=sk-secret\n"
            r"C:\Users\Owner\AppData\Roaming\1SalemBOT\settings.json"
        )

        redacted = redact_sensitive_text(text)

        self.assertNotIn("abc123", redacted)
        self.assertNotIn("sk-secret", redacted)
        self.assertNotIn("settings.json", redacted.replace("<redacted:settings.json>", ""))
        self.assertIn("<redacted>", redacted)

    def test_support_mailto_uses_default_mail_draft_data(self):
        url = support_mailto_url()
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)

        self.assertEqual(parsed.scheme, "mailto")
        self.assertEqual(urllib.parse.unquote(parsed.path), SUPPORT_EMAIL)
        self.assertIn("1SalemBOT Support Request v", query["subject"][0])
        self.assertIn("App version:", query["body"][0])
        self.assertIn("attach logs manually", query["body"][0].lower())

    def test_crash_log_is_redacted_and_pending_state_can_clear(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            logs_dir = Path(temp_dir) / "logs"
            state_file = Path(temp_dir) / "crash_state.json"
            try:
                raise RuntimeError("access_token=secret-token")
            except RuntimeError as exc:
                crash_path = write_crash_report(
                    type(exc),
                    exc,
                    exc.__traceback__,
                    logs_dir=logs_dir,
                    state_file=state_file,
                )

            content = crash_path.read_text(encoding="utf-8")
            state = json.loads(state_file.read_text(encoding="utf-8"))
            self.assertTrue(state["pending"])
            self.assertNotIn("secret-token", content)
            self.assertIn("<redacted>", content)
            self.assertIsNotNone(pending_crash_report(state_file=state_file))

            url = crash_mailto_url(crash_path)
            crash_query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            self.assertIn("1SalemBOT Crash Report v", crash_query["subject"][0])

        clear_pending_crash_report(state_file=state_file)
        self.assertIsNone(pending_crash_report(state_file=state_file))

    def test_outlook_draft_attaches_redacted_log_without_sending(self):
        class FakeAttachments:
            def __init__(self):
                self.paths = []

            def Add(self, path):
                self.paths.append(path)

        class FakeMail:
            def __init__(self):
                self.To = ""
                self.Subject = ""
                self.Body = ""
                self.Attachments = FakeAttachments()
                self.displayed = False
                self.sent = False

            def Display(self):
                self.displayed = True

            def Send(self):
                self.sent = True

        class FakeOutlook:
            def __init__(self, mail):
                self.mail = mail

            def CreateItem(self, item_type):
                self.item_type = item_type
                return self.mail

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_log = temp_path / "crash.log"
            source_log.write_text(
                "Authorization: Bearer secret-token\n"
                '"access_token": "json-secret"\n'
                "Cookie: private-cookie\n",
                encoding="utf-8",
            )
            mail = FakeMail()
            outlook = FakeOutlook(mail)

            with patch("core.support.LOGS_DIR", temp_path), patch("core.support.sys.platform", "win32"):
                opened = create_outlook_email_draft(
                    SUPPORT_EMAIL,
                    "Subject",
                    "Diagnostic body access_token=body-secret",
                    attachment_path=source_log,
                    com_client_factory=lambda _name: outlook,
                )

            self.assertTrue(opened)
            self.assertEqual(mail.To, SUPPORT_EMAIL)
            self.assertEqual(mail.Subject, "Subject")
            self.assertTrue(mail.displayed)
            self.assertFalse(mail.sent)
            self.assertEqual(len(mail.Attachments.paths), 1)

            attached_path = Path(mail.Attachments.paths[0])
            attached_content = attached_path.read_text(encoding="utf-8")
            self.assertNotIn("secret-token", attached_content)
            self.assertNotIn("json-secret", attached_content)
            self.assertNotIn("private-cookie", attached_content)
            self.assertNotIn("body-secret", mail.Body)
            self.assertIn("<redacted>", attached_content)

    def test_outlook_unavailable_returns_false_for_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_log = Path(temp_dir) / "crash.log"
            source_log.write_text("safe crash", encoding="utf-8")

            with patch("core.support.LOGS_DIR", Path(temp_dir)), patch("core.support.sys.platform", "win32"):
                opened = create_outlook_email_draft(
                    SUPPORT_EMAIL,
                    "Subject",
                    "Body",
                    attachment_path=source_log,
                    com_client_factory=lambda _name: (_ for _ in ()).throw(RuntimeError("Outlook unavailable")),
                )

            self.assertFalse(opened)


if __name__ == "__main__":
    unittest.main()

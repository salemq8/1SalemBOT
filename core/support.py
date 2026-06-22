import json
import os
import platform
import re
import sys
import traceback
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from .app_paths import APP_STORAGE_DIR, CRASH_REPORT_STATE_FILE, LOGS_DIR
from .version import APP_VERSION_LABEL


SUPPORT_EMAIL = "1Salembot.support@gmail.com"
SUPPORT_SUBJECT = f"1SalemBOT Support Request v{APP_VERSION_LABEL}"
CRASH_SUBJECT = f"1SalemBOT Crash Report v{APP_VERSION_LABEL}"
OUTLOOK_MAIL_ITEM = 0

SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s\"']+"),
    re.compile(r"(?i)(authorization\s*[=:]\s*)[^\r\n]+"),
    re.compile(
        r"(?i)([\"']?(?:access_token|refresh_token|device_code|user_code|id_token|openai_api_key|api[_-]?key|client_secret|password|secret|credential|credentials|token)[\"']?\s*[=:]\s*[\"']?)[^\s,;\"'\}\]]+"
    ),
    re.compile(r"(?i)(cookie\s*[:=]\s*)[^\r\n]+"),
    re.compile(r"(?i)(set-cookie\s*[:=]\s*)[^\r\n]+"),
)

SENSITIVE_FILE_NAMES = (
    "settings.json",
    "twitch_auth.json",
    "twitch_bot_auth.json",
    "twitch_channel_auth.json",
    "twitch_bot_auth.dpapi",
    "twitch_channel_auth.dpapi",
    "bot_runtime.json",
    "alert_runtime.json",
    "music_command.json",
    "chat_log.txt",
    "alerts.json",
    "alert_status.json",
)


def utc_timestamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def ensure_logs_dir(logs_dir=None):
    target = Path(logs_dir or LOGS_DIR)
    target.mkdir(parents=True, exist_ok=True)
    return target


def redact_sensitive_text(value):
    text = str(value or "")
    replacements = {
        str(APP_STORAGE_DIR): "<app-data>",
        str(LOGS_DIR): "<logs>",
        str(Path.home()): "<home>",
        os.environ.get("APPDATA", ""): "<appdata>",
        os.environ.get("LOCALAPPDATA", ""): "<localappdata>",
        os.environ.get("TEMP", ""): "<temp>",
        os.environ.get("TMP", ""): "<temp>",
    }
    for raw, replacement in replacements.items():
        if raw:
            text = text.replace(raw, replacement)
            text = text.replace(raw.replace("\\", "/"), replacement)

    for filename in SENSITIVE_FILE_NAMES:
        text = re.sub(rf"(?i)([A-Z]:)?[^\s\"']*{re.escape(filename)}", f"<redacted:{filename}>", text)

    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda match: f"{match.group(1)}<redacted>", text)
    return text


def diagnostic_summary(extra=None):
    lines = [
        "1SalemBOT Diagnostic Summary",
        f"App version: {APP_VERSION_LABEL}",
        f"Windows version: {platform.platform()}",
        f"Python runtime: {platform.python_version()}",
        f"Timestamp: {utc_timestamp()}",
    ]
    if extra:
        lines.append("")
        lines.append("Summary:")
        lines.extend(str(extra).strip().splitlines())
    return redact_sensitive_text("\n".join(lines))


def support_email_body(log_path=None, *, automatic_attachment=False):
    attachment_note = ""
    if log_path:
        if automatic_attachment:
            attachment_note = f"\nA redacted log file has been attached to this draft: {Path(log_path).name}"
        else:
            attachment_note = f"\nLog file available: {Path(log_path).name}"
    return diagnostic_summary(
        "Please describe the issue here.\n"
        f"{attachment_note}\n"
        "Attach logs manually if needed. Do not include passwords, tokens, or API keys."
    )


def crash_email_body(crash_log_path=None, *, automatic_attachment=False):
    path_note = ""
    if crash_log_path:
        path_note = f"\nCrash log: {Path(crash_log_path).name}"
    attachment_note = (
        "A redacted crash log is attached to this draft. Please review the email before sending."
        if automatic_attachment
        else "Please attach the crash log manually if your mail client does not support attachments."
    )
    return diagnostic_summary(
        "Crash report request.\n"
        f"{path_note}\n"
        f"{attachment_note}"
    )


def mailto_url(to_email, subject, body):
    query = urllib.parse.urlencode({"subject": subject, "body": redact_sensitive_text(body)})
    return f"mailto:{urllib.parse.quote(str(to_email or SUPPORT_EMAIL))}?{query}"


def support_mailto_url(log_path=None):
    return mailto_url(SUPPORT_EMAIL, SUPPORT_SUBJECT, support_email_body(log_path, automatic_attachment=False))


def crash_mailto_url(crash_log_path=None):
    return mailto_url(SUPPORT_EMAIL, CRASH_SUBJECT, crash_email_body(crash_log_path, automatic_attachment=False))


def read_redacted_log_text(log_path):
    path = Path(log_path)
    return redact_sensitive_text(path.read_text(encoding="utf-8", errors="replace"))


def create_redacted_log_attachment(log_path, *, output_dir=None):
    if not log_path:
        return None
    source_path = Path(log_path)
    if not source_path.exists() or not source_path.is_file():
        return None

    target_dir = ensure_logs_dir(output_dir)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_path.stem).strip("._") or "crash_log"
    target_path = target_dir / f"{safe_name}_redacted.log"
    target_path.write_text(read_redacted_log_text(source_path), encoding="utf-8")
    return target_path


def create_outlook_email_draft(to_email, subject, body, *, attachment_path=None, com_client_factory=None):
    if not sys.platform.startswith("win"):
        return False

    redacted_attachment = None
    if attachment_path:
        redacted_attachment = create_redacted_log_attachment(attachment_path)
        if redacted_attachment is None:
            return False

    try:
        if com_client_factory is None:
            import comtypes.client as com_client

            com_client_factory = com_client.CreateObject
        outlook = com_client_factory("Outlook.Application")
        mail = outlook.CreateItem(OUTLOOK_MAIL_ITEM)
        mail.To = str(to_email or SUPPORT_EMAIL)
        mail.Subject = str(subject or "")
        mail.Body = redact_sensitive_text(body)
        if redacted_attachment is not None:
            mail.Attachments.Add(str(redacted_attachment))
        mail.Display()
        return True
    except Exception:
        return False


def create_support_outlook_draft(*, attachment_path=None):
    return create_outlook_email_draft(
        SUPPORT_EMAIL,
        SUPPORT_SUBJECT,
        support_email_body(attachment_path, automatic_attachment=bool(attachment_path)),
        attachment_path=attachment_path,
    )


def create_crash_outlook_draft(crash_log_path):
    return create_outlook_email_draft(
        SUPPORT_EMAIL,
        CRASH_SUBJECT,
        crash_email_body(crash_log_path, automatic_attachment=True),
        attachment_path=crash_log_path,
    )


def write_crash_report(exc_type, exc_value, exc_traceback, *, source="app", logs_dir=None, state_file=None):
    logs_path = ensure_logs_dir(logs_dir)
    state_path = Path(state_file or CRASH_REPORT_STATE_FILE)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    crash_path = logs_path / f"crash_{timestamp}.log"
    trace_text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    content = diagnostic_summary(
        f"Source: {source}\n\n"
        "Traceback:\n"
        f"{trace_text}"
    )
    crash_path.write_text(content, encoding="utf-8")
    state = {
        "pending": True,
        "path": str(crash_path),
        "timestamp": utc_timestamp(),
        "source": str(source or "app"),
    }
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return crash_path


def pending_crash_report(state_file=None):
    state_path = Path(state_file or CRASH_REPORT_STATE_FILE)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict) or not state.get("pending"):
        return None
    path = Path(str(state.get("path") or ""))
    if not path.exists():
        return None
    return {
        "path": str(path),
        "timestamp": str(state.get("timestamp") or ""),
        "source": str(state.get("source") or "app"),
    }


def clear_pending_crash_report(state_file=None):
    state_path = Path(state_file or CRASH_REPORT_STATE_FILE)
    try:
        state_path.unlink(missing_ok=True)
    except OSError:
        pass


def install_crash_hooks():
    def excepthook(exc_type, exc_value, exc_traceback):
        try:
            write_crash_report(exc_type, exc_value, exc_traceback, source="unhandled")
        finally:
            sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = excepthook

    if hasattr(threading := __import__("threading"), "excepthook"):
        original_threading_hook = threading.excepthook

        def threading_hook(args):
            try:
                write_crash_report(args.exc_type, args.exc_value, args.exc_traceback, source=f"thread:{args.thread.name if args.thread else 'unknown'}")
            finally:
                original_threading_hook(args)

        threading.excepthook = threading_hook

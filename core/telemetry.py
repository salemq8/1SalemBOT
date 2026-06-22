import platform
import re
import threading
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import requests

from .app_paths import TELEMETRY_FILE, TELEMETRY_LOG_FILE
from .app_state import load_json, save_json
from .version import APP_VERSION_LABEL


SUPABASE_URL = "https://yvuqeulhbrjjpolcnvso.supabase.co"
SUPABASE_PUBLISHABLE_KEY = "sb_publishable_igevwtHLkW2ZADV6M0PUtw_w1Bvv2lQ"
INSTALLATIONS_TABLE = "installations"
DEFAULT_TIMEOUT_SECONDS = 8
INSTALL_ID_PATTERN = re.compile(r"^[a-f0-9-]{32,36}$", re.IGNORECASE)
MAX_LOG_BODY_LENGTH = 4000
DEFAULT_TELEMETRY_LOG_MAX_BYTES = 1024 * 1024
DEFAULT_TELEMETRY_LOG_ROTATE_COUNT = 3


@dataclass
class TelemetryResult:
    ok: bool
    action: str
    install_id: str
    error: str = ""


def utc_timestamp():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rotate_telemetry_log_if_needed(
    log_file=TELEMETRY_LOG_FILE,
    *,
    max_bytes=DEFAULT_TELEMETRY_LOG_MAX_BYTES,
    rotate_count=DEFAULT_TELEMETRY_LOG_ROTATE_COUNT,
):
    try:
        if not log_file.exists() or log_file.stat().st_size < int(max_bytes or 0):
            return
        for index in range(int(rotate_count or 1) - 1, 0, -1):
            source = log_file.with_name(f"{log_file.name}.{index}")
            target = log_file.with_name(f"{log_file.name}.{index + 1}")
            if source.exists():
                if index + 1 > int(rotate_count or 1):
                    source.unlink(missing_ok=True)
                else:
                    source.replace(target)
        log_file.replace(log_file.with_name(f"{log_file.name}.1"))
    except Exception:
        pass


def append_telemetry_log(message, *, log_file=TELEMETRY_LOG_FILE, max_bytes=DEFAULT_TELEMETRY_LOG_MAX_BYTES):
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        rotate_telemetry_log_if_needed(log_file, max_bytes=max_bytes)
        timestamp = utc_timestamp()
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} {message}\n")
    except Exception:
        pass


def truncate_log_value(value, max_length=MAX_LOG_BODY_LENGTH):
    text = str(value if value is not None else "")
    if len(text) > max_length:
        return f"{text[:max_length]}...<truncated>"
    return text


def mask_loaded_key(value):
    return "yes (masked)" if str(value or "").strip() else "no"


def mask_install_id(value):
    text = str(value or "").strip()
    if len(text) <= 8:
        return "<masked>"
    return f"<masked>...{text[-6:]}"


def telemetry_error_category(exc):
    if isinstance(exc, requests.Timeout):
        return "timeout"
    if isinstance(exc, requests.ConnectionError):
        return "network"
    if isinstance(exc, requests.HTTPError):
        return "http"
    if isinstance(exc, requests.RequestException):
        return "request"
    return "exception"


def clean_telemetry_text(value: Any, max_length=255):
    text = str(value or "").strip()
    text = "".join(ch for ch in text if ch.isprintable())
    if len(text) > max_length:
        return text[:max_length]
    return text


def valid_install_id(value):
    return bool(INSTALL_ID_PATTERN.match(str(value or "").strip()))


def load_or_create_install_id(storage_file=TELEMETRY_FILE):
    install_id, _created = load_or_create_install_id_with_status(storage_file)
    return install_id


def load_or_create_install_id_with_status(storage_file=TELEMETRY_FILE):
    data = load_json(storage_file, {})
    install_id = str((data or {}).get("install_id") or "").strip()
    created = False
    if not valid_install_id(install_id):
        install_id = str(uuid.uuid4())
        save_json(storage_file, {"install_id": install_id})
        created = True
    return install_id, created


def build_installation_payload(settings, install_id, *, include_first_seen=False, timestamp=None):
    now = timestamp or utc_timestamp()
    safe_settings = settings if isinstance(settings, dict) else {}
    payload = {
        "install_id": str(install_id),
        "channel_name": clean_telemetry_text(safe_settings.get("channel_login") or safe_settings.get("channel_name")),
        "bot_name": clean_telemetry_text(safe_settings.get("bot_login") or safe_settings.get("bot_name")),
        "app_version": clean_telemetry_text(APP_VERSION_LABEL, 64),
        "os_version": clean_telemetry_text(platform.platform(), 500),
        "last_seen": now,
    }
    if include_first_seen:
        payload["first_seen"] = now
    return payload


class SupabaseTelemetryService:
    def __init__(
        self,
        *,
        supabase_url=SUPABASE_URL,
        publishable_key=SUPABASE_PUBLISHABLE_KEY,
        table=INSTALLATIONS_TABLE,
        storage_file=TELEMETRY_FILE,
        log_file=TELEMETRY_LOG_FILE,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        request_func=None,
        developer_diagnostics=False,
        log_max_bytes=DEFAULT_TELEMETRY_LOG_MAX_BYTES,
    ):
        self.supabase_url = str(supabase_url or "").rstrip("/")
        self.publishable_key = str(publishable_key or "")
        self.table = str(table or INSTALLATIONS_TABLE).strip("/")
        self.storage_file = storage_file
        self.log_file = log_file
        self.timeout = timeout
        self.request_func = request_func or requests.request
        self.developer_diagnostics = bool(developer_diagnostics)
        self.log_max_bytes = int(log_max_bytes or DEFAULT_TELEMETRY_LOG_MAX_BYTES)

    def telemetry_log(self, message, *, detailed=False):
        if detailed and not self.developer_diagnostics:
            return
        append_telemetry_log(message, log_file=self.log_file, max_bytes=self.log_max_bytes)

    @property
    def table_url(self):
        return f"{self.supabase_url}/rest/v1/{self.table}"

    def headers(self, prefer="return=representation"):
        return {
            "apikey": self.publishable_key,
            "Authorization": f"Bearer {self.publishable_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Prefer": prefer,
        }

    def update_existing(self, install_id, payload):
        url = f"{self.table_url}?install_id=eq.{quote(str(install_id), safe='')}"
        self.telemetry_log("Update request prepared", detailed=True)
        self.telemetry_log(f"Update request URL present: {'yes' if url else 'no'}", detailed=True)
        self.telemetry_log(f"Update request payload fields: {sorted(payload.keys())}", detailed=True)
        response = self.request_func(
            "PATCH",
            url,
            headers=self.headers("return=minimal"),
            json=payload,
            timeout=self.timeout,
        )
        self.telemetry_log(f"Update HTTP status code: {getattr(response, 'status_code', 'unknown')}", detailed=True)
        self.telemetry_log(f"Update response body: {truncate_log_value(getattr(response, 'text', ''))}", detailed=True)
        response.raise_for_status()
        return getattr(response, "status_code", None)

    def insert_or_ignore(self, payload):
        url = f"{self.table_url}?on_conflict=install_id"
        self.telemetry_log("Insert/update attempt prepared", detailed=True)
        self.telemetry_log(f"Insert request URL present: {'yes' if url else 'no'}", detailed=True)
        self.telemetry_log(f"Insert request payload fields: {sorted(payload.keys())}", detailed=True)
        response = self.request_func(
            "POST",
            url,
            headers=self.headers("resolution=ignore-duplicates,return=minimal"),
            json=payload,
            timeout=self.timeout,
        )
        self.telemetry_log(f"Insert HTTP status code: {getattr(response, 'status_code', 'unknown')}", detailed=True)
        self.telemetry_log(f"Insert response body: {truncate_log_value(getattr(response, 'text', ''))}", detailed=True)
        response.raise_for_status()
        return getattr(response, "status_code", None)

    def upsert_installation(self, install_id, insert_payload, update_payload):
        insert_status = self.insert_or_ignore(insert_payload)
        update_status = self.update_existing(install_id, update_payload)
        return insert_status, update_status

    def sync_installation(self, settings=None):
        install_id = ""
        try:
            safe_settings = settings if isinstance(settings, dict) else {}
            self.developer_diagnostics = bool(
                self.developer_diagnostics
                or safe_settings.get("developer_diagnostics")
                or safe_settings.get("telemetry_diagnostics")
            )
            self.telemetry_log("Telemetry sync requested")
            self.telemetry_log(f"Supabase URL present: {'yes' if self.supabase_url else 'no'}", detailed=True)
            self.telemetry_log(f"Supabase key present: {'yes' if self.publishable_key else 'no'}", detailed=True)
            self.telemetry_log(f"Supabase key loaded: {mask_loaded_key(self.publishable_key)}", detailed=True)
            install_id, created = load_or_create_install_id_with_status(self.storage_file)
            state_text = "generated" if created else "loaded"
            self.telemetry_log(f"install_id {state_text}: {mask_install_id(install_id)}", detailed=True)
            update_payload = build_installation_payload(safe_settings, install_id, include_first_seen=False)
            insert_payload = build_installation_payload(safe_settings, install_id, include_first_seen=True)
            self.telemetry_log(f"app_version: {update_payload.get('app_version', '')}", detailed=True)
            self.telemetry_log("Telemetry payload prepared with allowed fields only", detailed=True)
            insert_status, update_status = self.upsert_installation(install_id, insert_payload, update_payload)
            self.telemetry_log(f"Telemetry sync succeeded: upserted (insert={insert_status}, update={update_status})")
            return TelemetryResult(True, "upserted", install_id)
        except requests.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            response_body = getattr(getattr(exc, "response", None), "text", "")
            self.telemetry_log(f"Telemetry sync failed: category=http status={status}")
            self.telemetry_log(f"Telemetry HTTP response body: {truncate_log_value(response_body)}", detailed=True)
            self.telemetry_log(f"Telemetry exception stack trace:\n{traceback.format_exc()}", detailed=True)
            return TelemetryResult(False, "failed", install_id, str(exc))
        except Exception as exc:
            try:
                install_id = load_or_create_install_id(self.storage_file)
            except Exception:
                pass
            self.telemetry_log(f"Telemetry sync skipped: category={telemetry_error_category(exc)}")
            self.telemetry_log(f"Telemetry exception: {exc}", detailed=True)
            self.telemetry_log(f"Telemetry exception stack trace:\n{traceback.format_exc()}", detailed=True)
            return TelemetryResult(False, "failed", install_id, str(exc))


def sync_installation(settings=None, **kwargs):
    return SupabaseTelemetryService(**kwargs).sync_installation(settings or {})


def sync_installation_async(settings=None, on_result=None, **kwargs):
    settings_snapshot = dict(settings or {})

    def worker():
        result = sync_installation(settings_snapshot, **kwargs)
        if callable(on_result):
            try:
                on_result(result)
            except Exception:
                pass

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread

import re
import time

from .app_paths import DIAGNOSTICS_LOG_FILE


DIAGNOSTICS_LOG_MAX_BYTES = 1024 * 1024
DIAGNOSTICS_LOG_ROTATE_COUNT = 3
REPEATED_SUMMARY_EVERY = 100

_WINDOWS_PATH_RE = re.compile(r"(?i)([A-Z]:\\|\\\\[^\\]+\\|%APPDATA%|AppData\\Roaming)")
_WINDOWS_FULL_PATH_RE = re.compile(r"(?i)(?:[A-Z]:\\|\\\\[^\\\s]+\\|%APPDATA%\\|AppData\\Roaming\\)[^\s\"']+")
_URL_RE = re.compile(r"(?i)\b(?:https?|wss?)://")
_AUTH_RE = re.compile(r"(?i)(Authorization\s*[:=]\s*(?:Bearer|OAuth)\s+)[^\s\"']+")
_TOKEN_RE = re.compile(r"(?i)((?:access_token|refresh_token|device_code|user_code|api_key|apikey|client_secret|password|secret)\s*[:=]\s*[\"']?)[^,\s\"'}]+")
_USER_ID_RE = re.compile(r"(?i)((?:user_id|broadcaster_user_id|bot_user_id|channel_user_id)\s*[:=]\s*[\"']?)[^,\s\"'}]+")
_SCOPES_RE = re.compile(r"(?i)((?:token scopes|scopes)\s*[:=]\s*)(.+)$")

_DIAGNOSTIC_MARKERS = (
    "SSL CERT FILE",
    "[QT] Plugin path",
    "token path:",
    "token type:",
    "token user_id:",
    "token scopes:",
    "Checked:",
    "Expected file:",
    "Music command bridge ready:",
    "Session ready:",
    "Connecting to WebSocket:",
    "Removing conflicting subscription:",
    "Delete subscription",
    "request URL",
    "request payload",
    "response body",
    "payload dump",
    "token file:",
    "token saved successfully:",
    "authorization in progress",
    "profile lookup failed:",
    "profile lookup recovered",
    "BOT LOGIN:",
    "CHANNEL LOGIN:",
    "BOT AUTH LOGIN:",
    "CHANNEL AUTH LOGIN:",
    "Bot moderator status",
    "channel:bot:",
    "Full broadcaster/channel permissions",
)

_HIGH_FREQUENCY_PATTERNS = (
    ("chat_message", re.compile(r"^\[[A-Z]+ CHAT\]\s+[^:]+:")),
    ("chat_ignore", re.compile(r"^\[[A-Z]+ CHAT\] Ignored event")),
    ("chat_no_trigger", re.compile(r"^\[[A-Z]+ CHAT\] No trigger matched")),
    ("chat_trigger", re.compile(r"^\[[A-Z]+ CHAT\] Trigger matched")),
    ("chat_cleaned", re.compile(r"^\[[A-Z]+ CHAT\] Cleaned text")),
    ("chat_music_ignored", re.compile(r"^\[[A-Z]+ CHAT\] Ignored normal chat message for music")),
    ("chat_music_parse", re.compile(r"^\[[A-Z]+ CHAT\] Music command detected")),
    ("chat_music_forward", re.compile(r"^\[[A-Z]+ CHAT\] Forwarding .* into music pipeline")),
    ("chat_profile", re.compile(r"^\[[A-Z]+ PROFILE\]")),
    ("viewer_count", re.compile(r"^\[VIEWERS\] Counted message from")),
    ("viewer_duplicate", re.compile(r"^\[VIEWERS\] Ignored duplicate message from")),
    ("eventsub_chat", re.compile(r"^\[EVENTSUB\] Chat event received")),
    ("eventsub_alert_debug", re.compile(r"^\[EVENTSUB\] Alert event received")),
    ("eventsub_keepalive", re.compile(r"^\[EVENTSUB\] Connection healthy")),
    ("eventsub_subscription_debug", re.compile(r"^\[EVENTSUB\] (Subscription enabled|Duplicate subscription|Cleaned|Removing|Deleted conflicting|Delete response body)")),
    ("twitch_send_debug", re.compile(r"^\[TWITCH (SEND|SENT)\]")),
    ("alerts_saved_debug", re.compile(r"^\[ALERTS\] Saved alert event")),
    ("alerts_scope_debug", re.compile(r"^\[ALERTS\] .+: scope check ok")),
    ("music_metadata", re.compile(r"^\[Music\] (Checking track metadata|Thumbnail|VLC state|Last VLC state|Command detected|Ignored music command|Skip handoff)")),
    ("alert_cached_render", re.compile(r"^\[Alerts\] Rendered \d+ cached")),
)

_REPEATED_STATE = {}


def rotate_log_if_needed(log_file=DIAGNOSTICS_LOG_FILE, *, max_bytes=DIAGNOSTICS_LOG_MAX_BYTES, rotate_count=DIAGNOSTICS_LOG_ROTATE_COUNT):
    try:
        if not log_file.exists() or log_file.stat().st_size < int(max_bytes or 0):
            return
        keep = max(1, int(rotate_count or 1))
        for index in range(keep, 0, -1):
            source = log_file.with_name(f"{log_file.name}.{index}")
            target = log_file.with_name(f"{log_file.name}.{index + 1}")
            if not source.exists():
                continue
            if index >= keep:
                source.unlink(missing_ok=True)
            else:
                source.replace(target)
        log_file.replace(log_file.with_name(f"{log_file.name}.1"))
    except Exception:
        pass


def redact_diagnostic_text(text):
    value = str(text or "")
    value = _AUTH_RE.sub(r"\1<redacted>", value)
    value = _TOKEN_RE.sub(r"\1<redacted>", value)
    value = _USER_ID_RE.sub(r"\1<redacted>", value)
    value = _SCOPES_RE.sub(r"\1<redacted>", value)
    value = _WINDOWS_FULL_PATH_RE.sub("<path>", value)
    return value


def classify_log_line(text):
    value = str(text or "").strip()
    if not value:
        return "empty", None
    for key, pattern in _HIGH_FREQUENCY_PATTERNS:
        if pattern.search(value):
            return "high_frequency", key
    if any(marker in value for marker in _DIAGNOSTIC_MARKERS):
        return "diagnostic", None
    if _WINDOWS_PATH_RE.search(value):
        return "diagnostic", None
    if _URL_RE.search(value) and not value.startswith("[Updates] Update found"):
        return "diagnostic", None
    return "user", None


def summarize_repeated_line(key, text):
    value = str(text or "").strip()
    if key == "chat_message":
        return "chat message received"
    if key == "eventsub_chat":
        return "EventSub chat event received"
    if key == "viewer_count":
        return "viewer message counted"
    if key == "chat_no_trigger":
        return "chat message did not match trigger"
    if key == "alert_cached_render":
        return "cached alert render summary"
    if key and key.startswith("music_"):
        return "music debug event"
    if key:
        return key.replace("_", " ")
    return value[:160]


def _write_repeated_summary(key, *, log_file=DIAGNOSTICS_LOG_FILE, max_bytes=DIAGNOSTICS_LOG_MAX_BYTES):
    state = _REPEATED_STATE.get(key) or {}
    suppressed = int(state.get("suppressed") or 0)
    if suppressed <= 0:
        return False
    summary = state.get("summary") or key
    write_diagnostics_line(
        f"[Diagnostics] Repeated {suppressed} times: {summary}",
        log_file=log_file,
        max_bytes=max_bytes,
    )
    state["suppressed"] = 0
    state["last_summary_at"] = time.monotonic()
    _REPEATED_STATE[key] = state
    return True


def route_repeated_diagnostic_line(key, text, *, log_file=DIAGNOSTICS_LOG_FILE, max_bytes=DIAGNOSTICS_LOG_MAX_BYTES):
    summary = summarize_repeated_line(key, text)
    state = _REPEATED_STATE.setdefault(
        key,
        {
            "seen": False,
            "suppressed": 0,
            "summary": summary,
            "last_summary_at": 0.0,
        },
    )
    state["summary"] = summary
    if not state.get("seen"):
        state["seen"] = True
        write_diagnostics_line(text, log_file=log_file, max_bytes=max_bytes)
        return True

    state["suppressed"] = int(state.get("suppressed") or 0) + 1
    if state["suppressed"] >= REPEATED_SUMMARY_EVERY:
        return _write_repeated_summary(key, log_file=log_file, max_bytes=max_bytes)
    return True


def is_diagnostic_log_line(text):
    category, _key = classify_log_line(text)
    return category in {"diagnostic", "high_frequency"}


def write_diagnostics_line(text, *, log_file=DIAGNOSTICS_LOG_FILE, max_bytes=DIAGNOSTICS_LOG_MAX_BYTES):
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        rotate_log_if_needed(log_file, max_bytes=max_bytes)
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(redact_diagnostic_text(text).rstrip() + "\n")
    except Exception:
        pass


def route_diagnostic_line(text, *, log_file=DIAGNOSTICS_LOG_FILE, max_bytes=DIAGNOSTICS_LOG_MAX_BYTES):
    category, key = classify_log_line(text)
    if category == "empty":
        return False
    if category == "high_frequency":
        route_repeated_diagnostic_line(key, text, log_file=log_file, max_bytes=max_bytes)
        return True
    if category != "diagnostic":
        return False
    write_diagnostics_line(text, log_file=log_file, max_bytes=max_bytes)
    return True


def flush_repeated_log_summaries(*, log_file=DIAGNOSTICS_LOG_FILE, max_bytes=DIAGNOSTICS_LOG_MAX_BYTES):
    wrote = False
    for key in list(_REPEATED_STATE):
        wrote = _write_repeated_summary(key, log_file=log_file, max_bytes=max_bytes) or wrote
    return wrote


def reset_repeated_log_state():
    _REPEATED_STATE.clear()

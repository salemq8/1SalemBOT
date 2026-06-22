import errno
import webbrowser
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from .app_paths import (
    AUTH_STATE_FILE,
    BOT_SECURE_TOKEN_FILE,
    BOT_TOKEN_FILE,
    CHANNEL_SECURE_TOKEN_FILE,
    CHANNEL_TOKEN_FILE,
    LEGACY_APPDATA_BOT_TOKEN_FILE,
    LEGACY_APPDATA_CHANNEL_TOKEN_FILE,
    LEGACY_TOKEN_FILE,
)
from .app_state import load_json, save_json
from .runtime_logging import write_diagnostics_line
from .secure_storage import load_encrypted_json, save_encrypted_json


CLIENT_ID = "e1t33efjfvvzzcq16kb5xc3uu99lls"
REDIRECT_URI = "https://localhost"
VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
HELIX_USERS_URL = "https://api.twitch.tv/helix/users"
DEVICE_CODE_URL = "https://id.twitch.tv/oauth2/device"
TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TOKEN_SCHEMA_VERSION = 2
REFRESH_RETRY_COOLDOWN_SECONDS = 120
MIGRATION_FAILED_RETRY_COOLDOWN_SECONDS = 24 * 60 * 60
TOKEN_DELETE_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4)

BOT_AUTH_ROLE = "bot"
CHANNEL_AUTH_ROLE = "channel"
AUTH_ROLES = (BOT_AUTH_ROLE, CHANNEL_AUTH_ROLE)

ROLE_LABELS = {
    BOT_AUTH_ROLE: "Bot Account",
    CHANNEL_AUTH_ROLE: "Channel Account",
}

SCOPES_BY_ROLE = {
    BOT_AUTH_ROLE: [
        "user:read:chat",
        "user:write:chat",
        "user:bot",
        "moderator:manage:banned_users",
        "moderator:manage:chat_messages",
    ],
    CHANNEL_AUTH_ROLE: [
        "user:read:chat",
        "user:write:chat",
        "user:read:follows",
        "bits:read",
        "channel:bot",
        "user:bot",
        "moderation:read",
        "moderator:read:chatters",
        "moderator:read:followers",
        "moderator:read:shoutouts",
        "moderator:manage:banned_users",
        "moderator:manage:chat_messages",
        "channel:manage:broadcast",
        "channel:read:redemptions",
        "channel:read:polls",
        "channel:read:predictions",
        "channel:read:hype_train",
        "channel:read:subscriptions",
        "channel:read:vips",
    ],
}

TOKEN_FILES = {
    BOT_AUTH_ROLE: BOT_TOKEN_FILE,
    CHANNEL_AUTH_ROLE: CHANNEL_TOKEN_FILE,
}

SECURE_TOKEN_FILES = {
    BOT_AUTH_ROLE: BOT_SECURE_TOKEN_FILE,
    CHANNEL_AUTH_ROLE: CHANNEL_SECURE_TOKEN_FILE,
}

_refresh_lock = threading.Lock()
_refresh_inflight = {}
_auth_log_lock = threading.Lock()
_auth_log_once_keys = set()
_auth_log_last_at = {}
_migration_attempted_roles = set()
_migration_lock = threading.Lock()


def _is_transient_token_file_error(exc):
    if isinstance(exc, PermissionError):
        return True
    if getattr(exc, "winerror", None) == 5:
        return True
    return getattr(exc, "errno", None) in {errno.EACCES, errno.EPERM}


def normalize_role(role: str | None):
    return role if role in AUTH_ROLES else BOT_AUTH_ROLE


def get_role_label(role: str | None):
    return ROLE_LABELS[normalize_role(role)]


def get_token_file(role: str | None):
    return TOKEN_FILES[normalize_role(role)]


def get_secure_token_file(role: str | None):
    return SECURE_TOKEN_FILES[normalize_role(role)]


def get_role_scopes(role: str | None):
    return list(SCOPES_BY_ROLE[normalize_role(role)])


def auth_diagnostics(message, *, event_key=None, cooldown_seconds=None):
    if event_key:
        now = time.time()
        with _auth_log_lock:
            if cooldown_seconds is None:
                if event_key in _auth_log_once_keys:
                    return False
                _auth_log_once_keys.add(event_key)
            else:
                last_at = float(_auth_log_last_at.get(event_key, 0.0) or 0.0)
                if now - last_at < float(cooldown_seconds):
                    return False
                _auth_log_last_at[event_key] = now
    write_diagnostics_line(f"[TWITCH AUTH] {message}")
    return True


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_auth_state():
    return {
        "roles": {
            BOT_AUTH_ROLE: {"state": "disconnected", "message": "", "updated_at": ""},
            CHANNEL_AUTH_ROLE: {"state": "disconnected", "message": "", "updated_at": ""},
        }
    }


def load_auth_state():
    state = load_json(AUTH_STATE_FILE, default_auth_state())
    if not isinstance(state, dict):
        state = default_auth_state()
    roles = state.setdefault("roles", {})
    for role in AUTH_ROLES:
        role_state = roles.get(role)
        if not isinstance(role_state, dict):
            role_state = {}
        role_state.setdefault("state", "disconnected")
        role_state.setdefault("message", "")
        role_state.setdefault("updated_at", "")
        roles[role] = role_state
    return state


def save_auth_state(state):
    return save_json(AUTH_STATE_FILE, state)


def get_role_auth_runtime_state(role):
    normalized_role = normalize_role(role)
    return dict(load_auth_state().get("roles", {}).get(normalized_role, {}))


def set_role_auth_runtime_state(role, state, message="", *, reason="", explicit_disconnected=None, clear_migration_failure=False):
    normalized_role = normalize_role(role)
    payload = load_auth_state()
    role_state = dict(payload.setdefault("roles", {}).get(normalized_role, {}))
    role_state["state"] = str(state or "disconnected")
    role_state["message"] = str(message or "")
    role_state["reason"] = str(reason or "")
    role_state["updated_at"] = _utc_now_iso()
    if explicit_disconnected is not None:
        role_state["explicitly_disconnected"] = bool(explicit_disconnected)
        if explicit_disconnected:
            role_state["disconnected_at"] = role_state["updated_at"]
    if clear_migration_failure:
        role_state.pop("migration_failed_at", None)
        role_state.pop("migration_failed_reason", None)
    payload["roles"][normalized_role] = role_state
    save_auth_state(payload)
    return role_state


def begin_role_auth_flow(role):
    normalized_role = normalize_role(role)
    with _migration_lock:
        _migration_attempted_roles.discard(normalized_role)
    return set_role_auth_runtime_state(
        normalized_role,
        "waiting_for_device_code",
        "Waiting for Twitch authorization",
        explicit_disconnected=False,
        clear_migration_failure=True,
    )


def mark_role_connected(role):
    normalized_role = normalize_role(role)
    with _migration_lock:
        _migration_attempted_roles.discard(normalized_role)
    return set_role_auth_runtime_state(
        normalized_role,
        "connected",
        "Twitch connected",
        explicit_disconnected=False,
        clear_migration_failure=True,
    )


def mark_role_disconnected(role, message="No saved token"):
    normalized_role = normalize_role(role)
    return set_role_auth_runtime_state(
        normalized_role,
        "disconnected",
        message,
        reason="user_disconnected",
        explicit_disconnected=True,
    )


def is_role_explicitly_disconnected(role):
    return bool(get_role_auth_runtime_state(role).get("explicitly_disconnected"))


def _raise_if_role_disconnected_for_token_save(role, stage):
    normalized_role = normalize_role(role)
    if not is_role_explicitly_disconnected(normalized_role):
        return
    auth_diagnostics(
        f"{get_role_label(normalized_role)} stale token save blocked after disconnect",
        event_key=f"{normalized_role}:stale_token_save_blocked:{stage}",
        cooldown_seconds=30,
    )
    raise ValueError("Reconnect required. Role disconnected during token save.")


def _safe_unlink_token_file(path, *, retry_delays=None, event_key=None):
    target = Path(path)
    attempts = [0.0] + list(retry_delays if retry_delays is not None else TOKEN_DELETE_RETRY_DELAYS)
    last_exc = None

    for index, delay in enumerate(attempts):
        if delay:
            time.sleep(delay)
        try:
            target.unlink(missing_ok=True)
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            last_exc = exc
            if not _is_transient_token_file_error(exc) or index >= len(attempts) - 1:
                break
            auth_diagnostics(
                f"Token file delete retried after file lock: {target.name}",
                event_key=f"token_delete_retry:{event_key or target.name}",
                cooldown_seconds=30,
            )

    auth_diagnostics(
        f"Token file delete failed after retries: {target.name}",
        event_key=f"token_delete_failed:{event_key or target.name}",
        cooldown_seconds=30,
    )
    if last_exc is not None:
        raise last_exc
    return False


def mark_role_migration_failed(role, reason):
    normalized_role = normalize_role(role)
    state = set_role_auth_runtime_state(
        normalized_role,
        "migration_failed",
        "Legacy token migration failed",
        reason=reason,
        explicit_disconnected=False,
    )
    payload = load_auth_state()
    role_state = payload.setdefault("roles", {}).setdefault(normalized_role, {})
    role_state["migration_failed_at"] = _utc_now_iso()
    role_state["migration_failed_reason"] = str(reason or "validation_failed")
    save_auth_state(payload)
    return state


def _parse_iso_timestamp(value):
    try:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            return None
        return datetime.fromisoformat(text)
    except Exception:
        return None


def should_skip_migration_for_role(role):
    normalized_role = normalize_role(role)
    state = get_role_auth_runtime_state(normalized_role)
    if state.get("explicitly_disconnected"):
        auth_diagnostics(
            f"{get_role_label(normalized_role)} migration skipped: user_disconnected_skip_migration",
            event_key=f"{normalized_role}:migration_skip:user_disconnected",
        )
        return True
    failed_at = _parse_iso_timestamp(state.get("migration_failed_at"))
    if failed_at is not None:
        age = (datetime.now(failed_at.tzinfo) - failed_at).total_seconds()
        if age < MIGRATION_FAILED_RETRY_COOLDOWN_SECONDS:
            reason = state.get("migration_failed_reason") or "migration_failed"
            auth_diagnostics(
                f"{get_role_label(normalized_role)} migration skipped: {reason}",
                event_key=f"{normalized_role}:migration_skip:{reason}",
            )
            return True
    return False


def build_auth_url(role: str = BOT_AUTH_ROLE):
    normalized_role = normalize_role(role)
    query = urlencode(
        {
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "token",
            "scope": " ".join(get_role_scopes(normalized_role)),
            "state": normalized_role,
            "force_verify": "true",
        }
    )
    return f"https://id.twitch.tv/oauth2/authorize?{query}"


def open_twitch_login(role: str = BOT_AUTH_ROLE):
    url = build_auth_url(role)
    webbrowser.open(url)
    return url


def extract_token_from_redirect_url(full_url: str):
    if not full_url:
        return None

    full_url = full_url.strip()

    try:
        if full_url.startswith("#"):
            fragment = full_url[1:]
        else:
            parsed = urlparse(full_url)
            fragment = parsed.fragment
            if not fragment and "access_token=" in parsed.query:
                fragment = parsed.query

        if not fragment:
            return None

        token = parse_qs(fragment).get("access_token", [None])[0]
        return token.strip() if token else None
    except Exception:
        return None


def extract_auth_state_from_redirect_url(full_url: str):
    if not full_url:
        return None

    full_url = full_url.strip()

    try:
        if full_url.startswith("#"):
            parsed_values = parse_qs(full_url[1:])
        else:
            parsed = urlparse(full_url)
            parsed_values = parse_qs(parsed.query)
            if "state" not in parsed_values and parsed.fragment:
                parsed_values.update(parse_qs(parsed.fragment))

        state = parsed_values.get("state", [None])[0]
        return state.strip() if isinstance(state, str) and state.strip() else None
    except Exception:
        return None


def validate_token(token: str):
    response = requests.get(
        VALIDATE_URL,
        headers={"Authorization": f"OAuth {token.strip()}"},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def _normalize_token_data(data):
    if not isinstance(data, dict):
        return {}

    scopes = data.get("scopes") or []
    if not isinstance(scopes, list):
        scopes = []

    return {
        "access_token": str(data.get("access_token") or "").strip(),
        "refresh_token": str(data.get("refresh_token") or "").strip(),
        "token_type": data.get("token_type", "bearer"),
        "saved_at": data.get("saved_at", ""),
        "source": data.get("source", ""),
        "role": normalize_role(data.get("role")),
        "login": data.get("login", ""),
        "display_name": data.get("display_name", ""),
        "user_id": data.get("user_id", ""),
        "client_id": data.get("client_id", ""),
        "scopes": scopes,
        "expires_in": data.get("expires_in", 0),
        "expires_at": data.get("expires_at", ""),
        "last_validated_at": data.get("last_validated_at", ""),
        "profile_image_url": data.get("profile_image_url", ""),
        "secure_storage": data.get("secure_storage", ""),
        "token_schema_version": data.get("token_schema_version", 1),
    }


def _load_secure_token_payload(role):
    normalized_role = normalize_role(role)
    secure_file = get_secure_token_file(normalized_role)
    try:
        payload = load_encrypted_json(secure_file)
    except Exception as exc:
        auth_diagnostics(f"{get_role_label(normalized_role)} secure token read failed: {exc.__class__.__name__}")
        return {}
    if payload and normalize_role(payload.get("role")) != normalized_role:
        auth_diagnostics(f"{get_role_label(normalized_role)} secure token role mismatch ignored")
        return {}
    return payload if isinstance(payload, dict) else {}


def _combine_metadata_and_secret(role, metadata):
    normalized_role = normalize_role(role)
    data = _normalize_token_data(metadata)
    secret_payload = _load_secure_token_payload(normalized_role)
    if secret_payload:
        data["access_token"] = str(secret_payload.get("access_token") or "").strip()
        data["refresh_token"] = str(secret_payload.get("refresh_token") or "").strip()
        data["token_type"] = str(secret_payload.get("token_type") or data.get("token_type") or "bearer")
        data["secure_storage"] = data.get("secure_storage") or "windows_dpapi_current_user"
    return data


def _metadata_has_plaintext_secret(metadata):
    if not isinstance(metadata, dict):
        return False
    return bool(
        str(metadata.get("access_token") or "").strip()
        or str(metadata.get("refresh_token") or "").strip()
    )


def _has_secure_access_token(role):
    payload = _load_secure_token_payload(role)
    return bool(str(payload.get("access_token") or "").strip())


def _without_plaintext_secret(data):
    scrubbed = dict(data or {})
    scrubbed["access_token"] = ""
    scrubbed["refresh_token"] = ""
    return scrubbed


def legacy_token_error_category(exc=None, data=None):
    if data is not None:
        if not isinstance(data, dict):
            return "legacy_token_json_invalid"
        if not str(data.get("access_token") or "").strip():
            return "legacy_token_no_access_token"
    if exc is None:
        return "validation_failed"

    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code:
        return f"validation_failed_http_{status_code}"

    message = str(exc or "").strip().lower()
    exc_name = exc.__class__.__name__
    if isinstance(exc, ValueError):
        if "empty" in message:
            return "legacy_token_empty"
        if "access token" in message:
            return "legacy_token_no_access_token"
        if "refresh token" in message:
            return "legacy_token_no_refresh_token"
        if "different application" in message or "client" in message:
            return "legacy_token_client_id_mismatch"
        if "scope" in message or "permission" in message:
            return "missing_scopes"
        if "identity" in message or "login" in message or "user_id" in message:
            return "validation_failed_missing_identity"
        return "validation_failed"
    if exc_name in {"JSONDecodeError"}:
        return "legacy_token_json_invalid"
    if "decrypt" in message or "dpapi" in message:
        return "dpapi_decrypt_failed"
    return "validation_failed"


def _expires_at_from_seconds(expires_in):
    try:
        seconds = int(expires_in or 0)
    except Exception:
        seconds = 0
    if seconds <= 0:
        return ""
    return (datetime.now() + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _metadata_payload(role, token_payload, validation, profile, source):
    normalized_role = normalize_role(role)
    now = datetime.now().isoformat(timespec="seconds")
    expires_in = int(token_payload.get("expires_in") or validation.get("expires_in") or 0)
    return {
        "saved_at": now,
        "source": source,
        "role": normalized_role,
        "login": profile.get("login") or validation.get("login", ""),
        "display_name": profile.get("display_name", ""),
        "user_id": validation.get("user_id", ""),
        "client_id": validation.get("client_id", ""),
        "scopes": validation.get("scopes") or token_payload.get("scope") or [],
        "expires_in": expires_in,
        "expires_at": _expires_at_from_seconds(expires_in),
        "last_validated_at": now,
        "profile_image_url": profile.get("profile_image_url", ""),
        "secure_storage": "windows_dpapi_current_user",
        "token_schema_version": TOKEN_SCHEMA_VERSION,
    }


def _secret_payload(role, token_payload):
    return {
        "schema_version": TOKEN_SCHEMA_VERSION,
        "role": normalize_role(role),
        "access_token": str(token_payload.get("access_token") or "").strip(),
        "refresh_token": str(token_payload.get("refresh_token") or "").strip(),
        "token_type": str(token_payload.get("token_type") or "bearer"),
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }


def _save_token_payload(token_payload, role=BOT_AUTH_ROLE, source="device_code", validation_details=None, profile_details=None):
    normalized_role = normalize_role(role)
    access_token = str((token_payload or {}).get("access_token") or "").strip()
    if not access_token:
        raise ValueError("Token response did not include an access token.")

    _raise_if_role_disconnected_for_token_save(normalized_role, "start")
    validation = validation_details or validate_token(access_token)
    _raise_if_role_disconnected_for_token_save(normalized_role, "validated")
    if str(validation.get("client_id") or "").strip() != CLIENT_ID:
        raise ValueError("Twitch token was issued for a different application.")
    if not str(validation.get("login") or "").strip() or not str(validation.get("user_id") or "").strip():
        raise ValueError("Twitch token validation did not include account identity.")

    granted_scopes = validation.get("scopes") or []
    required_scopes = get_role_scopes(normalized_role)
    missing_scopes = [scope for scope in required_scopes if scope not in granted_scopes]
    if missing_scopes:
        readable = ", ".join(missing_scopes)
        raise ValueError(f"Missing required Twitch scopes for {get_role_label(normalized_role)}: {readable}")

    profile = profile_details
    if profile is None:
        try:
            profile = fetch_user_profile(
                access_token,
                validation.get("client_id", "") or CLIENT_ID,
                validation.get("user_id", ""),
            )
        except Exception as exc:
            auth_diagnostics(f"{get_role_label(normalized_role)} profile fetch failed during token save: {exc.__class__.__name__}")
            profile = {}

    _raise_if_role_disconnected_for_token_save(normalized_role, "profile")
    metadata = _metadata_payload(normalized_role, token_payload, validation, profile or {}, source)
    secret = _secret_payload(normalized_role, token_payload)
    secure_file = get_secure_token_file(normalized_role)
    token_file = get_token_file(normalized_role)

    save_encrypted_json(secure_file, secret)
    verified_secret = _load_secure_token_payload(normalized_role)
    if verified_secret.get("access_token") != access_token:
        raise RuntimeError("Encrypted token verification failed after saving.")
    try:
        _raise_if_role_disconnected_for_token_save(normalized_role, "secure")
    except Exception:
        _safe_unlink_token_file(secure_file, event_key=f"{normalized_role}:secure_rollback")
        raise

    token_file.parent.mkdir(parents=True, exist_ok=True)
    save_json(token_file, metadata)
    mark_role_connected(normalized_role)
    return _combine_metadata_and_secret(normalized_role, load_json(token_file, {}))


def _sanitize_legacy_plaintext_file(path, role, original_data):
    try:
        if not Path(path).exists():
            return
        data = dict(original_data or {})
        data.pop("access_token", None)
        data.pop("refresh_token", None)
        data["role"] = normalize_role(role)
        data["secure_storage"] = "migrated_to_windows_dpapi_current_user"
        data["token_schema_version"] = TOKEN_SCHEMA_VERSION
        save_json(Path(path), data)
    except Exception as exc:
        auth_diagnostics(f"{get_role_label(role)} legacy plaintext sanitize skipped: {exc.__class__.__name__}")


def fetch_user_profile(access_token: str, client_id: str, user_id: str):
    if not access_token or not client_id or not user_id:
        return {}

    response = requests.get(
        HELIX_USERS_URL,
        headers={
            "Client-Id": client_id,
            "Authorization": f"Bearer {access_token.strip()}",
        },
        params={"id": user_id},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json().get("data", [])
    if not data:
        return {}
    user = data[0]
    return {
        "login": user.get("login", ""),
        "display_name": user.get("display_name", ""),
        "profile_image_url": user.get("profile_image_url", ""),
    }


def _legacy_sources_for_role(role):
    normalized_role = normalize_role(role)
    sources = [(get_token_file(normalized_role), "plaintext_token")]
    if normalized_role == BOT_AUTH_ROLE:
        sources.append((LEGACY_APPDATA_BOT_TOKEN_FILE, "legacy_token"))
        sources.append((LEGACY_TOKEN_FILE, "legacy_token"))
    else:
        sources.append((LEGACY_APPDATA_CHANNEL_TOKEN_FILE, "legacy_token"))
    return sources


def _attempt_legacy_token_migration(role, path, source_label, raw_data):
    normalized_role = normalize_role(role)
    data = _normalize_token_data(raw_data)
    access_token = str(data.get("access_token") or "").strip()
    if not access_token:
        return False

    token_payload = {
        "access_token": access_token,
        "refresh_token": data.get("refresh_token", ""),
        "token_type": data.get("token_type", "bearer"),
        "expires_in": data.get("expires_in", 0),
    }
    validation = validate_token(token_payload["access_token"])
    _save_token_payload(
        token_payload,
        role=normalized_role,
        source=data.get("source") or "legacy_migration",
        validation_details=validation,
    )
    _sanitize_legacy_plaintext_file(path, normalized_role, raw_data)
    label = "plaintext token" if source_label == "plaintext_token" else "legacy token"
    auth_diagnostics(
        f"{get_role_label(normalized_role)} {label} migrated to Windows DPAPI storage",
        event_key=f"{normalized_role}:migration_success:{source_label}",
    )
    return True


def migrate_legacy_token_if_needed(role=None, *, force=False):
    roles = AUTH_ROLES if role is None else (normalize_role(role),)
    migrated_any = False

    for role_name in roles:
        normalized_role = normalize_role(role_name)
        if not force:
            if should_skip_migration_for_role(normalized_role):
                continue
            if _has_secure_access_token(normalized_role):
                continue
            with _migration_lock:
                if normalized_role in _migration_attempted_roles:
                    continue
                _migration_attempted_roles.add(normalized_role)

        for legacy_file, source_label in _legacy_sources_for_role(normalized_role):
            if not Path(legacy_file).exists():
                continue
            raw_data = load_json(legacy_file, {})
            if not isinstance(raw_data, dict) or not str(raw_data.get("access_token") or "").strip():
                continue
            try:
                set_role_auth_runtime_state(normalized_role, "migrating", "Migrating legacy Twitch token")
                if _attempt_legacy_token_migration(normalized_role, Path(legacy_file), source_label, raw_data):
                    mark_role_connected(normalized_role)
                    migrated_any = True
                    break
            except Exception as exc:
                category = legacy_token_error_category(exc, raw_data)
                mark_role_migration_failed(normalized_role, category)
                label = "plaintext token" if source_label == "plaintext_token" else "legacy token"
                auth_diagnostics(
                    f"{get_role_label(normalized_role)} {label} migration failed once: {category}",
                    event_key=f"{normalized_role}:migration_failed:{source_label}:{category}",
                )
                break

    return migrated_any


def save_token(token: str, role: str = BOT_AUTH_ROLE, source: str = "manual", validation_details=None):
    normalized_role = normalize_role(role)
    token = (token or "").strip()
    if not token:
        raise ValueError("Token is empty")

    return _save_token_payload(
        {
            "access_token": token,
            "refresh_token": "",
            "token_type": "bearer",
            "expires_in": (validation_details or {}).get("expires_in", 0),
        },
        role=normalized_role,
        source=source,
        validation_details=validation_details,
    )


def save_token_response(token_payload, role: str = BOT_AUTH_ROLE, source: str = "device_code", validation_details=None):
    return _save_token_payload(token_payload or {}, role=role, source=source, validation_details=validation_details)


def start_device_code_authorization(role=BOT_AUTH_ROLE, request_func=None):
    normalized_role = normalize_role(role)
    scopes = get_role_scopes(normalized_role)
    post = request_func or requests.post
    response = post(
        DEVICE_CODE_URL,
        data={
            "client_id": CLIENT_ID,
            "scopes": " ".join(scopes),
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    required = ("device_code", "user_code", "verification_uri", "expires_in", "interval")
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"Twitch device authorization response missing: {', '.join(missing)}")
    return {
        "role": normalized_role,
        "device_code": str(payload.get("device_code") or ""),
        "user_code": str(payload.get("user_code") or ""),
        "verification_uri": str(payload.get("verification_uri") or ""),
        "expires_in": int(payload.get("expires_in") or 0),
        "interval": max(1, int(payload.get("interval") or 5)),
        "scopes": scopes,
        "requested_at": time.time(),
    }


def twitch_error_code(response):
    try:
        payload = response.json()
    except Exception:
        payload = {}
    message = str((payload or {}).get("message") or (payload or {}).get("error") or "").strip()
    return message.lower().replace(" ", "_") or f"http_{getattr(response, 'status_code', 'unknown')}"


def exchange_device_code(device_code, role=BOT_AUTH_ROLE, request_func=None):
    normalized_role = normalize_role(role)
    post = request_func or requests.post
    response = post(
        TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "scopes": " ".join(get_role_scopes(normalized_role)),
            "device_code": str(device_code or ""),
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
        timeout=20,
    )
    if response.status_code >= 400:
        code = twitch_error_code(response)
        return {"ok": False, "error": code, "status_code": response.status_code}
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("access_token"):
        return {"ok": False, "error": "malformed_token_response", "status_code": response.status_code}
    payload["ok"] = True
    payload["status_code"] = response.status_code
    return payload


def refresh_access_token(refresh_token, request_func=None):
    token = str(refresh_token or "").strip()
    if not token:
        raise ValueError("Refresh token is missing.")
    post = request_func or requests.post
    response = post(
        TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "refresh_token": token,
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("access_token") or not payload.get("refresh_token"):
        raise ValueError("Twitch refresh response did not include a complete token pair.")
    return payload


def refresh_role_token(role=BOT_AUTH_ROLE, request_func=None):
    normalized_role = normalize_role(role)
    with _refresh_lock:
        current = _refresh_inflight.get(normalized_role)
        if current is None:
            current = {"event": threading.Event(), "result": None, "error": None}
            _refresh_inflight[normalized_role] = current
            owner = True
        else:
            owner = False

    if not owner:
        current["event"].wait(30)
        if current.get("error"):
            raise current["error"]
        return current.get("result")

    try:
        if is_role_explicitly_disconnected(normalized_role):
            raise ValueError("Reconnect required. Role is disconnected.")
        details = load_token_details(normalized_role)
        refresh_token = details.get("refresh_token")
        if not refresh_token:
            raise ValueError("Reconnect required. No refresh token is available.")
        token_payload = refresh_access_token(refresh_token, request_func=request_func)
        validation = validate_token(token_payload["access_token"])
        if is_role_explicitly_disconnected(normalized_role):
            raise ValueError("Reconnect required. Role disconnected during refresh.")
        set_role_auth_runtime_state(normalized_role, "refreshing", "Refreshing Twitch token")
        result = _save_token_payload(token_payload, role=normalized_role, source="refresh", validation_details=validation)
        current["result"] = result
        auth_diagnostics(f"{get_role_label(normalized_role)} token refreshed and rotated successfully")
        return result
    except Exception as exc:
        current["error"] = exc
        auth_diagnostics(f"{get_role_label(normalized_role)} token refresh failed: {exc.__class__.__name__}")
        raise
    finally:
        current["event"].set()
        with _refresh_lock:
            if _refresh_inflight.get(normalized_role) is current:
                _refresh_inflight.pop(normalized_role, None)


def load_token_details(role: str = BOT_AUTH_ROLE):
    normalized_role = normalize_role(role)
    token_file = get_token_file(normalized_role)
    if is_role_explicitly_disconnected(normalized_role):
        metadata = load_json(token_file, {})
        return {
            "access_token": "",
            "refresh_token": "",
            "token_type": "bearer",
            "saved_at": "",
            "source": "",
            "role": normalized_role,
            "login": (metadata or {}).get("login", "") if isinstance(metadata, dict) else "",
            "display_name": (metadata or {}).get("display_name", "") if isinstance(metadata, dict) else "",
            "user_id": "",
            "client_id": "",
            "scopes": [],
            "expires_in": 0,
            "expires_at": "",
            "last_validated_at": "",
            "profile_image_url": "",
            "redirect_uri": REDIRECT_URI,
            "path": str(token_file),
            "secure_path": str(get_secure_token_file(normalized_role)),
            "secure_storage": "",
            "token_schema_version": TOKEN_SCHEMA_VERSION,
            "exists": False,
            "auth_state": "disconnected",
        }
    migrate_legacy_token_if_needed(normalized_role)
    metadata = load_json(token_file, {})
    data = _combine_metadata_and_secret(normalized_role, metadata)
    if _metadata_has_plaintext_secret(metadata) and not _has_secure_access_token(normalized_role):
        data = _without_plaintext_secret(data)
    return {
        "access_token": data.get("access_token"),
        "refresh_token": data.get("refresh_token", ""),
        "token_type": data.get("token_type", "bearer"),
        "saved_at": data.get("saved_at", ""),
        "source": data.get("source", ""),
        "role": normalized_role,
        "login": data.get("login", ""),
        "display_name": data.get("display_name", ""),
        "user_id": data.get("user_id", ""),
        "client_id": data.get("client_id", ""),
        "scopes": data.get("scopes", []),
        "expires_in": data.get("expires_in", 0),
        "expires_at": data.get("expires_at", ""),
        "last_validated_at": data.get("last_validated_at", ""),
        "profile_image_url": data.get("profile_image_url", ""),
        "redirect_uri": REDIRECT_URI,
        "path": str(token_file),
        "secure_path": str(get_secure_token_file(normalized_role)),
        "secure_storage": data.get("secure_storage", ""),
        "token_schema_version": data.get("token_schema_version", 1),
        "exists": token_file.exists(),
        "auth_state": get_role_auth_runtime_state(normalized_role).get("state", ""),
    }


def load_token(role: str = BOT_AUTH_ROLE):
    return load_token_details(role).get("access_token")


def load_best_token_details(preferred_roles=(CHANNEL_AUTH_ROLE, BOT_AUTH_ROLE)):
    for role in preferred_roles:
        details = load_token_details(role)
        if details.get("access_token"):
            return details
    return load_token_details(BOT_AUTH_ROLE)


def load_best_token(preferred_roles=(CHANNEL_AUTH_ROLE, BOT_AUTH_ROLE)):
    return load_best_token_details(preferred_roles).get("access_token")


def clear_token(role: str = BOT_AUTH_ROLE):
    normalized_role = normalize_role(role)
    mark_role_disconnected(normalized_role)
    token_file = get_token_file(normalized_role)
    secure_file = get_secure_token_file(normalized_role)
    _safe_unlink_token_file(token_file, event_key=f"{normalized_role}:metadata")
    _safe_unlink_token_file(secure_file, event_key=f"{normalized_role}:secure")
    for legacy_file, _source_label in _legacy_sources_for_role(normalized_role):
        if Path(legacy_file) == Path(token_file):
            continue
        data = load_json(legacy_file, {})
        if isinstance(data, dict) and _metadata_has_plaintext_secret(data):
            _sanitize_legacy_plaintext_file(legacy_file, normalized_role, data)
    auth_diagnostics(
        f"{get_role_label(normalized_role)} disconnected",
        event_key=f"{normalized_role}:disconnected",
        cooldown_seconds=5,
    )

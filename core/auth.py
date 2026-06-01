import webbrowser
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from .app_paths import (
    BOT_TOKEN_FILE,
    CHANNEL_TOKEN_FILE,
    LEGACY_APPDATA_BOT_TOKEN_FILE,
    LEGACY_APPDATA_CHANNEL_TOKEN_FILE,
    LEGACY_TOKEN_FILE,
)
from .app_state import load_json, save_json


CLIENT_ID = "e1t33efjfvvzzcq16kb5xc3uu99lls"
REDIRECT_URI = "https://localhost"
VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
HELIX_USERS_URL = "https://api.twitch.tv/helix/users"

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


def normalize_role(role: str | None):
    return role if role in AUTH_ROLES else BOT_AUTH_ROLE


def get_role_label(role: str | None):
    return ROLE_LABELS[normalize_role(role)]


def get_token_file(role: str | None):
    return TOKEN_FILES[normalize_role(role)]


def get_role_scopes(role: str | None):
    return list(SCOPES_BY_ROLE[normalize_role(role)])


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

    token = data.get("access_token")
    if not isinstance(token, str) or not token.strip():
        return {}

    scopes = data.get("scopes") or []
    if not isinstance(scopes, list):
        scopes = []

    return {
        "access_token": token.strip(),
        "saved_at": data.get("saved_at", ""),
        "source": data.get("source", ""),
        "role": normalize_role(data.get("role")),
        "login": data.get("login", ""),
        "display_name": data.get("display_name", ""),
        "user_id": data.get("user_id", ""),
        "client_id": data.get("client_id", ""),
        "scopes": scopes,
        "expires_in": data.get("expires_in", 0),
        "profile_image_url": data.get("profile_image_url", ""),
    }


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


def migrate_legacy_token_if_needed():
    migrations = (
        (BOT_TOKEN_FILE, LEGACY_APPDATA_BOT_TOKEN_FILE, BOT_AUTH_ROLE),
        (CHANNEL_TOKEN_FILE, LEGACY_APPDATA_CHANNEL_TOKEN_FILE, CHANNEL_AUTH_ROLE),
        (BOT_TOKEN_FILE, LEGACY_TOKEN_FILE, BOT_AUTH_ROLE),
    )

    for target_file, legacy_file, role in migrations:
        if target_file.exists() or not legacy_file.exists():
            continue

        data = _normalize_token_data(load_json(legacy_file, {}))
        if not data:
            continue

        target_file.parent.mkdir(parents=True, exist_ok=True)
        data["role"] = role
        save_json(target_file, data)


def save_token(token: str, role: str = BOT_AUTH_ROLE, source: str = "manual", validation_details=None):
    normalized_role = normalize_role(role)
    token = (token or "").strip()
    if not token:
        raise ValueError("Token is empty")

    validation = validation_details or validate_token(token)
    granted_scopes = validation.get("scopes") or []
    required_scopes = get_role_scopes(normalized_role)
    missing_scopes = [scope for scope in required_scopes if scope not in granted_scopes]
    if missing_scopes:
        readable = ", ".join(missing_scopes)
        raise ValueError(f"Missing required Twitch scopes for {get_role_label(normalized_role)}: {readable}")

    profile = {}
    try:
        profile = fetch_user_profile(
            token,
            validation.get("client_id", "") or CLIENT_ID,
            validation.get("user_id", ""),
        )
    except Exception:
        profile = {}

    token_file = get_token_file(normalized_role)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "access_token": token,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "role": normalized_role,
        "login": profile.get("login") or validation.get("login", ""),
        "display_name": profile.get("display_name", ""),
        "user_id": validation.get("user_id", ""),
        "client_id": validation.get("client_id", ""),
        "scopes": granted_scopes,
        "expires_in": validation.get("expires_in", 0),
        "profile_image_url": profile.get("profile_image_url", ""),
    }
    save_json(token_file, payload)

    verified = _normalize_token_data(load_json(token_file, {}))
    if verified.get("access_token") != token:
        raise RuntimeError("Token verification failed after saving")
    return verified


def load_token_details(role: str = BOT_AUTH_ROLE):
    migrate_legacy_token_if_needed()
    normalized_role = normalize_role(role)
    token_file = get_token_file(normalized_role)
    data = _normalize_token_data(load_json(token_file, {}))
    return {
        "access_token": data.get("access_token"),
        "saved_at": data.get("saved_at", ""),
        "source": data.get("source", ""),
        "role": normalized_role,
        "login": data.get("login", ""),
        "display_name": data.get("display_name", ""),
        "user_id": data.get("user_id", ""),
        "client_id": data.get("client_id", ""),
        "scopes": data.get("scopes", []),
        "expires_in": data.get("expires_in", 0),
        "profile_image_url": data.get("profile_image_url", ""),
        "redirect_uri": REDIRECT_URI,
        "path": str(token_file),
        "exists": token_file.exists(),
    }


def load_token(role: str = BOT_AUTH_ROLE):
    return load_token_details(role).get("access_token")


def load_best_token_details(preferred_roles=(CHANNEL_AUTH_ROLE, BOT_AUTH_ROLE)):
    migrate_legacy_token_if_needed()
    for role in preferred_roles:
        details = load_token_details(role)
        if details.get("access_token"):
            return details
    return load_token_details(BOT_AUTH_ROLE)


def load_best_token(preferred_roles=(CHANNEL_AUTH_ROLE, BOT_AUTH_ROLE)):
    return load_best_token_details(preferred_roles).get("access_token")


def clear_token(role: str = BOT_AUTH_ROLE):
    token_file = get_token_file(role)
    if token_file.exists():
        token_file.unlink()

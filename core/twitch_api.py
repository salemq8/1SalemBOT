import requests


HELIX_BASE = "https://api.twitch.tv/helix"
REQUEST_TIMEOUT = 15


def get_headers(client_id: str, access_token: str, include_json=False):
    headers = {
        "Client-Id": client_id,
        "Authorization": f"Bearer {access_token}",
    }
    if include_json:
        headers["Content-Type"] = "application/json"
    return headers


def get_user_by_login(client_id: str, access_token: str, login_name: str):
    response = requests.get(
        f"{HELIX_BASE}/users",
        headers=get_headers(client_id, access_token),
        params={"login": login_name},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json().get("data", [])
    return data[0] if data else None


def get_users_by_logins(client_id: str, access_token: str, login_names):
    collected = {}
    logins = [str(login).strip() for login in list(login_names or []) if str(login).strip()]
    for start in range(0, len(logins), 100):
        batch = logins[start : start + 100]
        if not batch:
            continue
        params = [("login", login_name) for login_name in batch]
        response = requests.get(
            f"{HELIX_BASE}/users",
            headers=get_headers(client_id, access_token),
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        for item in response.json().get("data", []):
            login_name = str(item.get("login", "")).strip().lower()
            if login_name:
                collected[login_name] = item
    return collected


def send_chat_message(client_id: str, access_token: str, broadcaster_id: str, sender_id: str, message: str):
    payload = {
        "broadcaster_id": broadcaster_id,
        "sender_id": sender_id,
        "message": message,
    }
    response = requests.post(
        f"{HELIX_BASE}/chat/messages",
        headers=get_headers(client_id, access_token, include_json=True),
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def get_global_chat_badges(client_id: str, access_token: str):
    response = requests.get(
        f"{HELIX_BASE}/chat/badges/global",
        headers=get_headers(client_id, access_token),
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json().get("data", [])


def get_channel_chat_badges(client_id: str, access_token: str, broadcaster_id: str):
    response = requests.get(
        f"{HELIX_BASE}/chat/badges",
        headers=get_headers(client_id, access_token),
        params={"broadcaster_id": broadcaster_id},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json().get("data", [])


def get_stream_by_user_login(client_id: str, access_token: str, login_name: str):
    response = requests.get(
        f"{HELIX_BASE}/streams",
        headers=get_headers(client_id, access_token),
        params={"user_login": login_name},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json().get("data", [])
    return data[0] if data else None


def _paginate(endpoint: str, headers: dict, params: dict | None = None):
    collected = []
    cursor = None
    base_params = dict(params or {})
    while True:
        query = dict(base_params)
        query.setdefault("first", 100)
        if cursor:
            query["after"] = cursor

        response = requests.get(endpoint, headers=headers, params=query, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        collected.extend(payload.get("data", []))
        cursor = (payload.get("pagination") or {}).get("cursor")
        if not cursor:
            return collected


def get_all_channel_followers(client_id: str, access_token: str, broadcaster_id: str):
    return _paginate(
        f"{HELIX_BASE}/channels/followers",
        get_headers(client_id, access_token),
        {"broadcaster_id": broadcaster_id},
    )


def get_all_broadcaster_subscriptions(client_id: str, access_token: str, broadcaster_id: str):
    return _paginate(
        f"{HELIX_BASE}/subscriptions",
        get_headers(client_id, access_token),
        {"broadcaster_id": broadcaster_id},
    )


def get_all_followed_channels(client_id: str, access_token: str, user_id: str):
    return _paginate(
        f"{HELIX_BASE}/channels/followed",
        get_headers(client_id, access_token),
        {"user_id": user_id},
    )


def is_user_moderator(client_id: str, access_token: str, broadcaster_id: str, user_id: str):
    response = requests.get(
        f"{HELIX_BASE}/moderation/moderators",
        headers=get_headers(client_id, access_token),
        params={
            "broadcaster_id": broadcaster_id,
            "user_id": user_id,
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return bool(response.json().get("data", []))


def get_users_by_ids(client_id: str, access_token: str, user_ids):
    collected = {}
    ids = [str(user_id).strip() for user_id in list(user_ids or []) if str(user_id).strip()]
    for start in range(0, len(ids), 100):
        batch = ids[start : start + 100]
        if not batch:
            continue
        params = [("id", user_id) for user_id in batch]
        response = requests.get(
            f"{HELIX_BASE}/users",
            headers=get_headers(client_id, access_token),
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        for item in response.json().get("data", []):
            user_id = str(item.get("id", "")).strip()
            if user_id:
                collected[user_id] = item
    return collected

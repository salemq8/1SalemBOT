from datetime import datetime, timedelta, timezone

from .app_state import default_alerts_state, load_json, save_json


ALERT_EVENT_LIMIT = 50

ALERT_EVENT_SCOPE_REQUIREMENTS = {
    "channel.follow": ["moderator:read:followers"],
    "channel.subscribe": ["channel:read:subscriptions"],
    "channel.subscription.gift": ["channel:read:subscriptions"],
    "channel.raid": [],
    "channel.cheer": ["bits:read"],
    "channel.channel_points_custom_reward_redemption.add": ["channel:read:redemptions"],
    "channel.poll.begin": ["channel:read:polls"],
    "channel.poll.progress": ["channel:read:polls"],
    "channel.poll.end": ["channel:read:polls"],
    "channel.prediction.begin": ["channel:read:predictions"],
    "channel.prediction.progress": ["channel:read:predictions"],
    "channel.prediction.lock": ["channel:read:predictions"],
    "channel.prediction.end": ["channel:read:predictions"],
    "channel.hype_train.begin": ["channel:read:hype_train"],
    "channel.hype_train.progress": ["channel:read:hype_train"],
    "channel.hype_train.end": ["channel:read:hype_train"],
    "channel.shoutout.create": ["moderator:read:shoutouts"],
    "channel.shoutout.receive": ["moderator:read:shoutouts"],
}

ALERT_FILTER_SCOPE_REQUIREMENTS = {
    "Followers": ["moderator:read:followers"],
    "Subs": ["channel:read:subscriptions"],
    "Gifted Subs": ["channel:read:subscriptions"],
    "Bits": ["bits:read"],
    "Polls": ["channel:read:polls"],
    "Predictions": ["channel:read:predictions"],
    "Reward Requests": ["channel:read:redemptions"],
    "Shoutouts": ["moderator:read:shoutouts"],
    "Hype Train": ["channel:read:hype_train"],
}

ALERT_TONE_MAP = {
    "Followers": "info",
    "Subs": "success",
    "Gifted Subs": "success",
    "Raids": "primary",
    "Bits": "primary",
    "Clips": "info",
    "Hype Train": "warning",
    "Polls": "info",
    "Predictions": "primary",
    "Reward Requests": "warning",
    "Shoutouts": "info",
    "Watch Streaks": "success",
    "Collaboration Requests": "warning",
}

ALERT_ICON_MAP = {
    "Followers": "heart",
    "Subs": "star",
    "Gifted Subs": "gift",
    "Raids": "raid",
    "Bits": "diamond",
    "Clips": "clapper",
    "Hype Train": "flame",
    "Polls": "chart",
    "Predictions": "trophy",
    "Reward Requests": "reward",
    "Shoutouts": "megaphone",
    "Watch Streaks": "lightning",
    "Collaboration Requests": "users",
    "Charity Donations": "charity",
    "Goals": "goal",
}

EVENT_TYPE_ALERT_MAP = {
    "channel.follow": ("Followers", "heart", "info"),
    "channel.subscribe": ("Subs", "star", "success"),
    "channel.subscription.gift": ("Gifted Subs", "gift", "success"),
    "channel.raid": ("Raids", "raid", "primary"),
    "channel.cheer": ("Bits", "diamond", "primary"),
    "channel.channel_points_custom_reward_redemption.add": ("Reward Requests", "reward", "warning"),
    "channel.shoutout.create": ("Shoutouts", "megaphone", "info"),
    "channel.shoutout.receive": ("Shoutouts", "megaphone", "info"),
}

ALERT_BADGE_COLOR_MAP = {
    "Followers": ("rgba(235, 4, 108, 0.16)", "#EB046C", "rgba(235, 4, 108, 0.34)"),
    "Subs": ("rgba(255, 202, 64, 0.17)", "#FFCA40", "rgba(255, 202, 64, 0.36)"),
    "Gifted Subs": ("rgba(255, 165, 54, 0.18)", "#FFA536", "rgba(255, 165, 54, 0.36)"),
    "Raids": ("rgba(145, 71, 255, 0.18)", "#9147FF", "rgba(145, 71, 255, 0.42)"),
    "Bits": ("rgba(0, 191, 255, 0.18)", "#00BFFF", "rgba(0, 191, 255, 0.38)"),
    "Clips": ("rgba(29, 185, 84, 0.16)", "#1DB954", "rgba(29, 185, 84, 0.34)"),
    "Hype Train": ("rgba(255, 117, 64, 0.18)", "#FF7540", "rgba(255, 117, 64, 0.36)"),
    "Polls": ("rgba(57, 255, 20, 0.14)", "#39FF14", "rgba(57, 255, 20, 0.30)"),
    "Predictions": ("rgba(25, 215, 224, 0.16)", "#19D7E0", "rgba(25, 215, 224, 0.34)"),
    "Reward Requests": ("rgba(255, 202, 64, 0.17)", "#FFCA40", "rgba(255, 202, 64, 0.36)"),
    "Shoutouts": ("rgba(145, 71, 255, 0.16)", "#BF94FF", "rgba(145, 71, 255, 0.36)"),
    "Watch Streaks": ("rgba(39, 240, 255, 0.16)", "#27F0FF", "rgba(39, 240, 255, 0.34)"),
    "Collaboration Requests": ("rgba(0, 191, 255, 0.15)", "#8BE9FD", "rgba(0, 191, 255, 0.32)"),
    "Charity Donations": ("rgba(235, 4, 108, 0.16)", "#FF6EA8", "rgba(235, 4, 108, 0.34)"),
    "Goals": ("rgba(57, 255, 20, 0.14)", "#39FF14", "rgba(57, 255, 20, 0.30)"),
}

GENERIC_ALERT_BADGE_COLORS = ("rgba(148, 163, 184, 0.14)", "#94A3B8", "rgba(148, 163, 184, 0.30)")
LEGACY_PLACEHOLDER_ICONS = {"!", "f", "r", "s", "g", "b", "c", "h", "p", "w"}


def resolve_alert_type(event_type="", alert_type=""):
    event_type = str(event_type or "").strip()
    alert_type = str(alert_type or "").strip()
    if event_type in EVENT_TYPE_ALERT_MAP:
        return EVENT_TYPE_ALERT_MAP[event_type][0]
    if event_type.startswith("channel.poll."):
        return "Polls"
    if event_type.startswith("channel.prediction."):
        return "Predictions"
    if event_type.startswith("channel.hype_train."):
        return "Hype Train"
    if "clip" in event_type:
        return "Clips"
    if "watch_streak" in event_type or "watch-streak" in event_type:
        return "Watch Streaks"
    if "collaboration" in event_type:
        return "Collaboration Requests"
    return alert_type or "Alert"


def get_alert_icon_name(item):
    if not isinstance(item, dict):
        return "bell"
    event_type = str(item.get("event_type") or item.get("eventType") or "").strip()
    alert_type = resolve_alert_type(event_type, item.get("type"))
    if event_type in EVENT_TYPE_ALERT_MAP:
        return EVENT_TYPE_ALERT_MAP[event_type][1]
    if event_type.startswith("channel.poll."):
        return "chart"
    if event_type.startswith("channel.prediction."):
        return "trophy"
    if event_type.startswith("channel.hype_train."):
        return "flame"
    if "clip" in event_type:
        return "clapper"
    if "watch_streak" in event_type or "watch-streak" in event_type:
        return "lightning"
    if "collaboration" in event_type:
        return "users"

    icon_name = str(item.get("icon") or "").strip().lower()
    if icon_name and icon_name not in LEGACY_PLACEHOLDER_ICONS and alert_type not in ALERT_ICON_MAP:
        return icon_name
    return ALERT_ICON_MAP.get(alert_type, "bell")


def get_alert_tone(item):
    if not isinstance(item, dict):
        return "info"
    event_type = str(item.get("event_type") or item.get("eventType") or "").strip()
    alert_type = resolve_alert_type(event_type, item.get("type"))
    if event_type in EVENT_TYPE_ALERT_MAP:
        return EVENT_TYPE_ALERT_MAP[event_type][2]
    return ALERT_TONE_MAP.get(alert_type, "info")


def get_alert_badge_colors(item):
    if not isinstance(item, dict):
        return GENERIC_ALERT_BADGE_COLORS
    event_type = str(item.get("event_type") or item.get("eventType") or "").strip()
    alert_type = resolve_alert_type(event_type, item.get("type"))
    return ALERT_BADGE_COLOR_MAP.get(alert_type, GENERIC_ALERT_BADGE_COLORS)


def missing_alert_scopes(granted_scopes, required_scopes):
    granted = set(granted_scopes or [])
    return [scope for scope in required_scopes if scope not in granted]


def alert_filter_required_scopes(alert_filter):
    if alert_filter == "All":
        required = []
        for scopes in ALERT_FILTER_SCOPE_REQUIREMENTS.values():
            for scope in scopes:
                if scope not in required:
                    required.append(scope)
        return required
    return list(ALERT_FILTER_SCOPE_REQUIREMENTS.get(alert_filter, []))


def parse_alert_datetime(raw_value):
    value = str(raw_value or "").strip()
    if not value:
        return None

    for candidate in (
        value,
        value.replace("Z", "+00:00"),
        value.replace(" ", "T"),
    ):
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            continue

    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def format_alert_time_ago(raw_value, now=None):
    parsed = parse_alert_datetime(raw_value)
    if parsed is None:
        return "Unknown time"

    current = now or datetime.now(timezone.utc)
    delta = current - parsed
    total_seconds = max(int(delta.total_seconds()), 0)
    if total_seconds < 30:
        return "just now"
    if total_seconds < 3600:
        minutes = total_seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    if total_seconds < 86400:
        hours = total_seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    if total_seconds < 172800:
        return "yesterday"
    days = total_seconds // 86400
    return f"{days} days ago"


def normalize_alert_item(item):
    if not isinstance(item, dict):
        return None
    event_type = str(item.get("event_type") or item.get("eventType") or "").strip()
    alert_type = resolve_alert_type(event_type, item.get("type"))
    username = str(item.get("username") or item.get("user_login") or item.get("user_name") or "Unknown").strip() or "Unknown"
    occurred_at = str(item.get("occurred_at") or item.get("timestamp") or "").strip()
    if not occurred_at:
        return None
    normalized = {
        "id": str(item.get("id") or f"{event_type or alert_type}:{username}:{occurred_at}:{item.get('text','')}").strip(),
        "event_type": event_type,
        "type": alert_type,
        "username": username,
        "text": str(item.get("text") or "").strip(),
        "occurred_at": occurred_at,
        "timestamp": occurred_at,
        "icon": get_alert_icon_name({"event_type": event_type, "type": alert_type, "icon": item.get("icon")}),
        "tone": get_alert_tone({"event_type": event_type, "type": alert_type}),
        "details": item.get("details") if isinstance(item.get("details"), dict) else {},
        "source": str(item.get("source") or "stored").strip(),
    }
    if not normalized["event_type"]:
        normalized.pop("event_type")
    return normalized


def alert_dedupe_key(item):
    event_type = str(item.get("event_type") or "").strip()
    alert_type = str(item.get("type") or "").strip()
    username = str(item.get("username") or "").strip().casefold()
    occurred_at = str(item.get("occurred_at") or "").strip()
    if alert_type == "Followers":
        return ("follower", username, occurred_at)
    return {
        "id": str(item.get("id") or ""),
        "event_type": event_type,
        "type": alert_type,
        "username": username,
        "text": str(item.get("text") or "").strip(),
        "occurred_at": occurred_at,
    }.get("id") or (event_type or alert_type, username, occurred_at, str(item.get("text") or "").strip())


def sort_alert_items(items):
    def key(item):
        parsed = parse_alert_datetime(item.get("occurred_at"))
        return parsed or datetime.min.replace(tzinfo=timezone.utc)

    return sorted((item for item in items if item), key=key, reverse=True)


def dedupe_alert_items(items):
    deduped = {}
    for item in items:
        normalized = normalize_alert_item(item)
        if normalized is None:
            continue
        deduped[alert_dedupe_key(normalized)] = normalized
    return sort_alert_items(deduped.values())[:ALERT_EVENT_LIMIT]


def load_alert_items(alerts_file):
    return dedupe_alert_items(load_json(alerts_file, default_alerts_state()))


def save_alert_items(alerts_file, items):
    save_json(alerts_file, dedupe_alert_items(items))


def add_alert_items(alerts_file, new_items):
    existing = load_alert_items(alerts_file)
    combined = existing + list(new_items or [])
    save_alert_items(alerts_file, combined)
    return load_alert_items(alerts_file)


def load_alert_status(status_file):
    status = load_json(status_file, {"listener": {}, "subscriptions": {}, "updated_at": ""})
    if not isinstance(status, dict):
        return {"listener": {}, "subscriptions": {}, "updated_at": ""}
    if not isinstance(status.get("listener"), dict):
        status["listener"] = {}
    if not isinstance(status.get("subscriptions"), dict):
        status["subscriptions"] = {}
    status.setdefault("updated_at", "")
    return status


def update_alert_subscription_status(status_file, subscription_type, **fields):
    status = load_alert_status(status_file)
    subscription_type = str(subscription_type or "").strip()
    if not subscription_type:
        return status
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    entry = dict(status["subscriptions"].get(subscription_type, {}))
    entry.update(fields)
    entry["event_type"] = subscription_type
    entry["updated_at"] = now
    status["subscriptions"][subscription_type] = entry
    status["updated_at"] = now
    save_json(status_file, status)
    return status


def update_alert_listener_status(status_file, state, message="", **fields):
    status = load_alert_status(status_file)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    listener = dict(status.get("listener") or {})
    listener.update(fields)
    listener["state"] = str(state or "").strip()
    listener["message"] = str(message or "").strip()
    listener["updated_at"] = now
    status["listener"] = listener
    status["updated_at"] = now
    save_json(status_file, status)
    return status


def make_alert_item(alert_type, username, text, occurred_at, *, source="api", icon=None, tone=None, event_type=None, details=None):
    resolved_type = resolve_alert_type(event_type, alert_type)
    return normalize_alert_item(
        {
            "id": f"{event_type or resolved_type}:{username}:{occurred_at}:{text}",
            "event_type": event_type or "",
            "type": resolved_type,
            "username": username,
            "text": text,
            "occurred_at": occurred_at,
            "timestamp": occurred_at,
            "icon": icon,
            "tone": tone,
            "details": details if isinstance(details, dict) else {},
            "source": source,
        }
    )


def derive_historical_alerts_from_relationships(state):
    alerts = []
    for item in list((state or {}).get("followers_snapshot", []) or []):
        occurred_at = str(item.get("followed_at") or "").strip()
        username = item.get("user_name") or item.get("user_login") or "Unknown"
        if occurred_at:
            alerts.append(make_alert_item("Followers", username, "Followed you", occurred_at, source="historical", event_type="channel.follow"))

    for item in list((state or {}).get("subscriptions_snapshot", []) or []):
        occurred_at = str(item.get("added_at") or item.get("subscribed_at") or "").strip()
        username = item.get("user_name") or item.get("user_login") or "Unknown"
        if not occurred_at:
            continue
        if item.get("is_gift"):
            gifted_count = int(item.get("gift_count") or 1)
            text = f"Gifted {gifted_count} sub{'s' if gifted_count != 1 else ''} to your community"
            alerts.append(make_alert_item("Gifted Subs", username, text, occurred_at, source="historical", event_type="channel.subscription.gift"))
        else:
            alerts.append(make_alert_item("Subs", username, "Subscribed", occurred_at, source="historical", event_type="channel.subscribe"))

    return dedupe_alert_items(alerts)


def build_new_follower_alerts(previous_items, current_items):
    previous_ids = {
        str(item.get("user_id") or item.get("user_login") or "").strip()
        for item in list(previous_items or [])
    }
    new_alerts = []
    for item in list(current_items or []):
        item_id = str(item.get("user_id") or item.get("user_login") or "").strip()
        if not item_id or item_id in previous_ids:
            continue
        occurred_at = str(item.get("followed_at") or "").strip()
        if not occurred_at:
            continue
        username = item.get("user_name") or item.get("user_login") or "Unknown"
        new_alerts.append(make_alert_item("Followers", username, "Followed you", occurred_at, source="api", event_type="channel.follow"))
    return new_alerts


def build_new_subscription_alerts(previous_items, current_items, detected_at):
    previous_ids = {
        str(item.get("user_id") or item.get("user_login") or "").strip()
        for item in list(previous_items or [])
    }
    new_alerts = []
    for item in list(current_items or []):
        item_id = str(item.get("user_id") or item.get("user_login") or "").strip()
        if not item_id or item_id in previous_ids:
            continue
        username = item.get("user_name") or item.get("user_login") or "Unknown"
        if item.get("is_gift"):
            gifted_count = int(item.get("gift_count") or 1)
            text = f"Gifted {gifted_count} sub{'s' if gifted_count != 1 else ''} to your community"
            new_alerts.append(make_alert_item("Gifted Subs", username, text, detected_at, source="api", event_type="channel.subscription.gift"))
        else:
            new_alerts.append(make_alert_item("Subs", username, "Subscribed", detected_at, source="api", event_type="channel.subscribe"))
    return new_alerts

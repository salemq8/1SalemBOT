import re
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta

from .app_paths import CHAT_LOG_FILE, DASHBOARD_STATE_FILE, USERS_FILE
from .app_state import DASHBOARD_HISTORY_DAYS, default_dashboard_state, load_json, save_json


CHAT_USER_LINE_RE = re.compile(
    r"^\[(?P<timestamp>[^\]]+)\]\s+PLATFORM=(?P<platform>\S+)\s+USER=(?P<username>\S+)\s+MESSAGE=(?P<message>.*)$"
)
WORD_RE = re.compile(r"[\w\u0600-\u06FF']+", re.UNICODE)
STOP_WORDS = {
    "the",
    "and",
    "for",
    "that",
    "this",
    "with",
    "you",
    "your",
    "are",
    "was",
    "have",
    "just",
    "from",
    "الى",
    "إلى",
    "في",
    "على",
    "من",
    "عن",
    "مع",
    "هذا",
    "ذي",
    "الى",
    "انا",
    "أنت",
    "انت",
    "انه",
    "وش",
    "اللي",
    "الى",
}

_CHAT_ANALYTICS_CACHE_SIGNATURE = None
_CHAT_ANALYTICS_CACHE_PAYLOAD = None


def load_user_profiles():
    return load_json(USERS_FILE, {})


def save_user_profiles(user_profiles):
    save_json(USERS_FILE, user_profiles)


def ensure_dashboard_shape(dashboard_state, days=DASHBOARD_HISTORY_DAYS):
    dashboard_state.setdefault("messages_today", 0)
    dashboard_state.setdefault("commands_used", 0)
    dashboard_state.setdefault("timeouts_today", 0)
    dashboard_state.setdefault("current_day", date.today().isoformat())
    dashboard_state.setdefault("top_chatters", {})
    dashboard_state.setdefault("top_commands", {})
    dashboard_state.setdefault("recent_chat", [])
    dashboard_state.setdefault("last_updated", "")

    raw_history = dashboard_state.get("analytics_history", [])
    history_by_date = {}
    for bucket in raw_history:
        if not isinstance(bucket, dict):
            continue
        bucket_date = bucket.get("date")
        if not bucket_date:
            continue
        history_by_date[bucket_date] = {
            "date": bucket_date,
            "messages": int(bucket.get("messages", 0) or 0),
            "commands": int(bucket.get("commands", 0) or 0),
            "timeouts": int(bucket.get("timeouts", 0) or 0),
        }

    today = date.today()
    normalized_history = []
    for offset in range(days - 1, -1, -1):
        bucket_date = (today - timedelta(days=offset)).isoformat()
        normalized_history.append(
            history_by_date.get(
                bucket_date,
                {
                    "date": bucket_date,
                    "messages": 0,
                    "commands": 0,
                    "timeouts": 0,
                },
            )
        )

    if not raw_history and normalized_history:
        normalized_history[-1]["messages"] = int(dashboard_state.get("messages_today", 0) or 0)
        normalized_history[-1]["commands"] = int(dashboard_state.get("commands_used", 0) or 0)
        normalized_history[-1]["timeouts"] = int(dashboard_state.get("timeouts_today", 0) or 0)

    dashboard_state["analytics_history"] = normalized_history
    return dashboard_state


def _set_bucket_value(history_by_date, bucket_date, *, messages, commands, timeouts):
    history_by_date[bucket_date] = {
        "date": bucket_date,
        "messages": int(messages or 0),
        "commands": int(commands or 0),
        "timeouts": int(timeouts or 0),
    }


def sync_dashboard_day(dashboard_state, days=DASHBOARD_HISTORY_DAYS):
    ensure_dashboard_shape(dashboard_state, days=days)

    today = date.today()
    today_key = today.isoformat()
    stored_day = str(dashboard_state.get("current_day") or today_key)

    history_by_date = {}
    for bucket in dashboard_state.get("analytics_history", []):
        bucket_date = bucket.get("date")
        if not bucket_date:
            continue
        history_by_date[bucket_date] = {
            "date": bucket_date,
            "messages": int(bucket.get("messages", 0) or 0),
            "commands": int(bucket.get("commands", 0) or 0),
            "timeouts": int(bucket.get("timeouts", 0) or 0),
        }

    try:
        stored_date = date.fromisoformat(stored_day)
    except Exception:
        stored_date = today

    if stored_date > today:
        stored_date = today
        stored_day = today_key

    _set_bucket_value(
        history_by_date,
        stored_day,
        messages=dashboard_state.get("messages_today", 0),
        commands=dashboard_state.get("commands_used", 0),
        timeouts=dashboard_state.get("timeouts_today", 0),
    )

    if stored_day != today_key:
        day_cursor = stored_date + timedelta(days=1)
        while day_cursor <= today:
            _set_bucket_value(
                history_by_date,
                day_cursor.isoformat(),
                messages=0,
                commands=0,
                timeouts=0,
            )
            day_cursor += timedelta(days=1)

        dashboard_state["current_day"] = today_key
        dashboard_state["messages_today"] = 0
        dashboard_state["commands_used"] = 0
        dashboard_state["timeouts_today"] = 0
        dashboard_state["top_chatters"] = {}
        dashboard_state["top_commands"] = {}
    else:
        dashboard_state["current_day"] = today_key

    _set_bucket_value(
        history_by_date,
        today_key,
        messages=dashboard_state.get("messages_today", 0),
        commands=dashboard_state.get("commands_used", 0),
        timeouts=dashboard_state.get("timeouts_today", 0),
    )

    normalized_history = []
    for offset in range(days - 1, -1, -1):
        bucket_date = (today - timedelta(days=offset)).isoformat()
        normalized_history.append(
            history_by_date.get(
                bucket_date,
                {
                    "date": bucket_date,
                    "messages": 0,
                    "commands": 0,
                    "timeouts": 0,
                },
            )
        )

    dashboard_state["analytics_history"] = normalized_history
    return dashboard_state


def load_dashboard_state():
    loaded_state = load_json(DASHBOARD_STATE_FILE, default_dashboard_state())
    original_state = deepcopy(loaded_state)
    normalized_state = sync_dashboard_day(loaded_state)
    if normalized_state != original_state:
        save_json(DASHBOARD_STATE_FILE, normalized_state)
    return normalized_state


def save_dashboard_state(dashboard_state):
    sync_dashboard_day(dashboard_state)
    dashboard_state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_json(DASHBOARD_STATE_FILE, dashboard_state)


def record_dashboard_metric(dashboard_state, metric_name, amount=1):
    sync_dashboard_day(dashboard_state)
    metric_key = (metric_name or "").strip().lower()
    if metric_key not in {"messages", "commands", "timeouts"}:
        return

    today_key = date.today().isoformat()
    for bucket in dashboard_state["analytics_history"]:
        if bucket.get("date") == today_key:
            if metric_key == "messages":
                bucket[metric_key] = int(dashboard_state.get("messages_today", 0) or 0)
            elif metric_key == "commands":
                bucket[metric_key] = int(dashboard_state.get("commands_used", 0) or 0)
            else:
                bucket[metric_key] = int(dashboard_state.get("timeouts_today", 0) or 0)
            break


def increment_top_command(dashboard_state, command_name, amount=1):
    ensure_dashboard_shape(dashboard_state)
    key = (command_name or "").strip()
    if not key:
        return
    dashboard_state["top_commands"][key] = dashboard_state["top_commands"].get(key, 0) + amount


def append_recent_chat(
    dashboard_state,
    username,
    text,
    *,
    display_name=None,
    badges=None,
    fragments=None,
    platform="twitch",
):
    dashboard_state["recent_chat"].append(
        {
            "time": datetime.now().strftime("%H:%M:%S"),
            "user": username,
            "display_name": display_name or username,
            "text": text,
            "badges": badges or [],
            "fragments": fragments or [],
            "platform": platform,
        }
    )
    dashboard_state["recent_chat"] = dashboard_state["recent_chat"][-100:]


def log_chat(username, message, reply="", platform="twitch"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with CHAT_LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] PLATFORM={platform} USER={username} MESSAGE={message}\n")
        if reply:
            handle.write(f"[{timestamp}] PLATFORM={platform} BOT={reply}\n")


def read_chat_log_lines():
    if not CHAT_LOG_FILE.exists():
        return []
    return CHAT_LOG_FILE.read_text(encoding="utf-8").splitlines()


def _parse_chat_timestamp(value):
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _chat_log_signature():
    if not CHAT_LOG_FILE.exists():
        return None
    stats = CHAT_LOG_FILE.stat()
    return (stats.st_size, getattr(stats, "st_mtime_ns", int(stats.st_mtime * 1_000_000_000)))


def _build_chat_analytics_cache():
    entries = []
    per_user = {}
    daily_counts = Counter()
    hourly_counts = Counter()
    word_counts = Counter()

    for line in read_chat_log_lines():
        match = CHAT_USER_LINE_RE.match(line.strip())
        if not match:
            continue

        timestamp = _parse_chat_timestamp(match.group("timestamp"))
        if timestamp is None:
            continue

        username = match.group("username").strip()
        message = match.group("message").strip()
        if not username:
            continue

        entry = {
            "timestamp": timestamp,
            "username": username,
            "message": message,
            "date": timestamp.date().isoformat(),
            "hour": timestamp.hour,
        }
        entries.append(entry)
        daily_counts[entry["date"]] += 1
        hourly_counts[entry["hour"]] += 1

        user_stats = per_user.setdefault(
            username,
            {
                "total_messages": 0,
                "messages_today": 0,
                "last_message": "",
                "last_message_time": "",
                "last_message_dt": None,
                "first_seen": "",
                "first_seen_dt": None,
                "daily_counts": Counter(),
                "hourly_counts": Counter(),
            },
        )
        user_stats["total_messages"] += 1
        user_stats["last_message"] = message
        user_stats["last_message_time"] = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        user_stats["last_message_dt"] = timestamp
        user_stats["daily_counts"][entry["date"]] += 1
        user_stats["hourly_counts"][entry["hour"]] += 1
        if user_stats["first_seen_dt"] is None:
            user_stats["first_seen_dt"] = timestamp
            user_stats["first_seen"] = timestamp.strftime("%Y-%m-%d %H:%M:%S")

        if timestamp.date() == date.today():
            user_stats["messages_today"] += 1

        for word in WORD_RE.findall(message.lower()):
            cleaned = word.strip("_'").lower()
            if len(cleaned) < 3:
                continue
            if cleaned.isdigit():
                continue
            if cleaned in STOP_WORDS:
                continue
            if cleaned.startswith("@"):
                continue
            word_counts[cleaned] += 1

    return {
        "entries": entries,
        "per_user": per_user,
        "daily_counts": dict(daily_counts),
        "hourly_counts": dict(hourly_counts),
        "word_counts": word_counts,
        "total_messages": len(entries),
    }


def get_chat_analytics_cache():
    global _CHAT_ANALYTICS_CACHE_SIGNATURE, _CHAT_ANALYTICS_CACHE_PAYLOAD
    signature = _chat_log_signature()
    if signature == _CHAT_ANALYTICS_CACHE_SIGNATURE and _CHAT_ANALYTICS_CACHE_PAYLOAD is not None:
        return _CHAT_ANALYTICS_CACHE_PAYLOAD

    _CHAT_ANALYTICS_CACHE_SIGNATURE = signature
    _CHAT_ANALYTICS_CACHE_PAYLOAD = _build_chat_analytics_cache()
    return _CHAT_ANALYTICS_CACHE_PAYLOAD


def _build_daily_series(counts_by_date, *, days=7):
    labels = []
    tooltip_labels = []
    values = []
    today = date.today()
    for offset in range(days - 1, -1, -1):
        bucket_date = today - timedelta(days=offset)
        key = bucket_date.isoformat()
        labels.append(bucket_date.strftime("%a"))
        tooltip_labels.append(bucket_date.strftime("%A, %d %b"))
        values.append(int(counts_by_date.get(key, 0) or 0))
    return labels, tooltip_labels, values


def get_dashboard_analytics_snapshot(*, session_started_at=None, days=7):
    cache = get_chat_analytics_cache()
    entries = cache["entries"]
    total_messages = int(cache.get("total_messages", 0) or 0)
    session_messages = 0
    if session_started_at is not None:
        session_messages = sum(1 for entry in entries if entry["timestamp"] >= session_started_at)
    else:
        session_messages = total_messages

    session_minutes = 0.0
    if session_started_at is not None:
        session_minutes = max((datetime.now() - session_started_at).total_seconds() / 60.0, 0.0)
    average_per_minute = (session_messages / session_minutes) if session_minutes > 0 else 0.0

    peak_hour = None
    peak_count = 0
    if cache["hourly_counts"]:
        peak_hour, peak_count = max(cache["hourly_counts"].items(), key=lambda item: item[1])

    labels, tooltip_labels, last_days_messages = _build_daily_series(cache["daily_counts"], days=days)
    top_words = cache["word_counts"].most_common(8)

    return {
        "total_messages": total_messages,
        "session_messages": session_messages,
        "average_messages_per_minute": average_per_minute,
        "peak_hour": peak_hour,
        "peak_hour_messages": peak_count,
        "labels": labels,
        "tooltip_labels": tooltip_labels,
        "daily_messages": last_days_messages,
        "top_words": top_words,
    }


def get_viewer_analytics_snapshot(username, *, session_started_at=None, days=7):
    cache = get_chat_analytics_cache()
    user_stats = cache["per_user"].get(username, {})
    if not user_stats:
        labels, tooltip_labels, values = _build_daily_series({}, days=days)
        return {
            "total_messages": 0,
            "messages_today": 0,
            "messages_this_session": 0,
            "last_message": "",
            "last_message_time": "",
            "first_seen": "",
            "labels": labels,
            "tooltip_labels": tooltip_labels,
            "activity_values": values,
        }

    session_messages = 0
    if session_started_at is not None:
        session_messages = sum(
            1
            for entry in cache["entries"]
            if entry["username"] == username and entry["timestamp"] >= session_started_at
        )
    else:
        session_messages = int(user_stats.get("total_messages", 0) or 0)

    labels, tooltip_labels, values = _build_daily_series(user_stats.get("daily_counts", {}), days=days)
    return {
        "total_messages": int(user_stats.get("total_messages", 0) or 0),
        "messages_today": int(user_stats.get("messages_today", 0) or 0),
        "messages_this_session": int(session_messages or 0),
        "last_message": user_stats.get("last_message", ""),
        "last_message_time": user_stats.get("last_message_time", ""),
        "first_seen": user_stats.get("first_seen", ""),
        "labels": labels,
        "tooltip_labels": tooltip_labels,
        "activity_values": values,
    }


def get_recent_user_messages(username, limit=8):
    user_lines = []
    for line in reversed(read_chat_log_lines()):
        is_user_line = f"USER={username} " in line
        is_bot_line = "] PLATFORM=" in line and " BOT=" in line
        if is_user_line or is_bot_line:
            user_lines.append(line.strip())
        if len(user_lines) >= limit * 2:
            break
    user_lines.reverse()
    return user_lines


def get_recent_user_only_messages(username, limit=12):
    messages = []
    for line in reversed(read_chat_log_lines()):
        if f"USER={username} " in line:
            messages.append(line.split("MESSAGE=", 1)[-1].strip())
        if len(messages) >= limit:
            break
    messages.reverse()
    return messages


def get_user_profile(user_profiles, username):
    return user_profiles.get(
        username,
        {
            "messages": 0,
            "last_seen": "",
            "behavior": "neutral",
            "notes": "not enough information yet",
            "last_message": "",
            "muted": False,
            "manual_role": "",
        },
    )

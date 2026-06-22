import os
import re
import sys
import time
import traceback
from datetime import datetime

from openai import OpenAI

from .alert_storage import (
    ALERT_EVENT_SCOPE_REQUIREMENTS,
    add_alert_items,
    make_alert_item,
    missing_alert_scopes,
    update_alert_subscription_status,
)
from .app_paths import ALERTS_FILE, ALERT_STATUS_FILE, CHAT_LOG_FILE, DASHBOARD_STATE_FILE, MUSIC_COMMAND_FILE, MUSIC_QUEUE_STATE_FILE, SETTINGS_FILE, USERS_FILE
from .app_state import DEFAULT_PROMPT, DEFAULT_TRIGGERS, build_runtime_system_prompt, default_alerts_state, ensure_app_files, load_json
from .auth import BOT_AUTH_ROLE, CHANNEL_AUTH_ROLE, CLIENT_ID, load_token_details, validate_token
from .bot_runtime import touch_bot_runtime_state
from .bot_messages import (
    AI_ERROR_REPLY,
    MENTION_REPLY,
    MUSIC_DISABLED_REPLY,
    MUSIC_NEEDS_QUERY_REPLY,
    MUSIC_QUEUED_REPLY,
    MUSIC_SKIPPED_REPLY,
    MUSIC_STOPPED_REPLY,
    mention_user,
)
from .chat_persistence import ChatPersistenceManager, persistence_update_lock
from .chat_storage import (
    append_recent_chat,
    get_recent_user_messages,
    get_recent_user_only_messages,
    get_user_profile,
    increment_top_command,
    load_dashboard_state,
    load_user_profiles,
    log_chat,
    record_dashboard_metric,
    save_dashboard_state,
    save_user_profiles,
    sync_dashboard_day,
)
from .music_commands import (
    looks_like_implicit_music_text,
    parse_bot_addressed_music_request,
    parse_music_command,
    parse_natural_music_command,
    write_music_command,
)
from .runtime_env import configure_ssl_cert_env
from .twitch_api import get_user_by_login, is_user_moderator, send_chat_message
from .twitch_eventsub import TwitchEventSubClient

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


LISTENERS = []
ALERT_SCOPE_REQUIREMENTS = ALERT_EVENT_SCOPE_REQUIREMENTS
MAX_VIEWER_MESSAGE_DEDUPE_IDS = 5000
BOT_RUNTIME_HEARTBEAT_SECONDS = 30
BOT_EVENTSUB_STALE_SECONDS = 90


def safe_print(*args):
    text = " ".join(str(argument) for argument in args)
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        cleaned = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
        print(cleaned, flush=True)


def iso_or_fallback(event, metadata, *keys):
    for key in keys:
        value = str(event.get(key, "")).strip()
        if value:
            return value
    return str((metadata or {}).get("message_timestamp", "")).strip()


def build_alert_subscription_requests(channel_user_id):
    return [
        {
            "label": "Followers",
            "type": "channel.follow",
            "version": "2",
            "condition": {
                "broadcaster_user_id": channel_user_id,
                "moderator_user_id": channel_user_id,
            },
        },
        {"label": "Subs", "type": "channel.subscribe", "version": "1", "condition": {"broadcaster_user_id": channel_user_id}},
        {"label": "Gifted Subs", "type": "channel.subscription.gift", "version": "1", "condition": {"broadcaster_user_id": channel_user_id}},
        {"label": "Raids", "type": "channel.raid", "version": "1", "condition": {"to_broadcaster_user_id": channel_user_id}},
        {"label": "Bits", "type": "channel.cheer", "version": "1", "condition": {"broadcaster_user_id": channel_user_id}},
        {
            "label": "Reward Requests",
            "type": "channel.channel_points_custom_reward_redemption.add",
            "version": "1",
            "condition": {"broadcaster_user_id": channel_user_id},
        },
        {"label": "Polls Begin", "type": "channel.poll.begin", "version": "1", "condition": {"broadcaster_user_id": channel_user_id}},
        {"label": "Polls Progress", "type": "channel.poll.progress", "version": "1", "condition": {"broadcaster_user_id": channel_user_id}},
        {"label": "Polls End", "type": "channel.poll.end", "version": "1", "condition": {"broadcaster_user_id": channel_user_id}},
        {
            "label": "Predictions Begin",
            "type": "channel.prediction.begin",
            "version": "1",
            "condition": {"broadcaster_user_id": channel_user_id},
        },
        {
            "label": "Predictions Progress",
            "type": "channel.prediction.progress",
            "version": "1",
            "condition": {"broadcaster_user_id": channel_user_id},
        },
        {
            "label": "Predictions Lock",
            "type": "channel.prediction.lock",
            "version": "1",
            "condition": {"broadcaster_user_id": channel_user_id},
        },
        {"label": "Predictions End", "type": "channel.prediction.end", "version": "1", "condition": {"broadcaster_user_id": channel_user_id}},
        {"label": "Hype Train Begin", "type": "channel.hype_train.begin", "version": "2", "condition": {"broadcaster_user_id": channel_user_id}},
        {"label": "Hype Train Progress", "type": "channel.hype_train.progress", "version": "2", "condition": {"broadcaster_user_id": channel_user_id}},
        {"label": "Hype Train End", "type": "channel.hype_train.end", "version": "2", "condition": {"broadcaster_user_id": channel_user_id}},
        {
            "label": "Shoutout Create",
            "type": "channel.shoutout.create",
            "version": "1",
            "condition": {
                "broadcaster_user_id": channel_user_id,
                "moderator_user_id": channel_user_id,
            },
        },
        {
            "label": "Shoutout Receive",
            "type": "channel.shoutout.receive",
            "version": "1",
            "condition": {
                "broadcaster_user_id": channel_user_id,
                "moderator_user_id": channel_user_id,
            },
        },
    ]


def build_alert_item_from_event(subscription_type, event, metadata):
    if subscription_type == "channel.follow":
        return make_alert_item(
            "Followers",
            event.get("user_name") or event.get("user_login") or "Unknown",
            "Followed you",
            iso_or_fallback(event, metadata, "followed_at"),
            source="eventsub",
            event_type=subscription_type,
            details=event,
        )
    if subscription_type == "channel.subscribe":
        return make_alert_item(
            "Subs",
            event.get("user_name") or event.get("user_login") or "Unknown",
            "Subscribed",
            iso_or_fallback(event, metadata, "started_at"),
            source="eventsub",
            event_type=subscription_type,
            details=event,
        )
    if subscription_type == "channel.subscription.gift":
        total = int(event.get("total") or 1)
        return make_alert_item(
            "Gifted Subs",
            event.get("user_name") or event.get("user_login") or "Unknown",
            f"Gifted {total} sub{'s' if total != 1 else ''} to your community",
            iso_or_fallback(event, metadata, "started_at"),
            source="eventsub",
            event_type=subscription_type,
            details=event,
        )
    if subscription_type == "channel.raid":
        viewers = int(event.get("viewers") or 0)
        return make_alert_item(
            "Raids",
            event.get("from_broadcaster_user_name") or event.get("from_broadcaster_user_login") or "Unknown",
            f"Raided with {viewers} viewers",
            iso_or_fallback(event, metadata, "created_at"),
            source="eventsub",
            event_type=subscription_type,
            details=event,
        )
    if subscription_type == "channel.cheer":
        return make_alert_item(
            "Bits",
            event.get("user_name") or event.get("user_login") or "Unknown",
            f"Cheered {int(event.get('bits', 0) or 0)} bits",
            iso_or_fallback(event, metadata),
            source="eventsub",
            event_type=subscription_type,
            details=event,
        )
    if subscription_type == "channel.channel_points_custom_reward_redemption.add":
        reward = event.get("reward") or {}
        reward_title = str(reward.get("title") or "a channel reward").strip()
        return make_alert_item(
            "Reward Requests",
            event.get("user_name") or event.get("user_login") or "Unknown",
            f"Redeemed {reward_title}",
            iso_or_fallback(event, metadata, "redeemed_at"),
            source="eventsub",
            event_type=subscription_type,
            details=event,
        )
    if subscription_type.startswith("channel.poll."):
        title = str(event.get("title") or "a poll").strip()
        status_map = {
            "channel.poll.begin": "Started a poll",
            "channel.poll.progress": "Poll activity updated",
            "channel.poll.end": "Poll ended",
        }
        return make_alert_item(
            "Polls",
            event.get("broadcaster_user_name") or event.get("broadcaster_user_login") or "Channel",
            f"{status_map.get(subscription_type, 'Poll activity')}: {title}",
            iso_or_fallback(event, metadata, "started_at", "ended_at"),
            source="eventsub",
            event_type=subscription_type,
            details=event,
        )
    if subscription_type.startswith("channel.prediction."):
        title = str(event.get("title") or "a prediction").strip()
        status_map = {
            "channel.prediction.begin": "Started a prediction",
            "channel.prediction.progress": "Prediction activity updated",
            "channel.prediction.lock": "Prediction locked",
            "channel.prediction.end": "Prediction ended",
        }
        return make_alert_item(
            "Predictions",
            event.get("broadcaster_user_name") or event.get("broadcaster_user_login") or "Channel",
            f"{status_map.get(subscription_type, 'Prediction activity')}: {title}",
            iso_or_fallback(event, metadata, "started_at", "locked_at", "ended_at"),
            source="eventsub",
            event_type=subscription_type,
            details=event,
        )
    if subscription_type.startswith("channel.hype_train."):
        status_map = {
            "channel.hype_train.begin": "Hype Train started",
            "channel.hype_train.progress": f"Hype Train level {int(event.get('level', 0) or 0)} progress updated",
            "channel.hype_train.end": f"Hype Train ended at level {int(event.get('level', 0) or 0)}",
        }
        return make_alert_item(
            "Hype Train",
            event.get("broadcaster_user_name") or event.get("broadcaster_user_login") or "Channel",
            status_map.get(subscription_type, "Hype Train activity"),
            iso_or_fallback(event, metadata, "started_at", "expires_at", "ended_at"),
            source="eventsub",
            event_type=subscription_type,
            details=event,
        )
    if subscription_type in {"channel.shoutout.create", "channel.shoutout.receive"}:
        if subscription_type == "channel.shoutout.create":
            username = event.get("to_broadcaster_user_name") or event.get("to_broadcaster_user_login") or "Unknown"
            text = "Received a shoutout"
        else:
            username = event.get("from_broadcaster_user_name") or event.get("from_broadcaster_user_login") or "Unknown"
            text = "Sent you a shoutout"
        return make_alert_item(
            "Shoutouts",
            username,
            text,
            iso_or_fallback(event, metadata, "started_at"),
            source="eventsub",
            event_type=subscription_type,
            details=event,
        )
    return make_alert_item(
        "Alert",
        event.get("user_name")
        or event.get("user_login")
        or event.get("broadcaster_user_name")
        or event.get("broadcaster_user_login")
        or "Unknown",
        f"Received {subscription_type or 'unknown'} event",
        iso_or_fallback(event, metadata, "created_at", "started_at", "redeemed_at", "followed_at"),
        source="eventsub",
        event_type=subscription_type,
        details=event,
    )


def load_settings():
    if not SETTINGS_FILE.exists():
        raise RuntimeError("settings.json not found")
    return load_json(SETTINGS_FILE, {})


def get_configured_music_command_aliases():
    settings = load_json(SETTINGS_FILE, {})
    aliases = []
    for key in ("music_command", "songrequest_command", "song_request_command", "music_request_command"):
        value = settings.get(key)
        if isinstance(value, str) and value.strip():
            aliases.append(value.strip())
        elif isinstance(value, (list, tuple)):
            aliases.extend(str(item).strip() for item in value if str(item).strip())
    return aliases


def _starts_with_token(text, token):
    lowered = text.lower()
    candidate = token.lower().strip()
    return lowered == candidate or lowered.startswith(f"{candidate} ")


def _address_mojibake_alias(value):
    try:
        return str(value).encode("utf-8").decode("latin-1")
    except Exception:
        return str(value)


def _address_aliases(*values):
    aliases = set()
    for value in values:
        for alias in (str(value or ""), _address_mojibake_alias(value)):
            alias = " ".join(alias.strip().lower().split())
            if alias:
                aliases.add(alias)
    return aliases


def _bot_address_candidates(bot_login):
    bot_name = str(bot_login or "").strip().lower().lstrip("@")
    fixed_names = {"1salemgpt", "1salembot"}
    if bot_name:
        fixed_names.add(bot_name)

    candidates = set()
    candidates.update(_address_aliases("bot", "يا bot", "بوت", "يا بوت", "البوت", "يا البوت"))
    for name in fixed_names:
        candidates.update(
            _address_aliases(
                name,
                f"@{name}",
                f"يا {name}",
                f"يا @{name}",
            )
        )
    return candidates


def find_bot_address_trigger(bot_login, text):
    stripped = (text or "").strip()
    if not stripped:
        return None

    for candidate in sorted(_bot_address_candidates(bot_login), key=len, reverse=True):
        if _starts_with_token(stripped, candidate):
            return stripped[: len(candidate)]
    return None


def extract_twitch_badges(event):
    extracted = []
    for badge in event.get("badges", []) or []:
        extracted.append(
            {
                "set_id": badge.get("set_id", ""),
                "id": badge.get("id", ""),
                "info": badge.get("info", ""),
            }
        )

    if extracted:
        return extracted

    fallback_badges = (
        ("chatter_is_moderator", "moderator"),
        ("chatter_is_vip", "vip"),
        ("chatter_is_subscriber", "subscriber"),
    )
    for flag_name, badge_name in fallback_badges:
        if event.get(flag_name):
            extracted.append({"set_id": badge_name, "id": "1", "info": ""})
    return extracted


def normalize_login(value):
    return str(value or "").strip().lower().lstrip("@")


def badge_search_text(badge):
    if isinstance(badge, dict):
        parts = [
            badge.get("set_id", ""),
            badge.get("id", ""),
            badge.get("info", ""),
            badge.get("title", ""),
            badge.get("name", ""),
        ]
    else:
        parts = [badge]
    return " ".join(str(part or "").strip().lower().replace("_", " ") for part in parts if str(part or "").strip())


def chatter_can_control_music(chatter_name, channel_login, badges):
    chatter = normalize_login(chatter_name)
    channel = normalize_login(channel_login)
    if channel and chatter == channel:
        return True

    searchable = " ".join(badge_search_text(badge) for badge in badges or [])
    if any(role in searchable for role in ("broadcaster", "owner")):
        return True
    if "vip" in searchable:
        return True
    if "moderator" in searchable or re.search(r"\bmod\b", searchable):
        return True
    if ("lead" in searchable or "head" in searchable) and ("moderator" in searchable or "mod" in searchable):
        return True
    return False


def format_music_queue_reply(chatter_name):
    state = load_json(MUSIC_QUEUE_STATE_FILE, {})
    queue = state.get("queue", []) if isinstance(state, dict) else []
    if not isinstance(queue, list):
        queue = []
    count = len(queue)
    if count <= 0:
        return mention_user(chatter_name, "الطابور فاضي")

    titles = []
    for index, item in enumerate(queue[:10], start=1):
        if isinstance(item, dict):
            title = str(item.get("title") or item.get("query") or "Track").strip()
        else:
            title = str(item or "Track").strip()
        title = re.sub(r"\s+", " ", title)
        if len(title) > 38:
            title = title[:35].rstrip() + "..."
        titles.append(f"{index}. {title}")

    suffix = f" | total {count}" if count > 10 else f" | total {count}"
    return mention_user(chatter_name, " | ".join(titles) + suffix)


def extract_twitch_fragments(event):
    extracted = []
    for fragment in event.get("message", {}).get("fragments", []):
        extracted.append(
            {
                "type": fragment.get("type", "text"),
                "text": fragment.get("text", ""),
                "emote": fragment.get("emote"),
                "mention": fragment.get("mention"),
                "cheermote": fragment.get("cheermote"),
            }
        )
    return extracted


def generate_personality_notes(ai_client, user_profiles, username):
    profile = get_user_profile(user_profiles, username)
    recent_messages = get_recent_user_only_messages(username, limit=12)
    old_notes = profile.get("notes", "not enough information yet")

    if len(recent_messages) < 4:
        return old_notes

    joined_messages = "\n".join(f"- {message}" for message in recent_messages)
    analysis_prompt = f"""
Analyze this chatter's style only from their messages.

Username: {username}

Previous notes:
{old_notes}

Recent messages:
{joined_messages}

Return a very short Arabic summary focused on tone, style, and behavior.
One or two short lines only.
Do not invent personal facts.
"""

    try:
        response = ai_client.responses.create(model="gpt-5.4-mini", input=analysis_prompt)
        notes = response.output_text.strip()
        return notes or old_notes
    except Exception:
        return old_notes


def update_user_profile(ai_client, user_profiles, username, message, *, count_message=True, save_callback=None):
    profile = get_user_profile(user_profiles, username)
    if count_message:
        profile["messages"] = int(profile.get("messages", 0) or 0) + 1
    profile["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lowered = message.lower()
    rude_markers = ["idiot", "stupid", "fuck", "غبي", "حمار", "قذر", "زق"]
    if any(marker in lowered for marker in rude_markers):
        profile["behavior"] = "bad"
    elif profile["behavior"] != "bad":
        profile["behavior"] = "good"

    if message.strip() and profile["messages"] % 5 == 0:
        safe_print(f"[PROFILE] Refreshing notes for {username}")
        profile["notes"] = generate_personality_notes(ai_client, user_profiles, username)

    user_profiles[username] = profile
    if callable(save_callback):
        save_callback()
    else:
        save_user_profiles(user_profiles)
    return profile


def normalize_viewer_message_id(message_id):
    return str(message_id or "").strip()


def remember_viewer_message_id(seen_message_ids, seen_message_order, dedupe_key):
    if seen_message_ids is None or seen_message_order is None or not dedupe_key:
        return
    seen_message_ids.add(dedupe_key)
    seen_message_order.append(dedupe_key)
    overflow = len(seen_message_order) - MAX_VIEWER_MESSAGE_DEDUPE_IDS
    if overflow <= 0:
        return
    for stale_key in seen_message_order[:overflow]:
        seen_message_ids.discard(stale_key)
    del seen_message_order[:overflow]


def count_viewer_message(
    user_profiles,
    username,
    *,
    bot_login="",
    text="",
    message_id=None,
    platform="twitch",
    seen_message_ids=None,
    seen_message_order=None,
    log=None,
    save_callback=None,
):
    if log is None:
        log = safe_print

    username = str(username or "").strip()
    if not username:
        return False
    if bot_login and username.lower() == str(bot_login).strip().lower():
        return False

    normalized_message_id = normalize_viewer_message_id(message_id)
    dedupe_key = f"{platform}:{username.lower()}:{normalized_message_id}" if normalized_message_id else ""
    if dedupe_key and seen_message_ids is not None and dedupe_key in seen_message_ids:
        if callable(log):
            log(f"[VIEWERS] Ignored duplicate message from {username}")
        return False

    profile = get_user_profile(user_profiles, username)
    profile["messages"] = int(profile.get("messages", 0) or 0) + 1
    profile["last_seen"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if str(text or "").strip():
        profile["last_message"] = str(text)
    user_profiles[username] = profile
    if callable(save_callback):
        save_callback()
    else:
        save_user_profiles(user_profiles)

    remember_viewer_message_id(seen_message_ids, seen_message_order, dedupe_key)
    if callable(log):
        log(f"[VIEWERS] Counted message from {username}")
    return True


def find_trigger(bot_login, triggers, text, music_command_aliases=None):
    lowered = text.strip().lower()
    bot_address_trigger = find_bot_address_trigger(bot_login, text)
    if bot_address_trigger:
        return bot_address_trigger

    for trigger in triggers:
        if lowered.startswith(trigger):
            return trigger

    mention = f"@{bot_login.lower()}"
    if mention in lowered:
        return mention

    music_action, _ = parse_music_command(text, extra_play_commands=music_command_aliases)
    if music_action:
        return "command"

    return None


def is_bot_address_trigger(bot_login, trigger):
    marker = str(trigger or "").strip().lower()
    if not marker:
        return False

    return marker in _bot_address_candidates(bot_login)


def parse_chat_music_request(bot_login, trigger, cleaned_text, music_command_aliases=None):
    command_action, command_query = parse_music_command(
        cleaned_text,
        extra_play_commands=music_command_aliases,
    )
    if command_action:
        return command_action, command_query

    if is_bot_address_trigger(bot_login, trigger):
        natural_intent = parse_natural_music_command(cleaned_text)
        natural_action, natural_query = natural_intent.to_music_command()
        if natural_action:
            return natural_action, natural_query
        return parse_bot_addressed_music_request(cleaned_text)

    return None, ""


def remove_trigger(bot_login, text, trigger):
    stripped = text.strip()
    lowered = stripped.lower()
    lowered_trigger = str(trigger or "").lower()

    if trigger == "command":
        return stripped

    if lowered_trigger and lowered.startswith(lowered_trigger):
        return stripped[len(trigger) :].strip()

    mention = f"@{bot_login.lower()}"
    if mention in lowered:
        mention_index = lowered.find(mention)
        stripped = stripped[:mention_index] + stripped[mention_index + len(mention) :]
        return stripped.strip()

    return stripped


def is_music_enabled():
    settings = load_json(SETTINGS_FILE, {})
    return bool(settings.get("music_enabled", True))


_GENERIC_MENTION_PATTERN = re.compile(
    r"(?<![\w@])@(?:user|username|user_name|chatter|viewer)\b"
    r"|[\{\[\<](?:user|username|user_name|chatter|viewer)[\}\]\>]",
    re.IGNORECASE,
)


def _clean_reply_spacing(text):
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    cleaned = re.sub(r"\s+([,.!?;:،؛؟])", r"\1", cleaned)
    cleaned = re.sub(r"^[\s,،:؛;.!?؟\-–—]+", "", cleaned)
    return cleaned.strip()


def normalize_reply_for_username(reply, username):
    cleaned_reply = (reply or "").strip()
    clean_username = str(username or "").strip().lstrip("@")
    if not cleaned_reply:
        return ""
    if not clean_username:
        return _clean_reply_spacing(cleaned_reply)

    actual_mention = f"@{clean_username}"
    cleaned_reply = _GENERIC_MENTION_PATTERN.sub(" ", cleaned_reply)
    cleaned_reply = re.sub(
        rf"(?<![\w@]){re.escape(actual_mention)}(?!\w)",
        " ",
        cleaned_reply,
        flags=re.IGNORECASE,
    )
    cleaned_reply = _clean_reply_spacing(cleaned_reply)
    if not cleaned_reply:
        return ""
    return mention_user(clean_username, cleaned_reply)


def build_ai_reply(ai_client, system_prompt, username, cleaned_text, profile):
    if not cleaned_text:
        return mention_user(username, MENTION_REPLY)

    recent_history = get_recent_user_messages(username, limit=8)
    memory_summary = (
        f"Known user profile:\n"
        f"- behavior: {profile.get('behavior', 'neutral')}\n"
        f"- notes: {profile.get('notes', 'not enough information yet')}\n"
    )
    history_text = "\n".join(recent_history) if recent_history else "No recent history."

    try:
        response = ai_client.responses.create(
            model="gpt-5.4-mini",
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "system", "content": memory_summary},
                {"role": "system", "content": f"Recent history:\n{history_text}"},
                {
                    "role": "system",
                    "content": (
                        f"Reply naturally to {username}. Do not include @user, @username, "
                        f"or any placeholder mentions. Do not add extra mentions. "
                        f"The app will prepend exactly one @{username} before sending."
                    ),
                },
                {"role": "user", "content": cleaned_text},
            ],
        )
        reply = normalize_reply_for_username(response.output_text, username)
        if not reply:
            return mention_user(username, MENTION_REPLY)
        if len(reply) > 180:
            reply = reply[:180].rsplit(" ", 1)[0] + "..."
        return reply
    except Exception as exc:
        safe_print("[AI ERROR]", str(exc))
        return mention_user(username, AI_ERROR_REPLY)


def send_twitch_reply(token, channel_user_id, bot_user_id, reply, username, cleaned_text):
    try:
        safe_print(f"[TWITCH SEND] Sending reply to {username}: {reply}")
        result = send_chat_message(CLIENT_ID, token, channel_user_id, bot_user_id, reply)
        log_chat(username, cleaned_text, reply, platform="twitch")
        safe_print("[TWITCH SENT]", result)
        safe_print(f"[BOT] Bot replied to @{str(username or '').strip().lstrip('@')}")
    except Exception as exc:
        safe_print("[TWITCH SEND ERROR]", str(exc))


def create_message_handler(platform, bot_login, triggers, ai_client, user_profiles, dashboard_state, system_prompt, send_reply, persistence=None, channel_login=""):
    seen_viewer_message_ids = set()
    seen_viewer_message_order = []

    def mark_users_dirty():
        if persistence is not None:
            persistence.mark_users_dirty()
        else:
            save_user_profiles(user_profiles)

    def mark_dashboard_dirty():
        if persistence is not None:
            persistence.mark_dashboard_dirty()
        else:
            save_dashboard_state(dashboard_state)

    def update_dashboard_for_message(username, text, *, display_name=None, badges=None, fragments=None):
        sync_dashboard_day(dashboard_state)
        dashboard_state["messages_today"] += 1
        record_dashboard_metric(dashboard_state, "messages")
        dashboard_state["top_chatters"][username] = dashboard_state["top_chatters"].get(username, 0) + 1
        append_recent_chat(
            dashboard_state,
            username,
            text,
            display_name=display_name,
            badges=badges,
            fragments=fragments,
            platform=platform,
        )
        mark_dashboard_dirty()

    def handle_message(chatter_name, text, *, display_name=None, badges=None, fragments=None, message_id=None):
        try:
            safe_print(f"[{platform.upper()} CHAT] {chatter_name}: {text}")
            if not chatter_name or not text or chatter_name.lower() == bot_login.lower():
                safe_print(f"[{platform.upper()} CHAT] Ignored event due to empty message or self-message")
                return

            with persistence_update_lock(persistence):
                sync_dashboard_day(dashboard_state)
                if not count_viewer_message(
                    user_profiles,
                    chatter_name,
                    bot_login=bot_login,
                    text=text,
                    message_id=message_id,
                    platform=platform,
                    seen_message_ids=seen_viewer_message_ids,
                    seen_message_order=seen_viewer_message_order,
                    save_callback=mark_users_dirty,
                ):
                    return

                update_dashboard_for_message(
                    chatter_name,
                    text,
                    display_name=display_name,
                    badges=badges,
                    fragments=fragments,
                )

            music_command_aliases = get_configured_music_command_aliases()
            trigger = find_trigger(bot_login, triggers, text, music_command_aliases=music_command_aliases)
            if not trigger:
                if looks_like_implicit_music_text(text):
                    safe_print(
                        f"[{platform.upper()} CHAT] Ignored normal chat message for music: "
                        "explicit command required"
                    )
                safe_print(f"[{platform.upper()} CHAT] No trigger matched for '{text}'")
                return

            safe_print(f"[{platform.upper()} CHAT] Trigger matched: {trigger}")
            cleaned_text = remove_trigger(bot_login, text, trigger)
            safe_print(f"[{platform.upper()} CHAT] Cleaned text: {cleaned_text}")

            command_action, command_query = parse_chat_music_request(
                bot_login,
                trigger,
                cleaned_text,
                music_command_aliases=music_command_aliases,
            )
            if command_action in {"play", "skip", "stop", "queue", "volume", "remove"}:
                safe_print(f"[{platform.upper()} CHAT] Music command detected: {command_action} {command_query}")
                with persistence_update_lock(persistence):
                    dashboard_state["commands_used"] += 1
                    record_dashboard_metric(dashboard_state, "commands")
                    increment_top_command(dashboard_state, command_action)
                    mark_dashboard_dirty()

                if command_action == "queue":
                    send_reply(format_music_queue_reply(chatter_name), chatter_name, cleaned_text, message_id=message_id)
                    return

                if command_action in {"skip", "stop", "volume", "remove"} and not chatter_can_control_music(chatter_name, channel_login, badges):
                    safe_print(f"[{platform.upper()} CHAT] Music control denied for {chatter_name}: {command_action}")
                    send_reply(
                        mention_user(chatter_name, "هذا الأمر للمشرفين و VIP فقط"),
                        chatter_name,
                        cleaned_text,
                        message_id=message_id,
                    )
                    return

                if command_action == "play":
                    if not is_music_enabled():
                        send_reply(mention_user(chatter_name, MUSIC_DISABLED_REPLY), chatter_name, cleaned_text, message_id=message_id)
                        return
                    if command_query:
                        safe_print(f"[{platform.upper()} CHAT] Forwarding play request into music pipeline: {command_query}")
                        write_music_command(
                            MUSIC_COMMAND_FILE,
                            "play",
                            command_query,
                            source=platform,
                            requested_by=chatter_name,
                            raw_text=text,
                        )
                        reply = mention_user(chatter_name, MUSIC_QUEUED_REPLY)
                    else:
                        reply = mention_user(chatter_name, MUSIC_NEEDS_QUERY_REPLY)
                elif command_action == "skip":
                    safe_print(f"[{platform.upper()} CHAT] Forwarding skip request into music pipeline")
                    write_music_command(
                        MUSIC_COMMAND_FILE,
                        "skip",
                        source=platform,
                        requested_by=chatter_name,
                        raw_text=text,
                    )
                    reply = mention_user(chatter_name, MUSIC_SKIPPED_REPLY)
                elif command_action == "stop":
                    safe_print(f"[{platform.upper()} CHAT] Forwarding stop request into music pipeline")
                    write_music_command(
                        MUSIC_COMMAND_FILE,
                        "stop",
                        source=platform,
                        requested_by=chatter_name,
                        raw_text=text,
                    )
                    reply = mention_user(chatter_name, MUSIC_STOPPED_REPLY)
                elif command_action == "volume":
                    if not re.match(r"^[+-]?\d{1,3}$", str(command_query or "").strip()):
                        reply = mention_user(chatter_name, "استخدم: !volume 50 أو !volume +10")
                    else:
                        safe_print(f"[{platform.upper()} CHAT] Forwarding volume request into music pipeline: {command_query}")
                        write_music_command(
                            MUSIC_COMMAND_FILE,
                            "volume",
                            command_query,
                            source=platform,
                            requested_by=chatter_name,
                            raw_text=text,
                        )
                        reply = mention_user(chatter_name, "تم، عدلت الصوت")
                else:
                    if not re.match(r"^\d+$", str(command_query or "").strip()):
                        reply = mention_user(chatter_name, "استخدم: !remove 3")
                    else:
                        safe_print(f"[{platform.upper()} CHAT] Forwarding remove request into music pipeline: {command_query}")
                        write_music_command(
                            MUSIC_COMMAND_FILE,
                            "remove",
                            command_query,
                            source=platform,
                            requested_by=chatter_name,
                            raw_text=text,
                        )
                        reply = mention_user(chatter_name, "تم، شلتها من الطابور")

                send_reply(reply, chatter_name, cleaned_text, message_id=message_id)
                return

            if looks_like_implicit_music_text(cleaned_text):
                safe_print(
                    f"[{platform.upper()} CHAT] Ignored normal chat message for music: "
                    "explicit command required"
                )

            with persistence_update_lock(persistence):
                dashboard_state["commands_used"] += 1
                record_dashboard_metric(dashboard_state, "commands")
                increment_top_command(dashboard_state, "mention" if not cleaned_text.strip() else "reply")
                mark_dashboard_dirty()

            if not cleaned_text.strip():
                safe_print(f"[{platform.upper()} CHAT] Empty cleaned text, sending lightweight mention reply to {chatter_name}")
                send_reply(mention_user(chatter_name, MENTION_REPLY), chatter_name, cleaned_text, message_id=message_id)
                return

            safe_print(f"[{platform.upper()} PROFILE] Updating profile for {chatter_name}")
            with persistence_update_lock(persistence):
                profile = update_user_profile(
                    ai_client,
                    user_profiles,
                    chatter_name,
                    cleaned_text,
                    count_message=False,
                    save_callback=mark_users_dirty,
                )
            safe_print(
                f"[{platform.upper()} PROFILE] Profile ready for {chatter_name}: "
                f"messages={profile.get('messages', 0)} behavior={profile.get('behavior', '')}"
            )
            safe_print(f"[{platform.upper()} CHAT] Building AI reply for {chatter_name}")
            reply = build_ai_reply(ai_client, system_prompt, chatter_name, cleaned_text, profile)
            safe_print(f"[{platform.upper()} CHAT] Reply ready for {chatter_name}: {reply}")
            send_reply(reply, chatter_name, cleaned_text, message_id=message_id)
        except Exception as exc:
            safe_print(f"[{platform.upper()} CHAT ERROR]", str(exc))
            safe_print(traceback.format_exc())

    return handle_message


def start_twitch_listener(settings, ai_client, user_profiles, dashboard_state, triggers, system_prompt, persistence=None):
    safe_print("[TWITCH] Connecting to Twitch")

    def format_scopes(scopes):
        return ", ".join(sorted(scopes)) if scopes else "(none)"

    def log_token_diagnostics(role_label, details, validation=None):
        validation = validation or {}
        safe_print(f"[TWITCH AUTH] {role_label} token path: {details.get('path')}")
        safe_print(f"[TWITCH AUTH] {role_label} token type: user access token")
        safe_print(f"[TWITCH AUTH] {role_label} token login: {validation.get('login') or details.get('login') or 'unknown'}")
        safe_print(f"[TWITCH AUTH] {role_label} token user_id: {validation.get('user_id') or details.get('user_id') or 'unknown'}")
        safe_print(f"[TWITCH AUTH] {role_label} token scopes: {format_scopes(validation.get('scopes') or details.get('scopes') or [])}")

    def missing_scopes(granted_scopes, required_scopes):
        return [scope for scope in required_scopes if scope not in set(granted_scopes or [])]

    def log_alert_scope_summary(channel_scopes):
        channel_scopes = set(channel_scopes or [])
        for subscription_type, required_scopes in ALERT_SCOPE_REQUIREMENTS.items():
            missing = missing_alert_scopes(channel_scopes, required_scopes)
            if missing:
                safe_print(f"[ALERTS] {subscription_type}: missing scopes -> {', '.join(missing)}")
            else:
                safe_print(f"[ALERTS] {subscription_type}: scope check ok")

    bot_required_scopes = ["user:read:chat", "user:write:chat", "user:bot"]

    bot_token_details = load_token_details(BOT_AUTH_ROLE)
    bot_token = bot_token_details.get("access_token")
    if not bot_token:
        safe_print(f"[TWITCH] No bot token found. Checked: {bot_token_details.get('path')}")
        return False

    try:
        bot_validation = validate_token(bot_token)
    except Exception as exc:
        safe_print(f"[TWITCH AUTH] Bot token validation failed: {exc}")
        return False

    log_token_diagnostics("Bot", bot_token_details, bot_validation)
    missing_bot_scopes = missing_scopes(bot_validation.get("scopes", []), bot_required_scopes)
    if missing_bot_scopes:
        safe_print(f"[TWITCH AUTH] Bot token is missing required chat scopes: {', '.join(missing_bot_scopes)}")
        safe_print("[TWITCH AUTH] Reconnect the Bot Account and grant the required scopes before starting the bot")
        return False

    channel_token_details = load_token_details(CHANNEL_AUTH_ROLE)
    channel_token = channel_token_details.get("access_token")
    channel_validation = None
    if channel_token:
        try:
            channel_validation = validate_token(channel_token)
            log_token_diagnostics("Channel", channel_token_details, channel_validation)
        except Exception as exc:
            safe_print(f"[TWITCH AUTH] Channel token validation failed: {exc}")
            channel_token = None
            channel_validation = None
    else:
        safe_print(f"[TWITCH AUTH] Channel token not found. Checked: {channel_token_details.get('path')}")

    bot_login = settings.get("bot_login", "").strip()
    channel_login = settings.get("channel_login", "").strip()
    if not bot_login or not channel_login:
        safe_print("[TWITCH] Bot Login and Channel Login must be configured before starting the bot")
        return False

    bot_user = get_user_by_login(CLIENT_ID, bot_token, bot_login)
    lookup_token_for_channel = channel_token or bot_token
    channel_user = get_user_by_login(CLIENT_ID, lookup_token_for_channel, channel_login)
    if not bot_user:
        safe_print(f"[TWITCH] Bot account not found: {bot_login}")
        return False
    if not channel_user:
        safe_print(f"[TWITCH] Channel account not found: {channel_login}")
        return False

    bot_user_id = bot_user["id"]
    channel_user_id = channel_user["id"]

    validated_bot_user_id = bot_validation.get("user_id", "")
    if validated_bot_user_id and validated_bot_user_id != bot_user_id:
        safe_print(
            f"[TWITCH AUTH] Bot token belongs to user_id={validated_bot_user_id},"
            f" but Bot Login resolves to user_id={bot_user_id}. Reconnect the Bot Account with the correct Twitch user."
        )
        return False

    if channel_validation:
        validated_channel_user_id = channel_validation.get("user_id", "")
        if validated_channel_user_id and validated_channel_user_id != channel_user_id:
            safe_print(
                f"[TWITCH AUTH] Channel token belongs to user_id={validated_channel_user_id},"
                f" but Channel Login resolves to user_id={channel_user_id}. Reconnect the Channel Account with the correct broadcaster."
            )
            return False

    safe_print(f"[TWITCH] BOT LOGIN: {bot_login}")
    safe_print(f"[TWITCH] CHANNEL LOGIN: {channel_login}")
    safe_print(f"[TWITCH] BOT AUTH LOGIN: {bot_validation.get('login') or bot_token_details.get('login') or 'unknown'}")

    bot_is_moderator = None
    if channel_token and channel_validation:
        safe_print(f"[TWITCH] CHANNEL AUTH LOGIN: {channel_validation.get('login') or channel_token_details.get('login') or 'unknown'}")
        channel_scopes = channel_validation.get("scopes", [])
        has_channel_bot_scope = "channel:bot" in channel_scopes
        safe_print(f"[TWITCH AUTH] Channel token has channel:bot: {'yes' if has_channel_bot_scope else 'no'}")
        try:
            bot_is_moderator = is_user_moderator(CLIENT_ID, channel_token, channel_user_id, bot_user_id)
            safe_print(f"[TWITCH AUTH] Bot moderator status in channel: {'yes' if bot_is_moderator else 'no'}")
        except Exception as exc:
            bot_is_moderator = None
            safe_print(f"[TWITCH AUTH] Could not verify bot moderator status: {exc}")

        if has_channel_bot_scope:
            safe_print("[TWITCH] Full broadcaster/channel permissions are enabled")
        elif bot_is_moderator:
            safe_print("[TWITCH] Channel token is missing channel:bot, but the bot is a moderator in the channel")
        else:
            safe_print(
                "[TWITCH AUTH] Channel token is missing channel:bot and the bot is not verified as a moderator."
                " Broadcaster-level chat authorization may be incomplete."
            )
    else:
        safe_print("[TWITCH] Channel account not connected. Starting in limited mode with bot token only")

    handler = create_message_handler(
        "twitch",
        bot_login,
        triggers,
        ai_client,
        user_profiles,
        dashboard_state,
        system_prompt,
        send_reply=lambda reply, username, cleaned_text, message_id=None: send_twitch_reply(
            bot_token,
            channel_user_id,
            bot_user_id,
            reply,
            username,
            cleaned_text,
        ),
        persistence=persistence,
        channel_login=channel_login,
    )

    def on_chat_message(event):
        handler(
            event.get("chatter_user_login", ""),
            event.get("message", {}).get("text", ""),
            display_name=event.get("chatter_user_name") or event.get("chatter_user_login", ""),
            badges=extract_twitch_badges(event),
            fragments=extract_twitch_fragments(event),
            message_id=event.get("message_id") or event.get("_eventsub_message_id") or event.get("id"),
        )

    def on_alert_event(subscription_type, event, metadata):
        try:
            safe_print(f"[ALERTS] Received alert event: {subscription_type}")
            alert_item = build_alert_item_from_event(subscription_type, event, metadata)
            if not alert_item:
                safe_print(f"[ALERTS] Ignored unsupported event payload: {subscription_type}")
                return
            add_alert_items(ALERTS_FILE, [alert_item])
            safe_print(f"[ALERTS] Saved alert event: {subscription_type}")
        except Exception as exc:
            safe_print(f"[ALERTS] Failed to store alert for {subscription_type}: {exc}")

    def on_alert_subscription_result(request, succeeded, reason="", status_code=None, response_text=""):
        subscription_type = request.get("type", "")
        required_scopes = ALERT_SCOPE_REQUIREMENTS.get(subscription_type, [])
        base_status = {
            "label": request.get("label") or subscription_type,
            "required_scopes": required_scopes,
            "missing_scopes": [],
            "status_code": status_code,
            "reason": reason or "",
            "response": response_text or "",
        }
        if succeeded:
            update_alert_subscription_status(
                ALERT_STATUS_FILE,
                subscription_type,
                status="subscribed",
                **base_status,
            )
            safe_print(f"[ALERTS] Subscribed to alert event: {subscription_type}")
            return

        update_alert_subscription_status(
            ALERT_STATUS_FILE,
            subscription_type,
            status="failed",
            **base_status,
        )
        safe_print(f"[ALERTS] Failed to subscribe to {subscription_type}: {reason or 'unknown error'}")

    def on_connection_status(state, message=""):
        runtime_status = {
            "connected": "connecting",
            "ready": "connected",
            "reconnecting": "reconnecting",
            "error": "error",
            "closed": "disconnected",
        }.get(str(state or "").lower(), str(state or ""))
        touch_bot_runtime_state(status=runtime_status, message=message)

    safe_print("[EVENTSUB] Connecting to WebSocket")
    chat_client = TwitchEventSubClient(
        client_id=CLIENT_ID,
        access_token=bot_token,
        broadcaster_user_id=channel_user_id,
        bot_user_id=bot_user_id,
        on_chat_message=on_chat_message,
        on_connection_status=on_connection_status,
        logger=safe_print,
        subscription_auth_type="user access token",
        subscription_auth_role="bot account",
        subscription_auth_login=bot_validation.get("login") or bot_login,
        subscription_requests=[
            {
                "label": "Chat Messages",
                "type": "channel.chat.message",
                "version": "1",
                "condition": {
                    "broadcaster_user_id": channel_user_id,
                    "user_id": bot_user_id,
                },
            }
        ],
    )
    chat_client.connect()
    LISTENERS.append(chat_client)
    safe_print("[EVENTSUB] Connection requested")
    safe_print("[TWITCH] Chat listener is running")
    safe_print("[ALERTS] Alerts are managed by the standalone alerts listener, not Start Bot")
    return True


def main():
    safe_print("[BOT] Bot started")
    touch_bot_runtime_state(status="starting", message="bot runtime starting")
    cert_path = configure_ssl_cert_env()
    safe_print(f"[APP] SSL CERT FILE: {cert_path or 'not found'}")
    ensure_app_files(
        SETTINGS_FILE,
        USERS_FILE,
        DASHBOARD_STATE_FILE,
        MUSIC_COMMAND_FILE,
        CHAT_LOG_FILE,
        alerts_file=ALERTS_FILE,
    )

    settings = load_settings()
    bot_login = settings.get("bot_login", "").strip()
    channel_login = settings.get("channel_login", "").strip()
    triggers = [
        item.strip().lower()
        for item in settings.get("triggers", DEFAULT_TRIGGERS).split(",")
        if item.strip()
    ]

    raw_prompt = settings.get("system_prompt", DEFAULT_PROMPT)
    system_prompt = build_runtime_system_prompt(raw_prompt, bot_login, channel_login, triggers)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is missing.")

    ai_client = OpenAI(api_key=api_key)
    user_profiles = load_user_profiles()
    dashboard_state = load_dashboard_state()
    persistence = ChatPersistenceManager(user_profiles, dashboard_state)

    started_any = False
    try:
        started_any = start_twitch_listener(
            settings,
            ai_client,
            user_profiles,
            dashboard_state,
            triggers,
            system_prompt,
            persistence=persistence,
        ) or started_any
    except Exception as exc:
        safe_print(f"[ERROR] Twitch startup failed: {exc}")
        safe_print(traceback.format_exc())

    if not started_any:
        raise RuntimeError("Twitch bot did not start. Verify Twitch login and settings.")

    safe_print("[BOT] Listening for chat messages")
    last_runtime_heartbeat_at = 0.0
    stale_reported = False
    try:
        while True:
            now = time.monotonic()
            health_snapshots = [
                listener.health_snapshot(stale_after_seconds=BOT_EVENTSUB_STALE_SECONDS)
                for listener in LISTENERS
                if hasattr(listener, "health_snapshot")
            ]
            stale_snapshot = next((snapshot for snapshot in health_snapshots if snapshot.get("stale")), None)
            if stale_snapshot:
                if not stale_reported:
                    idle_seconds = stale_snapshot.get("idle_seconds")
                    idle_text = f"{int(idle_seconds)}s idle" if idle_seconds is not None else str(stale_snapshot.get("state") or "unknown")
                    safe_print(f"[BOT] Bot connection stale, reconnecting ({idle_text})")
                    stale_reported = True
                touch_bot_runtime_state(status="stale", message="EventSub connection stale")
            elif now - last_runtime_heartbeat_at >= BOT_RUNTIME_HEARTBEAT_SECONDS:
                touch_bot_runtime_state(status="connected", message="bot runtime healthy")
                last_runtime_heartbeat_at = now
                stale_reported = False
            time.sleep(1)
    except KeyboardInterrupt:
        safe_print("[BOT] Bot stopped")
    finally:
        for listener in LISTENERS:
            stop = getattr(listener, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
        persistence.shutdown()


if __name__ == "__main__":
    main()

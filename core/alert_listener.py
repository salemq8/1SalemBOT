import time
import traceback

from .alert_storage import (
    ALERT_EVENT_SCOPE_REQUIREMENTS,
    add_alert_items,
    make_alert_item,
    missing_alert_scopes,
    update_alert_listener_status,
    update_alert_subscription_status,
)
from .app_paths import ALERTS_FILE, ALERT_STATUS_FILE, CHAT_LOG_FILE, DASHBOARD_STATE_FILE, MUSIC_COMMAND_FILE, SETTINGS_FILE, USERS_FILE
from .app_state import ensure_app_files, load_json
from .auth import CHANNEL_AUTH_ROLE, CLIENT_ID, load_token_details, validate_token
from .runtime_env import configure_ssl_cert_env
from .twitch_eventsub import TwitchEventSubClient


LISTENERS = []
ALERT_SCOPE_REQUIREMENTS = ALERT_EVENT_SCOPE_REQUIREMENTS


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


def update_overall_alert_status(subscription_states):
    missing = []
    failed = []
    subscribed = []
    pending = []

    for event_type, entry in subscription_states.items():
        state = entry.get("status")
        if state == "missing_scope":
            missing.extend(entry.get("missing_scopes", []))
        elif state == "failed":
            failed.append(event_type)
        elif state == "subscribed":
            subscribed.append(event_type)
        elif state == "pending":
            pending.append(event_type)

    unique_missing = []
    for scope in missing:
        if scope not in unique_missing:
            unique_missing.append(scope)

    if unique_missing:
        update_alert_listener_status(
            ALERT_STATUS_FILE,
            "missing_permissions",
            f"Missing permissions: {', '.join(unique_missing)}",
            missing_scopes=unique_missing,
        )
    elif subscribed:
        update_alert_listener_status(
            ALERT_STATUS_FILE,
            "connected",
            f"Listening to {len(subscribed)} alert event types",
            subscribed_count=len(subscribed),
        )
    elif pending:
        update_alert_listener_status(ALERT_STATUS_FILE, "connecting", "Subscribing to Twitch alert events")
    elif failed:
        update_alert_listener_status(
            ALERT_STATUS_FILE,
            "disconnected",
            f"Failed to subscribe to alert events: {', '.join(failed[:3])}",
        )
    else:
        update_alert_listener_status(ALERT_STATUS_FILE, "disconnected", "No alert subscriptions are active")


def run_alert_listener():
    safe_print("[ALERTS] Alerts service starting")
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

    settings = load_json(SETTINGS_FILE, {})
    channel_details = load_token_details(CHANNEL_AUTH_ROLE)
    channel_token = channel_details.get("access_token")
    if not channel_token:
        update_alert_listener_status(ALERT_STATUS_FILE, "disconnected", "Channel Account is not connected")
        safe_print("[ALERTS] Channel Account is not connected")
        return 1

    try:
        validation = validate_token(channel_token)
    except Exception as exc:
        update_alert_listener_status(ALERT_STATUS_FILE, "disconnected", f"Channel token validation failed: {exc}")
        safe_print(f"[ALERTS] Channel token validation failed: {exc}")
        return 1

    channel_user_id = str(validation.get("user_id") or channel_details.get("user_id") or "").strip()
    channel_login = str(validation.get("login") or channel_details.get("login") or settings.get("channel_login") or "unknown").strip()
    if not channel_user_id:
        update_alert_listener_status(ALERT_STATUS_FILE, "disconnected", "Channel token did not include a Twitch user ID")
        safe_print("[ALERTS] Channel token did not include a Twitch user ID")
        return 1

    configured_channel = str(settings.get("channel_login") or "").strip()
    if configured_channel and channel_login and configured_channel.casefold() != channel_login.casefold():
        safe_print(
            f"[ALERTS] Channel setting is {configured_channel}, but Channel Account token belongs to {channel_login}. "
            "Alerts will listen to the authenticated Channel Account."
        )

    channel_scopes = set(validation.get("scopes") or channel_details.get("scopes") or [])
    subscription_states = {}
    alert_requests = []
    for request in build_alert_subscription_requests(channel_user_id):
        subscription_type = request["type"]
        required_scopes = ALERT_SCOPE_REQUIREMENTS.get(subscription_type, [])
        missing = missing_alert_scopes(channel_scopes, required_scopes)
        if missing:
            entry = {
                "status": "missing_scope",
                "label": request.get("label") or subscription_type,
                "required_scopes": required_scopes,
                "missing_scopes": missing,
                "reason": f"Missing required permission: {', '.join(missing)}",
                "status_code": None,
                "response": "",
            }
            subscription_states[subscription_type] = entry
            update_alert_subscription_status(ALERT_STATUS_FILE, subscription_type, **entry)
            safe_print(f"[ALERTS] Failed to subscribe to {subscription_type}: missing required permission {', '.join(missing)}")
            continue

        entry = {
            "status": "pending",
            "label": request.get("label") or subscription_type,
            "required_scopes": required_scopes,
            "missing_scopes": [],
            "reason": "Waiting for EventSub session",
            "status_code": None,
            "response": "",
        }
        subscription_states[subscription_type] = entry
        update_alert_subscription_status(ALERT_STATUS_FILE, subscription_type, **entry)
        alert_requests.append(request)

    update_overall_alert_status(subscription_states)
    if not alert_requests:
        safe_print("[ALERTS] No alert subscriptions could be started with current channel scopes")
        return 1

    def on_alert_event(subscription_type, event, metadata):
        try:
            safe_print(f"[ALERTS] Received alert event: {subscription_type}")
            alert_item = build_alert_item_from_event(subscription_type, event, metadata)
            add_alert_items(ALERTS_FILE, [alert_item])
            safe_print(f"[ALERTS] Saved alert event: {subscription_type}")
        except Exception as exc:
            safe_print(f"[ALERTS] Failed to store alert for {subscription_type}: {exc}")

    def on_subscription_result(request, succeeded, reason="", status_code=None, response_text=""):
        subscription_type = request.get("type", "")
        entry = {
            "status": "subscribed" if succeeded else "failed",
            "label": request.get("label") or subscription_type,
            "required_scopes": ALERT_SCOPE_REQUIREMENTS.get(subscription_type, []),
            "missing_scopes": [],
            "status_code": status_code,
            "reason": reason or "",
            "response": response_text or "",
        }
        subscription_states[subscription_type] = entry
        update_alert_subscription_status(ALERT_STATUS_FILE, subscription_type, **entry)
        if succeeded:
            safe_print(f"[ALERTS] Subscribed to alert event: {subscription_type}")
        else:
            safe_print(f"[ALERTS] Failed to subscribe to {subscription_type}: {reason or 'unknown error'}")
        update_overall_alert_status(subscription_states)

    def on_connection_status(state, message=""):
        if state in {"error", "closed"}:
            update_alert_listener_status(ALERT_STATUS_FILE, "disconnected", message or "EventSub disconnected")
        elif state in {"connected", "ready", "reconnecting"}:
            update_overall_alert_status(subscription_states)

    update_alert_listener_status(ALERT_STATUS_FILE, "connecting", f"Connecting alerts for {channel_login}")
    client = TwitchEventSubClient(
        client_id=CLIENT_ID,
        access_token=channel_token,
        broadcaster_user_id=channel_user_id,
        on_event=on_alert_event,
        on_subscription_result=on_subscription_result,
        on_connection_status=on_connection_status,
        logger=safe_print,
        subscription_auth_type="user access token",
        subscription_auth_role="channel account",
        subscription_auth_login=channel_login,
        subscription_requests=alert_requests,
    )
    client.connect()
    LISTENERS.append(client)
    safe_print("[ALERTS] Alerts listener requested")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        safe_print("[ALERTS] Alerts service stopped")
    finally:
        update_alert_listener_status(ALERT_STATUS_FILE, "disconnected", "Alerts service stopped")
        for listener in LISTENERS:
            stop = getattr(listener, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
    return 0


def main():
    try:
        return run_alert_listener()
    except Exception as exc:
        safe_print(f"[ALERTS] Alerts service failed: {exc}")
        safe_print(traceback.format_exc())
        update_alert_listener_status(ALERT_STATUS_FILE, "disconnected", f"Alerts service failed: {exc}")
        return 1

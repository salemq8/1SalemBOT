import json
import threading
import time

import requests
import websocket


EVENTSUB_WS_URL = "wss://eventsub.wss.twitch.tv/ws"
HELIX_EVENTSUB_URL = "https://api.twitch.tv/helix/eventsub/subscriptions"
REQUEST_TIMEOUT = 15
KEEPALIVE_SUMMARY_COUNT = 25
KEEPALIVE_SUMMARY_SECONDS = 300
REPEATED_LOG_RATE_LIMIT_SECONDS = 30


class TwitchEventSubClient:
    def __init__(
        self,
        client_id,
        access_token,
        broadcaster_user_id,
        *,
        bot_user_id="",
        on_chat_message=None,
        on_event=None,
        on_subscription_result=None,
        on_connection_status=None,
        logger=None,
        subscription_auth_type="user access token",
        subscription_auth_role="bot",
        subscription_auth_login="",
        subscription_requests=None,
    ):
        self.client_id = client_id
        self.access_token = access_token
        self.bot_user_id = bot_user_id
        self.broadcaster_user_id = broadcaster_user_id
        self.on_chat_message = on_chat_message
        self.on_event = on_event
        self.on_subscription_result = on_subscription_result
        self.on_connection_status = on_connection_status
        self.logger = logger or print
        self.subscription_auth_type = subscription_auth_type
        self.subscription_auth_role = subscription_auth_role
        self.subscription_auth_login = subscription_auth_login
        self.subscription_requests = list(subscription_requests or [])

        self.ws = None
        self.session_id = None
        self.websocket_url = EVENTSUB_WS_URL
        self._subscribe_retry_cache = set()
        self._keepalive_count_since_log = 0
        self._last_keepalive_summary_at = time.monotonic()
        self._last_keepalive_at = 0.0
        self._last_message_at = 0.0
        self._last_log_times = {}
        self._suppressed_log_counts = {}
        self._reconnecting = False

    def _headers(self):
        return {
            "Client-Id": self.client_id,
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def connect(self):
        self._subscribe_retry_cache = set()
        self._last_keepalive_summary_at = time.monotonic()
        self.logger("[EVENTSUB] Connecting to WebSocket:", self.websocket_url)
        self.ws = websocket.WebSocketApp(
            self.websocket_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        threading.Thread(
            target=lambda: self.ws.run_forever(ping_interval=20, ping_timeout=10),
            daemon=True,
        ).start()

    def stop(self):
        self._flush_keepalive_summary()
        try:
            if self.ws is not None:
                self.ws.close()
        except Exception:
            pass

    def _on_open(self, ws):
        if self._reconnecting:
            self.logger("[EVENTSUB] Reconnect success")
            self._reconnecting = False
        else:
            self.logger("[EVENTSUB] Connected")
        self.emit_connection_status("connected", "WebSocket connected")

    def _on_error(self, ws, error):
        self._flush_keepalive_summary()
        message = str(error)
        prefix = "[EVENTSUB] Ping/pong timeout" if "ping" in message.lower() and "timed out" in message.lower() else "[ERROR] EventSub WebSocket error"
        if self._reconnecting:
            self._log_rate_limited(f"reconnect-failed:{message}", f"[EVENTSUB] Reconnect failed: {message}")
        self._log_rate_limited(f"ws-error:{message}", f"{prefix}: {message}")
        self.emit_connection_status("error", str(error))

    def _on_close(self, ws, close_status_code, close_msg):
        self._flush_keepalive_summary()
        self.logger("[EVENTSUB] Disconnected:", close_status_code, close_msg)
        self.emit_connection_status("closed", f"{close_status_code or ''} {close_msg or ''}".strip())

    def _on_message(self, ws, message):
        payload = json.loads(message)
        metadata = payload.get("metadata", {})
        message_type = metadata.get("message_type")
        self._last_message_at = time.monotonic()

        if message_type == "session_welcome":
            self.session_id = payload["payload"]["session"]["id"]
            self.logger("[EVENTSUB] Session ready:", self.session_id)
            self.emit_connection_status("ready", "EventSub session ready")
            self.subscribe_all()
            return

        if message_type == "notification":
            subscription = payload["payload"].get("subscription", {})
            event = payload["payload"].get("event", {})
            subscription_type = subscription.get("type", "")
            if subscription_type == "channel.chat.message":
                eventsub_message_id = metadata.get("message_id")
                if eventsub_message_id and "_eventsub_message_id" not in event:
                    event["_eventsub_message_id"] = eventsub_message_id
                chatter = event.get("chatter_user_login", "")
                text = event.get("message", {}).get("text", "")
                self.logger(f"[EVENTSUB] Chat event received from {chatter}: {text}")
                if callable(self.on_chat_message):
                    self.on_chat_message(event)
            elif callable(self.on_event):
                self.logger(f"[EVENTSUB] Alert event received: {subscription_type}")
                self.on_event(subscription_type, event, metadata)
            return

        if message_type == "session_keepalive":
            self._record_keepalive()
            return

        if message_type == "session_reconnect":
            reconnect_url = payload["payload"]["session"].get("reconnect_url")
            if reconnect_url:
                self._flush_keepalive_summary()
                self.websocket_url = reconnect_url
                self._reconnecting = True
                self.logger("[EVENTSUB] Reconnecting")
                self.emit_connection_status("reconnecting", "EventSub reconnect requested")
                try:
                    if self.ws is not None:
                        self.ws.close()
                except Exception:
                    pass
                self.connect()
            return

        if message_type == "revocation":
            subscription = payload["payload"].get("subscription", {})
            self.logger(
                "[EVENTSUB] Subscription revoked:",
                subscription.get("type"),
                subscription.get("status"),
            )
            self.emit_subscription_result(
                {"type": subscription.get("type"), "label": subscription.get("type")},
                False,
                reason=f"revoked: {subscription.get('status') or 'unknown'}",
            )
            return

    def _record_keepalive(self):
        now = time.monotonic()
        self._last_keepalive_at = now
        self._keepalive_count_since_log += 1
        should_summarize = self._keepalive_count_since_log >= KEEPALIVE_SUMMARY_COUNT
        should_summarize = should_summarize or (
            self._keepalive_count_since_log > 1
            and now - self._last_keepalive_summary_at >= KEEPALIVE_SUMMARY_SECONDS
        )
        if should_summarize:
            self._flush_keepalive_summary(now=now)

    def _flush_keepalive_summary(self, *, now=None):
        if self._keepalive_count_since_log <= 0:
            return
        now = now or time.monotonic()
        self.logger(f"[EVENTSUB] Keepalive received x{self._keepalive_count_since_log}")
        self._keepalive_count_since_log = 0
        self._last_keepalive_summary_at = now

    def _log_rate_limited(self, key, message, *, interval=REPEATED_LOG_RATE_LIMIT_SECONDS):
        now = time.monotonic()
        last_logged_at = self._last_log_times.get(key, 0.0)
        suppressed = self._suppressed_log_counts.get(key, 0)
        if now - last_logged_at >= interval:
            suffix = f" (repeated x{suppressed + 1})" if suppressed else ""
            self.logger(f"{message}{suffix}")
            self._last_log_times[key] = now
            self._suppressed_log_counts[key] = 0
        else:
            self._suppressed_log_counts[key] = suppressed + 1

    def subscribe_all(self):
        for request in self.subscription_requests:
            try:
                self.subscribe_to_event(request)
            except Exception as exc:
                label = request.get("label") or request.get("type") or "unknown"
                reason = str(exc) or exc.__class__.__name__
                self.logger(f"[EVENTSUB] Subscribe exception for {label}: {reason}")
                self.emit_subscription_result(request, False, reason=reason)

    def subscription_retry_key(self, request):
        return json.dumps(
            {
                "type": request.get("type"),
                "version": request.get("version"),
                "condition": request.get("condition", {}),
            },
            sort_keys=True,
        )

    def response_failure_reason(self, response):
        try:
            payload = response.json()
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            message = str(payload.get("message") or payload.get("error") or "").strip()
            if message:
                return message
        return (response.text or f"HTTP {response.status_code}").strip()

    def emit_connection_status(self, state, message=""):
        if not callable(self.on_connection_status):
            return
        try:
            self.on_connection_status(state, message)
        except Exception as exc:
            self.logger("[EVENTSUB] Connection status callback failed:", exc)

    def emit_subscription_result(self, request, succeeded, *, reason="", response=None):
        if not callable(self.on_subscription_result):
            return
        try:
            self.on_subscription_result(
                request,
                succeeded,
                reason,
                getattr(response, "status_code", None),
                getattr(response, "text", "") or "",
            )
        except Exception as exc:
            self.logger("[EVENTSUB] Subscription result callback failed:", exc)

    def subscribe_to_event(self, request):
        condition = dict(request.get("condition", {}))
        body = {
            "type": request.get("type"),
            "version": request.get("version", "1"),
            "condition": condition,
            "transport": {
                "method": "websocket",
                "session_id": self.session_id,
            },
        }

        label = request.get("label") or body["type"]
        response = requests.post(
            HELIX_EVENTSUB_URL,
            headers=self._headers(),
            json=body,
            timeout=REQUEST_TIMEOUT,
        )

        retry_key = self.subscription_retry_key(body)
        response_text_lower = response.text.lower()
        should_cleanup_and_retry = (
            response.status_code in {409, 429}
            and (
                "maximum subscriptions with type and condition exceeded" in response_text_lower
                or "subscription already exists" in response_text_lower
                or "already exists" in response_text_lower
            )
        )
        if should_cleanup_and_retry:
            if retry_key not in self._subscribe_retry_cache:
                self._subscribe_retry_cache.add(retry_key)
                self.logger(f"[EVENTSUB] Duplicate subscription limit hit for {label}. Cleaning and retrying once.")
                deleted = self.cleanup_conflicting_subscriptions(body)
                self.logger(f"[EVENTSUB] Cleaned {deleted} conflicting subscription(s) for {label}")
                retry_response = requests.post(
                    HELIX_EVENTSUB_URL,
                    headers=self._headers(),
                    json=body,
                    timeout=REQUEST_TIMEOUT,
                )
                if retry_response.ok:
                    self.logger(f"[EVENTSUB] Subscription enabled: {label}")
                    self.emit_subscription_result(request, True, response=retry_response)
                    return True
                else:
                    reason = self.response_failure_reason(retry_response)
                    self.logger(f"[EVENTSUB] Subscription failed: {label}: {reason}")
                    self.emit_subscription_result(request, False, reason=reason, response=retry_response)
                    return False

        if response.ok:
            self.logger(f"[EVENTSUB] Subscription enabled: {label}")
            self.emit_subscription_result(request, True, response=response)
            return True
        else:
            reason = self.response_failure_reason(response)
            self.logger(f"[EVENTSUB] Subscription failed: {label}: {reason}")
            self.emit_subscription_result(request, False, reason=reason, response=response)
            return False

    def list_subscriptions(self):
        response = requests.get(
            HELIX_EVENTSUB_URL,
            headers=self._headers(),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("data", [])

    def delete_subscription(self, subscription_id):
        response = requests.delete(
            HELIX_EVENTSUB_URL,
            headers=self._headers(),
            params={"id": subscription_id},
            timeout=REQUEST_TIMEOUT,
        )
        self.logger(f"[EVENTSUB] Delete subscription {subscription_id}: {response.status_code}")
        if response.text:
            self.logger("[EVENTSUB] Delete response:", response.text)
        response.raise_for_status()

    def cleanup_conflicting_subscriptions(self, body):
        deleted = 0
        for subscription in self.list_subscriptions():
            condition = subscription.get("condition", {})
            transport = subscription.get("transport", {})
            is_same_condition = (
                subscription.get("type") == body.get("type")
                and condition == body.get("condition", {})
            )
            if not is_same_condition:
                continue

            same_session = transport.get("method") == "websocket" and transport.get("session_id") == self.session_id
            if same_session:
                continue

            self.logger(
                "[EVENTSUB] Removing conflicting subscription:",
                json.dumps(
                    {
                        "id": subscription.get("id"),
                        "type": subscription.get("type"),
                        "status": subscription.get("status"),
                        "transport": transport,
                        "condition": condition,
                    },
                    ensure_ascii=False,
                ),
            )
            self.delete_subscription(subscription.get("id"))
            deleted += 1

        return deleted

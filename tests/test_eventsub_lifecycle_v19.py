import json
import unittest
from unittest.mock import patch

from core.twitch_eventsub import EVENTSUB_WS_URL, TwitchEventSubClient


class FakeWebSocketApp:
    instances = []

    def __init__(self, url, on_open=None, on_message=None, on_error=None, on_close=None):
        self.url = url
        self.on_open = on_open
        self.on_message = on_message
        self.on_error = on_error
        self.on_close = on_close
        self.close_called = False
        self.run_called = False
        FakeWebSocketApp.instances.append(self)

    def run_forever(self, **_kwargs):
        self.run_called = True

    def close(self):
        self.close_called = True
        if callable(self.on_close):
            self.on_close(self, 1000, "closed")


def make_client(**kwargs):
    logs = []
    statuses = []
    chat_events = []
    alert_events = []
    client = TwitchEventSubClient(
        client_id="client",
        access_token="token",
        broadcaster_user_id="broadcaster",
        bot_user_id="bot",
        logger=lambda *parts: logs.append(" ".join(str(part) for part in parts)),
        on_connection_status=lambda state, message="": statuses.append((state, message)),
        on_chat_message=chat_events.append,
        on_event=lambda event_type, event, metadata: alert_events.append((event_type, event, metadata)),
        **kwargs,
    )
    return client, logs, statuses, chat_events, alert_events


def eventsub_message(message_type, payload=None, message_id="msg-1"):
    return json.dumps(
        {
            "metadata": {
                "message_type": message_type,
                "message_id": message_id,
            },
            "payload": payload or {},
        }
    )


class EventSubLifecycleV19Tests(unittest.TestCase):
    def setUp(self):
        FakeWebSocketApp.instances = []

    def test_session_reconnect_replaces_socket_without_old_close_status(self):
        client, logs, statuses, _chat_events, _alert_events = make_client()
        with patch("core.twitch_eventsub.websocket.WebSocketApp", FakeWebSocketApp):
            client.connect()
            first_ws = FakeWebSocketApp.instances[0]

            first_ws.on_message(
                first_ws,
                eventsub_message(
                    "session_reconnect",
                    {"session": {"reconnect_url": "wss://eventsub.example/reconnect"}},
                ),
            )

        self.assertEqual(len(FakeWebSocketApp.instances), 2)
        self.assertTrue(first_ws.close_called)
        self.assertEqual(FakeWebSocketApp.instances[1].url, "wss://eventsub.example/reconnect")
        self.assertIn(("[EVENTSUB] Reconnecting"), logs)
        self.assertIn(("reconnecting", "EventSub reconnect requested"), statuses)
        self.assertNotIn(("closed", "1000 closed"), statuses)

    def test_current_session_welcome_still_subscribes(self):
        client, logs, statuses, _chat_events, _alert_events = make_client()
        with patch("core.twitch_eventsub.websocket.WebSocketApp", FakeWebSocketApp), patch.object(
            client,
            "subscribe_all",
        ) as subscribe_all:
            client.connect()
            ws = FakeWebSocketApp.instances[0]
            ws.on_message(ws, eventsub_message("session_welcome", {"session": {"id": "session-1"}}))

        self.assertEqual(client.session_id, "session-1")
        subscribe_all.assert_called_once_with()
        self.assertIn("[EVENTSUB] Session ready", logs)
        self.assertIn(("ready", "EventSub session ready"), statuses)

    def test_old_socket_messages_are_ignored_after_reconnect(self):
        client, _logs, _statuses, chat_events, alert_events = make_client()
        with patch("core.twitch_eventsub.websocket.WebSocketApp", FakeWebSocketApp):
            client.connect()
            first_ws = FakeWebSocketApp.instances[0]
            first_ws.on_message(
                first_ws,
                eventsub_message(
                    "session_reconnect",
                    {"session": {"reconnect_url": "wss://eventsub.example/reconnect"}},
                ),
            )

            first_ws.on_message(
                first_ws,
                eventsub_message(
                    "notification",
                    {
                        "subscription": {"type": "channel.chat.message"},
                        "event": {"chatter_user_login": "old", "message": {"text": "late"}},
                    },
                    message_id="late-msg",
                ),
            )

        self.assertEqual(chat_events, [])
        self.assertEqual(alert_events, [])

    def test_stop_ignores_late_close_and_notifications(self):
        client, _logs, statuses, chat_events, alert_events = make_client()
        with patch("core.twitch_eventsub.websocket.WebSocketApp", FakeWebSocketApp):
            client.connect()
            ws = FakeWebSocketApp.instances[0]
            client.stop()
            ws.on_message(
                ws,
                eventsub_message(
                    "notification",
                    {
                        "subscription": {"type": "channel.chat.message"},
                        "event": {"chatter_user_login": "late", "message": {"text": "ignored"}},
                    },
                    message_id="late-msg",
                ),
            )

        self.assertTrue(ws.close_called)
        self.assertEqual(chat_events, [])
        self.assertEqual(alert_events, [])
        self.assertNotIn(("closed", "1000 closed"), statuses)

    def test_duplicate_reconnect_message_does_not_start_extra_socket(self):
        client, _logs, statuses, _chat_events, _alert_events = make_client()
        with patch("core.twitch_eventsub.websocket.WebSocketApp", FakeWebSocketApp):
            client.connect()
            first_ws = FakeWebSocketApp.instances[0]
            reconnect_payload = eventsub_message(
                "session_reconnect",
                {"session": {"reconnect_url": "wss://eventsub.example/reconnect"}},
            )
            first_ws.on_message(first_ws, reconnect_payload)
            first_ws.on_message(first_ws, reconnect_payload)

        self.assertEqual(len(FakeWebSocketApp.instances), 2)
        self.assertEqual(statuses.count(("reconnecting", "EventSub reconnect requested")), 1)

    def test_stop_during_reconnect_window_does_not_start_new_socket(self):
        client, _logs, _statuses, _chat_events, _alert_events = make_client()
        with patch("core.twitch_eventsub.websocket.WebSocketApp", FakeWebSocketApp):
            client.connect()
            first_ws = FakeWebSocketApp.instances[0]
            original_start = client._start_connection

            def stop_then_start(*, reset_stopped):
                client.stop()
                return original_start(reset_stopped=reset_stopped)

            with patch.object(client, "_start_connection", side_effect=stop_then_start):
                first_ws.on_message(
                    first_ws,
                    eventsub_message(
                        "session_reconnect",
                        {"session": {"reconnect_url": "wss://eventsub.example/reconnect"}},
                    ),
                )

        self.assertEqual(len(FakeWebSocketApp.instances), 1)
        self.assertTrue(first_ws.close_called)

    def test_current_reconnect_socket_reports_success_once(self):
        client, logs, statuses, _chat_events, _alert_events = make_client()
        with patch("core.twitch_eventsub.websocket.WebSocketApp", FakeWebSocketApp):
            client.connect()
            first_ws = FakeWebSocketApp.instances[0]
            first_ws.on_message(
                first_ws,
                eventsub_message(
                    "session_reconnect",
                    {"session": {"reconnect_url": "wss://eventsub.example/reconnect"}},
                ),
            )
            second_ws = FakeWebSocketApp.instances[1]
            second_ws.on_open(second_ws)

        self.assertEqual(FakeWebSocketApp.instances[0].url, EVENTSUB_WS_URL)
        self.assertIn("[EVENTSUB] Reconnect success", logs)
        self.assertIn(("connected", "WebSocket connected"), statuses)


if __name__ == "__main__":
    unittest.main()

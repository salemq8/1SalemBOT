import unittest
from unittest.mock import patch

from core.app_state import default_dashboard_state
from core.eventsub_bot import create_message_handler


class FakeAIResponse:
    output_text = "hello back"


class FakeAIResponses:
    def create(self, **_kwargs):
        return FakeAIResponse()


class FakeAIClient:
    responses = FakeAIResponses()


class ViewerMessageCountingTests(unittest.TestCase):
    def setUp(self):
        self.user_profiles = {}
        self.dashboard_state = default_dashboard_state()
        self.sent_replies = []

        self.patches = [
            patch("core.eventsub_bot.save_user_profiles"),
            patch("core.eventsub_bot.save_dashboard_state"),
            patch("core.eventsub_bot.get_configured_music_command_aliases", return_value=[]),
            patch("core.eventsub_bot.is_music_enabled", return_value=True),
            patch("core.eventsub_bot.write_music_command"),
            patch("core.eventsub_bot.safe_print"),
        ]
        self.mocks = [patcher.start() for patcher in self.patches]
        self.addCleanup(self.stop_patches)

        self.write_music_command = self.mocks[4]
        self.safe_print = self.mocks[5]

        self.handler = create_message_handler(
            "twitch",
            "1SalemGPT",
            ["bot"],
            FakeAIClient(),
            self.user_profiles,
            self.dashboard_state,
            "system prompt",
            send_reply=lambda reply, username, cleaned_text, message_id=None: self.sent_replies.append(
                {
                    "reply": reply,
                    "username": username,
                    "cleaned_text": cleaned_text,
                    "message_id": message_id,
                }
            ),
        )

    def stop_patches(self):
        for patcher in reversed(self.patches):
            patcher.stop()

    def test_normal_chat_message_increments_viewer_count(self):
        self.handler("hayouna6", "hello chat", message_id="msg-normal-1")

        self.assertEqual(self.user_profiles["hayouna6"]["messages"], 1)
        self.assertEqual(self.user_profiles["hayouna6"]["last_message"], "hello chat")
        self.safe_print.assert_any_call("[VIEWERS] Counted message from hayouna6")

    def test_bot_addressed_message_increments_once(self):
        self.handler("hayouna6", "1SalemGPT hello", message_id="msg-addressed-1")

        self.assertEqual(self.user_profiles["hayouna6"]["messages"], 1)
        self.assertEqual(len(self.sent_replies), 1)

    def test_song_request_command_increments_once(self):
        self.handler("hayouna6", "!sr song name", message_id="msg-sr-1")

        self.assertEqual(self.user_profiles["hayouna6"]["messages"], 1)
        self.write_music_command.assert_called_once()
        self.assertEqual(len(self.sent_replies), 1)

    def test_bot_own_messages_are_ignored(self):
        self.handler("1SalemGPT", "hello from bot", message_id="msg-self-1")

        self.assertEqual(self.user_profiles, {})
        self.assertEqual(self.dashboard_state["messages_today"], 0)

    def test_duplicate_message_id_is_not_counted_twice(self):
        self.handler("hayouna6", "first copy", message_id="msg-duplicate-1")
        self.handler("hayouna6", "retry copy", message_id="msg-duplicate-1")

        self.assertEqual(self.user_profiles["hayouna6"]["messages"], 1)
        self.assertEqual(self.dashboard_state["messages_today"], 1)
        self.safe_print.assert_any_call("[VIEWERS] Ignored duplicate message from hayouna6")


if __name__ == "__main__":
    unittest.main()

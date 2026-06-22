import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.app_state import default_dashboard_state, load_json, save_json
from core.chat_persistence import ChatPersistenceManager
from core.eventsub_bot import create_message_handler


class ChatPersistenceBatchingTests(unittest.TestCase):
    def make_handler(self, manager, user_profiles, dashboard_state):
        return create_message_handler(
            "twitch",
            "1SalemGPT",
            ["bot"],
            ai_client=None,
            user_profiles=user_profiles,
            dashboard_state=dashboard_state,
            system_prompt="system prompt",
            send_reply=lambda *_args, **_kwargs: None,
            persistence=manager,
        )

    def test_normal_chat_messages_batch_users_and_dashboard_saves(self):
        user_profiles = {}
        dashboard_state = default_dashboard_state()
        saved_users = []
        saved_dashboard = []
        manager = ChatPersistenceManager(
            user_profiles,
            dashboard_state,
            save_users_func=lambda payload: saved_users.append(copy.deepcopy(payload)) or True,
            save_dashboard_func=lambda payload: saved_dashboard.append(copy.deepcopy(payload)) or True,
            autostart=False,
        )

        with patch("core.eventsub_bot.safe_print"), patch("core.eventsub_bot.get_configured_music_command_aliases", return_value=[]):
            handler = self.make_handler(manager, user_profiles, dashboard_state)
            for index in range(5):
                handler("hayouna6", f"hello {index}", message_id=f"msg-{index}")

        self.assertEqual(user_profiles["hayouna6"]["messages"], 5)
        self.assertEqual(dashboard_state["messages_today"], 5)
        self.assertEqual(len(saved_users), 0)
        self.assertEqual(len(saved_dashboard), 0)

        manager.flush_now()

        self.assertEqual(len(saved_users), 1)
        self.assertEqual(len(saved_dashboard), 1)
        self.assertEqual(saved_users[-1]["hayouna6"]["messages"], 5)
        self.assertEqual(saved_dashboard[-1]["messages_today"], 5)

    def test_shutdown_flush_persists_dirty_chat_state(self):
        user_profiles = {}
        dashboard_state = default_dashboard_state()

        with tempfile.TemporaryDirectory() as temp_dir:
            users_path = Path(temp_dir) / "users.json"
            dashboard_path = Path(temp_dir) / "dashboard_state.json"
            manager = ChatPersistenceManager(
                user_profiles,
                dashboard_state,
                save_users_func=lambda payload: save_json(users_path, payload),
                save_dashboard_func=lambda payload: save_json(dashboard_path, payload),
                autostart=False,
            )

            with patch("core.eventsub_bot.safe_print"), patch("core.eventsub_bot.get_configured_music_command_aliases", return_value=[]):
                handler = self.make_handler(manager, user_profiles, dashboard_state)
                handler("hayouna6", "normal chat", message_id="msg-1")

            manager.shutdown()

            self.assertEqual(load_json(users_path, {})["hayouna6"]["messages"], 1)
            self.assertEqual(load_json(dashboard_path, {})["messages_today"], 1)

    def test_duplicate_message_id_is_not_marked_dirty_twice(self):
        user_profiles = {}
        dashboard_state = default_dashboard_state()
        saved_users = []
        saved_dashboard = []
        manager = ChatPersistenceManager(
            user_profiles,
            dashboard_state,
            save_users_func=lambda payload: saved_users.append(copy.deepcopy(payload)) or True,
            save_dashboard_func=lambda payload: saved_dashboard.append(copy.deepcopy(payload)) or True,
            autostart=False,
        )

        with patch("core.eventsub_bot.safe_print"), patch("core.eventsub_bot.get_configured_music_command_aliases", return_value=[]):
            handler = self.make_handler(manager, user_profiles, dashboard_state)
            handler("hayouna6", "first copy", message_id="same-message")
            handler("hayouna6", "retry copy", message_id="same-message")

        manager.flush_now()

        self.assertEqual(user_profiles["hayouna6"]["messages"], 1)
        self.assertEqual(dashboard_state["messages_today"], 1)
        self.assertEqual(len(saved_users), 1)
        self.assertEqual(len(saved_dashboard), 1)

    def test_high_volume_chat_messages_flush_once_per_file(self):
        user_profiles = {}
        dashboard_state = default_dashboard_state()
        saved_users = []
        saved_dashboard = []
        manager = ChatPersistenceManager(
            user_profiles,
            dashboard_state,
            save_users_func=lambda payload: saved_users.append(copy.deepcopy(payload)) or True,
            save_dashboard_func=lambda payload: saved_dashboard.append(copy.deepcopy(payload)) or True,
            autostart=False,
        )

        with patch("core.eventsub_bot.safe_print"), patch("core.eventsub_bot.get_configured_music_command_aliases", return_value=[]):
            handler = self.make_handler(manager, user_profiles, dashboard_state)
            for index in range(1000):
                username = f"viewer{index % 25:02d}"
                handler(username, f"normal chat {index}", message_id=f"bulk-{index}")

        self.assertEqual(sum(profile.get("messages", 0) for profile in user_profiles.values()), 1000)
        self.assertEqual(dashboard_state["messages_today"], 1000)
        self.assertEqual(len(saved_users), 0)
        self.assertEqual(len(saved_dashboard), 0)

        flushed = manager.flush_now()

        self.assertEqual(flushed, {"users": True, "dashboard": True})
        self.assertEqual(len(saved_users), 1)
        self.assertEqual(len(saved_dashboard), 1)
        self.assertEqual(sum(profile.get("messages", 0) for profile in saved_users[-1].values()), 1000)
        self.assertEqual(saved_dashboard[-1]["messages_today"], 1000)


if __name__ == "__main__":
    unittest.main()

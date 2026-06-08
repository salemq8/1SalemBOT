import unittest

from core.ui.viewers_mixin import DashboardViewersMixin


class ViewerSortHarness(DashboardViewersMixin):
    viewer_sort_key = "newest"

    def parse_profile_timestamp(self, raw_value):
        return None


class ViewerRoleSortTests(unittest.TestCase):
    def test_viewer_list_prioritizes_messages_then_roles(self):
        app = ViewerSortHarness()
        records = [
            {"username": "sub_high", "role": "Subscriber", "messages": 999, "last_seen": ""},
            {"username": "viewer_high", "role": "Viewer", "messages": 1200, "last_seen": ""},
            {"username": "vip_low", "role": "VIP", "messages": 3, "last_seen": ""},
            {"username": "mod_low", "role": "Mod", "messages": 2, "last_seen": ""},
            {"username": "owner_low", "role": "Owner", "messages": 1, "last_seen": ""},
            {"username": "bot_low", "role": "Bot", "messages": 5, "last_seen": ""},
            {"username": "sub_mid", "role": "Subscriber", "messages": 50, "last_seen": ""},
            {"username": "lead_mod_low", "role": "Lead Moderator", "messages": 4, "last_seen": ""},
        ]

        sorted_records = app.sort_viewer_records(records)

        self.assertEqual(
            [record["username"] for record in sorted_records],
            ["viewer_high", "sub_high", "sub_mid", "bot_low", "lead_mod_low", "vip_low", "mod_low", "owner_low"],
        )

    def test_same_message_count_uses_role_priority(self):
        app = ViewerSortHarness()
        records = [
            {"username": "subscriber", "role": "Subscriber", "messages": 10, "last_seen": ""},
            {"username": "moderator", "role": "Mod", "messages": 10, "last_seen": ""},
            {"username": "lead", "role": "Lead Moderator", "messages": 10, "last_seen": ""},
            {"username": "owner", "role": "Owner", "messages": 10, "last_seen": ""},
            {"username": "viewer", "role": "Viewer", "messages": 10, "last_seen": ""},
            {"username": "vip", "role": "VIP", "messages": 10, "last_seen": ""},
            {"username": "bot", "role": "Bot", "messages": 10, "last_seen": ""},
        ]

        sorted_records = app.sort_viewer_records(records)

        self.assertEqual(
            [record["username"] for record in sorted_records],
            ["owner", "lead", "moderator", "vip", "bot", "subscriber", "viewer"],
        )

    def test_lead_moderator_badge_overrides_subscriber(self):
        app = ViewerSortHarness()

        role = app.derive_badge_role(
            [
                {"set_id": "subscriber", "id": "12", "info": ""},
                {"set_id": "lead_moderator", "id": "1", "info": ""},
            ]
        )

        self.assertEqual(role, "Lead Moderator")
        self.assertLess(app.role_sort_rank("Lead Moderator"), app.role_sort_rank("Mod"))

    def test_recent_chat_lookup_preserves_lead_moderator_role(self):
        app = ViewerSortHarness()
        app.users_data = {"salem": {"messages": 401}}
        app.dashboard_state = {
            "recent_chat": [
                {
                    "user": "salem",
                    "badges": [
                        {"set_id": "subscriber", "id": "24", "info": ""},
                        {"set_id": "moderator", "id": "lead", "info": "Lead Moderator"},
                    ],
                }
            ]
        }

        self.assertEqual(app.build_viewer_role_lookup()["salem"], "Lead Moderator")


if __name__ == "__main__":
    unittest.main()

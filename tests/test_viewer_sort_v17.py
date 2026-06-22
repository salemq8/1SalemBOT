import unittest

from PySide6.QtWidgets import QApplication

from core.ui.viewers_mixin import DashboardViewersMixin
from core.ui.widgets import IncrementalTableModel


def app_instance():
    return QApplication.instance() or QApplication([])


class ViewerSortHarness(DashboardViewersMixin):
    viewer_sort_key = "newest"

    def parse_profile_timestamp(self, raw_value):
        return None

    def localize(self, text, **params):
        try:
            return str(text).format(**params)
        except Exception:
            return str(text)

    def set_localized_text(self, widget, text, **params):
        if widget is not None:
            widget.setText(self.localize(text, **params))

    def _set_i18n_source(self, *_args, **_kwargs):
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

    def test_product_tester_sorts_between_vip_and_bot(self):
        app = ViewerSortHarness()

        self.assertLess(app.role_sort_rank("VIP"), app.role_sort_rank("Product Tester"))
        self.assertLess(app.role_sort_rank("Product Tester"), app.role_sort_rank("Bot"))
        self.assertEqual(app.derive_badge_role([{"set_id": "product-tester", "id": "1"}]), "Product Tester")

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

    def test_recent_chat_role_lookup_normalizes_username_case(self):
        app = ViewerSortHarness()
        app.users_data = {"salem": {"messages": 3}}
        app.dashboard_state = {
            "recent_chat": [
                {
                    "user": "Salem",
                    "badges": [{"set_id": "vip", "id": "1", "info": ""}],
                }
            ]
        }

        records = app.build_viewer_records()

        self.assertEqual(records[0]["role"], "VIP")

    def test_relationship_pagination_uses_plural_model_attribute(self):
        app_instance()
        app = ViewerSortHarness()
        app.viewer_relationships_model = IncrementalTableModel(("Account", "Details", "When"), batch_size=10)
        app.viewer_relationship_page_size = 2
        app.viewer_relationship_current_page = 1
        app.viewer_relationship_total_pages = 1
        app.viewer_relationship_current_rows = []
        app.viewer_relationship_rows_cache = {
            "Followers": [
                ("one", "Follower", "now"),
                ("two", "Follower", "now"),
                ("three", "Follower", "now"),
            ]
        }
        app.viewer_relationships_state = {}
        app.viewer_list_category = "Followers"
        app.viewer_list_category_buttons = {}
        app.viewer_relationships_request_inflight = False

        app.refresh_viewer_relationships_panel()
        app.set_relationship_page(2)

        self.assertFalse(hasattr(app, "viewer_relationship_model"))
        self.assertEqual(app.viewer_relationship_current_page, 2)
        self.assertEqual(app.viewer_relationships_model.rowCount(), 1)

    def test_relationship_pagination_loading_click_is_ignored(self):
        app_instance()
        app = ViewerSortHarness()
        app.viewer_relationships_model = IncrementalTableModel(("Account", "Details", "When"), batch_size=10)
        app.viewer_relationship_current_page = 1
        app.viewer_relationship_total_pages = 3
        app.viewer_relationships_request_inflight = True

        app.set_relationship_page(3)

        self.assertEqual(app.viewer_relationship_current_page, 1)

    def test_relationship_page_clamps_after_rows_shrink(self):
        app_instance()
        app = ViewerSortHarness()
        app.viewer_relationships_model = IncrementalTableModel(("Account", "Details", "When"), batch_size=10)
        app.viewer_relationship_page_size = 10
        app.viewer_relationship_current_page = 5
        app.viewer_relationship_total_pages = 5

        app.populate_relationship_table([("only", "Follower", "now")])

        self.assertEqual(app.viewer_relationship_current_page, 1)
        self.assertEqual(app.viewer_relationship_total_pages, 1)


if __name__ == "__main__":
    unittest.main()

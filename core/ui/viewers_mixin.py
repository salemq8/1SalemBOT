import threading
import time
import webbrowser
from datetime import datetime, timezone

from PySide6.QtCore import QEasingCurve, QModelIndex, QPropertyAnimation, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QGridLayout, QHeaderView, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableView, QVBoxLayout, QWidget

from core.alert_storage import add_alert_items, build_new_follower_alerts, build_new_subscription_alerts
from core.app_paths import ALERTS_FILE, SETTINGS_FILE, VIEWER_RELATIONSHIPS_FILE
from core.app_state import default_viewer_relationships_state, load_json, save_json
from core.auth import CHANNEL_AUTH_ROLE, CLIENT_ID, load_best_token, load_token_details
from core.chat_storage import get_recent_user_only_messages, save_user_profiles
from core.twitch_api import (
    get_all_broadcaster_subscriptions,
    get_all_channel_followers,
    get_all_followed_channels,
    get_stream_by_user_login,
    get_users_by_ids,
    get_users_by_logins,
)
from .widgets import AnalyticsChartWidget, Card, IncrementalTableModel


class DashboardViewersMixin:
    def make_viewer_filter_button(self, name):
        button = QPushButton(self.localize(name))
        self._set_i18n_source(button, name)
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        button.setMinimumHeight(30)
        button.clicked.connect(lambda checked=False, filter_name=name: self.set_viewer_filter(filter_name))
        self.viewer_filter_buttons[name] = button
        return button
    def build_viewer_summary_card(self, title, value_ref_name, detail_ref_name):
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(6)

        title_label = QLabel(self.localize(title))
        self._set_i18n_source(title_label, title)
        self.set_label_role(title_label, "smallTitle")
        value_label = QLabel("--")
        self.set_label_role(value_label, "statValue")
        value_label.setMinimumHeight(38)
        detail_label = QLabel("")
        detail_label.setWordWrap(True)
        self.set_label_role(detail_label, "mutedBody")

        setattr(self, value_ref_name, value_label)
        setattr(self, detail_ref_name, detail_label)

        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addWidget(detail_label)
        layout.addStretch()
        return card
    def parse_profile_timestamp(self, raw_value):
        value = (raw_value or "").strip()
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None
    def format_last_active_display(self, raw_value):
        parsed = self.parse_profile_timestamp(raw_value)
        if parsed is None:
            return "No activity yet"
        return parsed.strftime("%Y-%m-%d %H:%M")
    def format_relative_activity(self, raw_value):
        parsed = self.parse_profile_timestamp(raw_value)
        if parsed is None:
            return "No recent activity"

        elapsed_seconds = max(int((datetime.now() - parsed).total_seconds()), 0)
        if elapsed_seconds < 60:
            return "Just now"
        if elapsed_seconds < 3600:
            minutes = elapsed_seconds // 60
            return f"{minutes}m ago"
        if elapsed_seconds < 86400:
            hours = elapsed_seconds // 3600
            return f"{hours}h ago"
        days = elapsed_seconds // 86400
        return f"{days}d ago"
    def format_stream_uptime(self, started_at):
        if not started_at:
            return "--"
        try:
            started = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
            elapsed = datetime.now(timezone.utc) - started
            total_seconds = max(int(elapsed.total_seconds()), 0)
        except Exception:
            return "--"

        hours, remainder = divmod(total_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if hours:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"
    def derive_badge_role(self, badges):
        role_priority = {
            "broadcaster": ("Broadcaster", 4),
            "moderator": ("Mod", 3),
            "vip": ("VIP", 2),
            "subscriber": ("Subscriber", 1),
            "founder": ("Subscriber", 1),
        }
        best_role = ("Viewer", 0)
        for badge in badges or []:
            if isinstance(badge, dict):
                badge_key = (badge.get("set_id") or "").strip().lower()
            else:
                badge_key = str(badge).strip().lower()
            candidate = role_priority.get(badge_key)
            if candidate and candidate[1] > best_role[1]:
                best_role = candidate
        return best_role[0]
    def build_viewer_role_lookup(self):
        role_lookup = {}
        role_priority = {"Viewer": 0, "Subscriber": 1, "VIP": 2, "Mod": 3, "Broadcaster": 4}

        for username, profile in self.users_data.items():
            manual_role = (profile.get("manual_role") or "").strip()
            if manual_role:
                role_lookup[username] = manual_role

        for entry in self.dashboard_state.get("recent_chat", []):
            username = (entry.get("user") or "").strip()
            if not username:
                continue
            detected_role = self.derive_badge_role(entry.get("badges", []))
            if role_priority.get(detected_role, 0) >= role_priority.get(role_lookup.get(username, "Viewer"), 0):
                role_lookup[username] = detected_role

        return role_lookup
    def derive_viewer_activity_state(self, profile):
        if profile.get("muted"):
            return "Muted"

        parsed = self.parse_profile_timestamp(profile.get("last_seen", ""))
        if parsed is None:
            return "Lurking"

        elapsed_seconds = max((datetime.now() - parsed).total_seconds(), 0)
        if elapsed_seconds <= 600:
            return "Active now"
        if elapsed_seconds <= 3600:
            return "Active"
        return "Lurking"
    def viewer_matches_filter(self, record):
        filter_name = self.viewer_filter_name
        if filter_name == "All":
            return True
        if filter_name == "Active":
            return record["activity"] in {"Active now", "Active"}
        if filter_name == "Mods":
            return record["role"] in {"Mod", "Broadcaster"}
        if filter_name == "VIP":
            return record["role"] == "VIP"
        if filter_name == "Lurkers":
            return record["activity"] == "Lurking"
        return True
    def role_sort_rank(self, role_name):
        return {
            "Broadcaster": 0,
            "Mod": 1,
            "VIP": 2,
            "Subscriber": 3,
            "Viewer": 3,
        }.get(str(role_name or "").strip(), 3)
    def parse_viewer_sort_timestamp(self, raw_value):
        parsed = self.parse_profile_timestamp(raw_value)
        if parsed is None:
            return 0.0
        return parsed.timestamp()
    def sort_viewer_records(self, records):
        items = list(records or [])
        sort_key = getattr(self, "viewer_sort_key", "newest")
        if sort_key == "messages":
            items.sort(
                key=lambda item: (
                    -int(item.get("messages", 0) or 0),
                    item.get("username", "").lower(),
                )
            )
        elif sort_key == "oldest":
            items.sort(
                key=lambda item: (
                    self.parse_viewer_sort_timestamp(item.get("last_seen", "")),
                    -int(item.get("messages", 0) or 0),
                    item.get("username", "").lower(),
                )
            )
        elif sort_key == "role":
            items.sort(
                key=lambda item: (
                    self.role_sort_rank(item.get("role", "")),
                    -int(item.get("messages", 0) or 0),
                    item.get("username", "").lower(),
                )
            )
        else:
            items.sort(
                key=lambda item: (
                    -self.parse_viewer_sort_timestamp(item.get("last_seen", "")),
                    -int(item.get("messages", 0) or 0),
                    item.get("username", "").lower(),
                )
            )
        return items
    def parse_relationship_sort_timestamp(self, item, category):
        if category == "Followers":
            raw_value = item.get("followed_at", "")
        elif category == "Unfollowers":
            raw_value = item.get("removed_at", "")
        elif category == "Unsubscribers":
            raw_value = item.get("removed_at", "")
        elif category == "Channels Followed":
            raw_value = item.get("followed_at", "")
        else:
            raw_value = item.get("followed_at", "") or item.get("removed_at", "")

        value = str(raw_value or "").strip()
        if not value:
            return 0.0
        for candidate in (value.replace("Z", "+00:00"), value):
            try:
                return datetime.fromisoformat(candidate).timestamp()
            except Exception:
                continue
        return 0.0
    def relationship_item_username(self, item, category):
        if category == "Channels Followed":
            return str(item.get("broadcaster_name") or item.get("broadcaster_login") or "Unknown")
        return str(item.get("user_name") or item.get("user_login") or "Unknown")
    def relationship_item_role(self, item, category):
        if category == "Channels Followed":
            return "Viewer"
        role_lookup = self.build_viewer_role_lookup()
        username = str(item.get("user_name") or item.get("user_login") or "").strip()
        return role_lookup.get(username, "Viewer")
    def sort_relationship_items(self, items, category):
        rows = list(items or [])
        sort_key = getattr(self, "relationship_sort_key", "newest")
        if sort_key == "oldest":
            rows.sort(
                key=lambda item: (
                    self.parse_relationship_sort_timestamp(item, category),
                    self.relationship_item_username(item, category).lower(),
                )
            )
        elif sort_key == "role":
            rows.sort(
                key=lambda item: (
                    self.role_sort_rank(self.relationship_item_role(item, category)),
                    -self.parse_relationship_sort_timestamp(item, category),
                    self.relationship_item_username(item, category).lower(),
                )
            )
        else:
            rows.sort(
                key=lambda item: (
                    -self.parse_relationship_sort_timestamp(item, category),
                    self.relationship_item_username(item, category).lower(),
                )
            )
        return rows
    def on_viewer_sort_changed(self, index):
        if index < 0 or not hasattr(self, "viewer_sort_selector"):
            return
        sort_key = self.viewer_sort_selector.itemData(index)
        if not sort_key or sort_key == getattr(self, "viewer_sort_key", "newest"):
            return
        self.viewer_sort_key = str(sort_key)
        self.settings["viewer_sort"] = self.viewer_sort_key
        save_json(SETTINGS_FILE, self.settings)
        self.refresh_viewers_dashboard()
    def on_relationship_sort_changed(self, index):
        if index < 0 or not hasattr(self, "relationship_sort_selector"):
            return
        sort_key = self.relationship_sort_selector.itemData(index)
        if not sort_key or sort_key == getattr(self, "relationship_sort_key", "newest"):
            return
        self.relationship_sort_key = str(sort_key)
        self.viewer_relationship_current_page = 1
        self.viewer_relationship_rows_cache = {}
        self.settings["relationship_sort"] = self.relationship_sort_key
        save_json(SETTINGS_FILE, self.settings)
        self.refresh_viewer_relationships_panel()
    def build_viewer_records(self):
        role_lookup = self.build_viewer_role_lookup()
        records = []
        for username, profile in self.users_data.items():
            records.append(
                {
                    "username": username,
                    "messages": int(profile.get("messages", 0) or 0),
                    "role": role_lookup.get(username, "Viewer"),
                    "activity": self.derive_viewer_activity_state(profile),
                    "last_seen": profile.get("last_seen", ""),
                    "behavior": profile.get("behavior", "neutral"),
                    "notes": profile.get("notes", "not enough information yet"),
                    "muted": bool(profile.get("muted", False)),
                }
            )

        records.sort(key=lambda item: (-item["messages"], item["username"].lower()))
        return records
    def build_default_stream_summary(self):
        tracked_viewers = len(self.users_data)
        active_viewers = sum(
            1 for profile in self.users_data.values() if self.derive_viewer_activity_state(profile) in {"Active now", "Active"}
        )
        return {
            "viewer_count": 0,
            "viewer_detail_key": "viewers.tracked_count",
            "viewer_detail_params": {"count": f"{tracked_viewers:,}"},
            "status_text": "Offline",
            "status_tone": "warning",
            "status_detail": "No live stream detected right now",
            "uptime": "--",
            "uptime_detail_key": "viewers.active_chatters_count",
            "uptime_detail_params": {"count": f"{active_viewers:,}"},
        }
    def request_stream_summary_refresh(self, force=False):
        if not hasattr(self, "viewer_summary_count_value"):
            return
        if not self.is_bot_process_running():
            self._apply_stream_summary(self.build_default_stream_summary())
            return

        channel_login = self.current_channel_login().strip()
        if not channel_login:
            self._apply_stream_summary(self.build_default_stream_summary())
            return

        if self.stream_summary_request_inflight:
            return

        now = time.time()
        if not force and self.stream_summary_cache and (now - self.stream_summary_last_fetch_at) < 60:
            self._apply_stream_summary(dict(self.stream_summary_cache))
            return

        token = load_best_token()
        if not token:
            self._apply_stream_summary(self.build_default_stream_summary())
            return

        self.stream_summary_request_inflight = True

        def worker():
            summary = self.build_default_stream_summary()
            try:
                stream = get_stream_by_user_login(CLIENT_ID, token, channel_login)
                if stream:
                    summary = {
                        "viewer_count": int(stream.get("viewer_count", 0) or 0),
                        "viewer_detail_key": "viewers.live_for",
                        "viewer_detail_params": {"channel": channel_login},
                        "status_text": "Online",
                        "status_tone": "success",
                        "status_detail": (stream.get("title") or "Stream is live right now")[:96],
                        "status_detail_dynamic": bool(stream.get("title")),
                        "uptime": self.format_stream_uptime(stream.get("started_at")),
                        "uptime_detail": "Time since stream start",
                    }
            except Exception as exc:
                summary["status_detail"] = f"Could not refresh Twitch stream info: {exc}"
            self.bridge.stream_summary_signal.emit(summary)

        threading.Thread(target=worker, daemon=True).start()
    def _apply_stream_summary(self, summary):
        self.stream_summary_request_inflight = False
        self.stream_summary_last_fetch_at = time.time()
        self.stream_summary_cache = dict(summary or {})

        if hasattr(self, "viewer_summary_count_value"):
            self.viewer_summary_count_value.setText(str(summary.get("viewer_count", 0)))
        if hasattr(self, "viewer_summary_count_detail"):
            if summary.get("viewer_detail_key"):
                self.set_localized_text(
                    self.viewer_summary_count_detail,
                    summary.get("viewer_detail_key"),
                    **dict(summary.get("viewer_detail_params") or {}),
                )
            else:
                self.set_localized_text(self.viewer_summary_count_detail, summary.get("viewer_detail", ""))
        if hasattr(self, "viewer_summary_status_value"):
            self.set_localized_text(self.viewer_summary_status_value, summary.get("status_text", "Offline"))
            tone = summary.get("status_tone", "warning")
            self.set_status_value_style(self.viewer_summary_status_value, tone)
        if hasattr(self, "viewer_summary_status_detail"):
            if summary.get("status_detail_dynamic"):
                self.set_dynamic_text(self.viewer_summary_status_detail, summary.get("status_detail", ""))
            else:
                self.set_localized_text(self.viewer_summary_status_detail, summary.get("status_detail", ""))
        if hasattr(self, "viewer_summary_uptime_value"):
            self.viewer_summary_uptime_value.setText(summary.get("uptime", "--"))
        if hasattr(self, "viewer_summary_uptime_detail"):
            if summary.get("uptime_detail_key"):
                self.set_localized_text(
                    self.viewer_summary_uptime_detail,
                    summary.get("uptime_detail_key"),
                    **dict(summary.get("uptime_detail_params") or {}),
                )
            else:
                self.set_localized_text(self.viewer_summary_uptime_detail, summary.get("uptime_detail", ""))
    def normalize_viewer_relationships_state(self, state):
        baseline = default_viewer_relationships_state()
        normalized = dict(baseline)
        if isinstance(state, dict):
            normalized.update(state)
        for key in (
            "followers_snapshot",
            "unfollowers",
            "subscriptions_snapshot",
            "unsubscribers",
            "followed_channels_snapshot",
        ):
            value = normalized.get(key)
            normalized[key] = value if isinstance(value, list) else []
        normalized["last_synced_at"] = str(normalized.get("last_synced_at", "") or "")
        normalized["last_error"] = str(normalized.get("last_error", "") or "")
        return normalized
    def save_viewer_relationships_state(self):
        self.viewer_relationships_state = self.normalize_viewer_relationships_state(self.viewer_relationships_state)
        save_json(VIEWER_RELATIONSHIPS_FILE, self.viewer_relationships_state)
    def make_viewer_list_category_button(self, name):
        button = QPushButton(self.localize(name))
        self._set_i18n_source(button, name)
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        button.setMinimumHeight(34)
        button.clicked.connect(lambda checked=False, category=name: self.set_viewer_list_category(category))
        self.viewer_list_category_buttons[name] = button
        return button
    def sync_viewer_list_category_buttons(self):
        counts = self.get_viewer_relationship_counts()
        for category, button in self.viewer_list_category_buttons.items():
            active = category == self.viewer_list_category
            count = counts.get(category, 0)
            self.set_localized_text(
                button,
                "filters.category_count",
                category=self.localize(category),
                count=f"{count:,}",
            )
            if active:
                background = self.theme.nav_active_bg
                border = self.theme.nav_active_border
                color = self.theme.nav_active_text
            else:
                background = self.theme.subtle_bg
                border = self.theme.subtle_border
                color = self.theme.text_secondary
            button.setStyleSheet(
                f"""
                QPushButton {{
                    background: {background};
                    color: {color};
                    border: 1px solid {border};
                    border-radius: 10px;
                    padding: 7px 12px;
                    text-align: {'right' if self.is_rtl_language() else 'left'};
                    font-size: 12px;
                    font-weight: 700;
                }}
                QPushButton:hover {{
                    background: {self.theme.nav_hover_bg};
                    border-color: {self.theme.nav_hover_border};
                    color: {self.theme.text_primary};
                }}
                """
            )
            button.blockSignals(True)
            button.setChecked(active)
            button.blockSignals(False)
    def get_viewer_relationship_counts(self):
        state = self.normalize_viewer_relationships_state(self.viewer_relationships_state)
        return {
            "Followers": len(state.get("followers_snapshot", [])),
            "Unfollowers": len(state.get("unfollowers", [])),
            "Subscribers": len(state.get("subscriptions_snapshot", [])),
            "Unsubscribers": len(state.get("unsubscribers", [])),
            "Channels Followed": len(state.get("followed_channels_snapshot", [])),
        }
    def set_viewer_list_category(self, category):
        if category == self.viewer_list_category:
            return
        self.viewer_list_category = category
        self.viewer_relationship_current_page = 1
        self.sync_viewer_list_category_buttons()
        self.refresh_viewer_relationships_panel()
    def format_relationship_time(self, raw_value):
        value = (raw_value or "").strip()
        if not value:
            return "--"
        for candidate in (value.replace("Z", "+00:00"), value):
            try:
                parsed = datetime.fromisoformat(candidate)
                return parsed.strftime("%Y-%m-%d %H:%M")
            except Exception:
                continue
        return value
    def format_subscription_tier(self, tier):
        tier_value = str(tier or "").strip()
        mapping = {"1000": "Tier 1", "2000": "Tier 2", "3000": "Tier 3"}
        return mapping.get(tier_value, tier_value or "Subscription")
    def build_relationship_rows(self, category):
        state = self.normalize_viewer_relationships_state(self.viewer_relationships_state)
        rows = []
        if category == "Followers":
            for item in self.sort_relationship_items(state.get("followers_snapshot", []), category):
                rows.append(
                    (
                        item.get("user_name") or item.get("user_login") or "Unknown",
                        "Follower",
                        self.format_relationship_time(item.get("followed_at", "")),
                    )
                )
        elif category == "Unfollowers":
            for item in self.sort_relationship_items(state.get("unfollowers", []), category):
                username = item.get("user_name") or item.get("user_login") or "Unknown"
                status = item.get("status") or "Unfollowed"
                profile_url = (item.get("profile_url") or "").strip()
                account_available = bool(item.get("account_available")) and bool(profile_url)
                status_color = {
                    "Unfollowed": self.theme.success,
                    "Account Closed": self.theme.warning,
                    "Account Unavailable": self.theme.text_muted,
                }.get(status, self.theme.text_secondary)
                rows.append(
                    self.make_incremental_table_row(
                        (
                            username,
                            status,
                            self.format_relationship_time(item.get("removed_at", "")),
                        ),
                        user_data={
                            0: {
                                "clickable": account_available,
                                "profile_url": profile_url,
                                "account_status": status,
                                "username": username,
                            }
                        },
                        foregrounds={
                            0: self.theme.accent if account_available else self.theme.text_primary,
                            1: status_color,
                        },
                        fonts={
                            0: {
                                "underline": account_available,
                                "bold": account_available,
                            }
                        },
                        alignments={
                            0: Qt.AlignLeft | Qt.AlignVCenter,
                            1: Qt.AlignLeft | Qt.AlignVCenter,
                            2: Qt.AlignRight | Qt.AlignVCenter,
                        },
                        localized_columns={1, 2},
                    )
                )
        elif category == "Subscribers":
            for item in self.sort_relationship_items(state.get("subscriptions_snapshot", []), category):
                detail = self.format_subscription_tier(item.get("tier"))
                if item.get("is_gift"):
                    detail += " • Gift"
                rows.append(
                    (
                        item.get("user_name") or item.get("user_login") or "Unknown",
                        detail,
                        "Active",
                    )
                )
        elif category == "Unsubscribers":
            for item in self.sort_relationship_items(state.get("unsubscribers", []), category):
                detail = self.format_subscription_tier(item.get("tier"))
                rows.append(
                    (
                        item.get("user_name") or item.get("user_login") or "Unknown",
                        detail,
                        self.format_relationship_time(item.get("removed_at", "")),
                    )
                )
        elif category == "Channels Followed":
            for item in self.sort_relationship_items(state.get("followed_channels_snapshot", []), category):
                rows.append(
                    (
                        item.get("broadcaster_name") or item.get("broadcaster_login") or "Unknown",
                        "Following",
                        self.format_relationship_time(item.get("followed_at", "")),
                    )
                )
        return rows
    def _legacy_make_incremental_table_row_translate_all_disabled(self, cells, *, user_data=None, alignments=None, foregrounds=None, fonts=None):
        normalized_cells = [
            self.localize(str(value).replace("â€¢", "-").replace("•", "-"))
            for value in list(cells or [])
        ]
        return {
            "cells": normalized_cells,
            "user_data": dict(user_data or {}),
            "alignments": dict(alignments or {}),
            "foregrounds": dict(foregrounds or {}),
            "fonts": dict(fonts or {}),
        }

    def make_incremental_table_row(self, cells, *, user_data=None, alignments=None, foregrounds=None, fonts=None, localized_columns=None):
        localized_columns = set(localized_columns or [])
        normalized_cells = []
        for index, value in enumerate(list(cells or [])):
            cell_text = str(value).replace("Ã¢â‚¬Â¢", "-").replace("â€¢", "-").replace("•", "-")
            if index in localized_columns:
                cell_text = self.localize(cell_text)
            normalized_cells.append(cell_text)
        return {
            "cells": normalized_cells,
            "user_data": dict(user_data or {}),
            "alignments": dict(alignments or {}),
            "foregrounds": dict(foregrounds or {}),
            "fonts": dict(fonts or {}),
        }

    def bind_incremental_table_loading(self, table, model, progress_callback=None):
        def maybe_load_more():
            scrollbar = table.verticalScrollBar()
            threshold = max(120, scrollbar.pageStep())
            if model.canFetchMore(QModelIndex()) and scrollbar.value() >= max(0, scrollbar.maximum() - threshold):
                model.fetchMore(QModelIndex())
                if progress_callback:
                    progress_callback()

        table.verticalScrollBar().valueChanged.connect(lambda _value: maybe_load_more())
        model.modelReset.connect(lambda: QTimer.singleShot(0, lambda: self.ensure_incremental_table_fill(table, model, progress_callback)))
        model.rowsInserted.connect(lambda *_args: progress_callback() if progress_callback else None)
    def ensure_incremental_table_fill(self, table, model, progress_callback=None):
        scrollbar = table.verticalScrollBar()
        threshold = max(120, scrollbar.pageStep())
        while model.canFetchMore(QModelIndex()) and scrollbar.maximum() <= threshold:
            model.fetchMore(QModelIndex())
        if progress_callback:
            progress_callback()
    def update_viewer_results_summary_label(self):
        if not hasattr(self, "viewer_results_summary_label") or not hasattr(self, "viewer_table_model"):
            return

        tracked_viewers = len(self.users_data)
        total_filtered = len(getattr(self, "viewer_filtered_records", []) or [])
        current_page = max(getattr(self, "viewer_current_page", 1), 1)
        total_pages = max(getattr(self, "viewer_total_pages", 1), 1)
        current_page_rows = self.viewer_table_model.rowCount()

        if not total_filtered:
            self.set_localized_text(
                self.viewer_results_summary_label,
                "viewers.showing_zero_tracked",
                tracked_viewers=f"{tracked_viewers:,}",
            )
            return

        self.set_localized_text(
            self.viewer_results_summary_label,
            "viewers.showing_page",
            rows=f"{current_page_rows:,}",
            page=current_page,
            total_pages=total_pages,
            matches=f"{total_filtered:,}",
            tracked_viewers=f"{tracked_viewers:,}",
        )
    def update_viewer_relationships_status_label(self):
        if not hasattr(self, "viewer_relationships_status_label") or not hasattr(self, "viewer_relationships_model"):
            return

        state = self.normalize_viewer_relationships_state(self.viewer_relationships_state)
        category_name = self.viewer_list_category.lower()
        total_rows = len(getattr(self, "viewer_relationship_current_rows", []) or [])
        current_page = max(getattr(self, "viewer_relationship_current_page", 1), 1)
        total_pages = max(getattr(self, "viewer_relationship_total_pages", 1), 1)

        if self.viewer_relationships_request_inflight:
            text = f"Loading {category_name} from Twitch..."
        elif total_rows:
            text = f"Showing page {current_page} of {total_pages} - {total_rows:,} total {category_name}"
        else:
            text = f"No {category_name} data yet"

        if state.get("last_error"):
            clean_error = str(state["last_error"]).replace("â€¢", "|").replace("•", "|")
            text = f"{text} - {clean_error}"
        elif state.get("last_synced_at"):
            text = f"{text} - Last synced {state['last_synced_at']}"

        self.set_localized_text(self.viewer_relationships_status_label, text)

    def update_viewer_relationships_status_label(self):
        if not hasattr(self, "viewer_relationships_status_label") or not hasattr(self, "viewer_relationships_model"):
            return

        state = self.normalize_viewer_relationships_state(self.viewer_relationships_state)
        category_name = self.viewer_list_category.lower()
        total_rows = len(getattr(self, "viewer_relationship_current_rows", []) or [])
        current_page = max(getattr(self, "viewer_relationship_current_page", 1), 1)
        total_pages = max(getattr(self, "viewer_relationship_total_pages", 1), 1)

        if self.viewer_relationships_request_inflight:
            key = "relationships.loading"
            params = {"category": self.localize(category_name)}
        elif total_rows:
            key = "relationships.showing_page"
            params = {
                "page": current_page,
                "total_pages": total_pages,
                "total": f"{total_rows:,}",
                "category": self.localize(category_name),
            }
        else:
            key = "relationships.no_data"
            params = {"category": self.localize(category_name)}

        if state.get("last_error"):
            clean_error = str(state["last_error"]).replace("Ã¢â‚¬Â¢", "|").replace("â€¢", "|")
            self.set_localized_text(self.viewer_relationships_status_label, f"{self.localize(key, **params)} - {clean_error}")
            return
        if state.get("last_synced_at") and key == "relationships.showing_page":
            self.set_localized_text(
                self.viewer_relationships_status_label,
                "relationships.showing_page_synced",
                time=state["last_synced_at"],
                **params,
            )
            return
        self.set_localized_text(self.viewer_relationships_status_label, key, **params)

    def make_pagination_button(self, text, callback, *, active=False, enabled=True, minimum_width=36):
        button = QPushButton(self.localize(text))
        self._set_i18n_source(button, text)
        button.setCursor(Qt.PointingHandCursor)
        button.setMinimumWidth(minimum_width)
        button.setMinimumHeight(30)
        button.clicked.connect(callback)
        button.setEnabled(enabled)

        background = self.theme.nav_active_bg if active else self.theme.subtle_bg
        border = self.theme.nav_active_border if active else self.theme.subtle_border
        color = self.theme.nav_active_text if active else self.theme.text_secondary
        hover_bg = self.theme.nav_hover_bg if not active else self.theme.nav_active_bg
        hover_border = self.theme.nav_hover_border if not active else self.theme.nav_active_border

        button.setStyleSheet(
            f"""
            QPushButton {{
                background: {background};
                color: {color};
                border: 1px solid {border};
                border-radius: 10px;
                padding: 6px 10px;
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton:hover:enabled {{
                background: {hover_bg};
                border-color: {hover_border};
                color: {self.theme.text_primary};
            }}
            QPushButton:disabled {{
                background: {self.theme.subtle_bg};
                color: {self.theme.text_muted};
                border-color: {self.theme.subtle_border};
            }}
            """
        )
        return button
    def paginate_rows(self, rows, current_page, page_size):
        items = list(rows or [])
        size = max(int(page_size or 1), 1)
        total_items = len(items)
        total_pages = max((total_items + size - 1) // size, 1)
        page = min(max(int(current_page or 1), 1), total_pages)
        start = (page - 1) * size
        end = start + size
        return items[start:end], page, total_pages, total_items
    def rebuild_viewer_pagination_controls(self):
        if not hasattr(self, "viewer_pagination_buttons_layout"):
            return
        while self.viewer_pagination_buttons_layout.count():
            item = self.viewer_pagination_buttons_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        total_pages = max(getattr(self, "viewer_total_pages", 1), 1)
        current_page = max(getattr(self, "viewer_current_page", 1), 1)

        self.viewer_pagination_buttons_layout.addWidget(
            self.make_pagination_button("Previous", lambda: self.set_viewer_page(current_page - 1), enabled=current_page > 1, minimum_width=74)
        )

        start_page = max(1, current_page - 2)
        end_page = min(total_pages, start_page + 4)
        start_page = max(1, end_page - 4)
        for page_number in range(start_page, end_page + 1):
            self.viewer_pagination_buttons_layout.addWidget(
                self.make_pagination_button(
                    str(page_number),
                    lambda checked=False, page=page_number: self.set_viewer_page(page),
                    active=page_number == current_page,
                )
            )

        self.viewer_pagination_buttons_layout.addWidget(
            self.make_pagination_button("Next", lambda: self.set_viewer_page(current_page + 1), enabled=current_page < total_pages, minimum_width=64)
        )
        self.viewer_pagination_buttons_layout.addStretch()
        if hasattr(self, "viewer_page_info_label"):
            total_items = len(getattr(self, "viewer_filtered_records", []) or [])
            self.set_localized_text(
                self.viewer_page_info_label,
                "pagination.page_results",
                page=current_page,
                total_pages=total_pages,
                results=f"{total_items:,}",
            )
    def rebuild_relationship_pagination_controls(self):
        if not hasattr(self, "viewer_relationship_pagination_buttons_layout"):
            return
        while self.viewer_relationship_pagination_buttons_layout.count():
            item = self.viewer_relationship_pagination_buttons_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        total_pages = max(getattr(self, "viewer_relationship_total_pages", 1), 1)
        current_page = max(getattr(self, "viewer_relationship_current_page", 1), 1)

        self.viewer_relationship_pagination_buttons_layout.addWidget(
            self.make_pagination_button(
                "Previous",
                lambda: self.set_relationship_page(current_page - 1),
                enabled=current_page > 1,
                minimum_width=74,
            )
        )

        start_page = max(1, current_page - 2)
        end_page = min(total_pages, start_page + 4)
        start_page = max(1, end_page - 4)
        for page_number in range(start_page, end_page + 1):
            self.viewer_relationship_pagination_buttons_layout.addWidget(
                self.make_pagination_button(
                    str(page_number),
                    lambda checked=False, page=page_number: self.set_relationship_page(page),
                    active=page_number == current_page,
                )
            )

        self.viewer_relationship_pagination_buttons_layout.addWidget(
            self.make_pagination_button(
                "Next",
                lambda: self.set_relationship_page(current_page + 1),
                enabled=current_page < total_pages,
                minimum_width=64,
            )
        )
        self.viewer_relationship_pagination_buttons_layout.addStretch()
        if hasattr(self, "viewer_relationship_page_info_label"):
            total_items = len(getattr(self, "viewer_relationship_current_rows", []) or [])
            self.set_localized_text(
                self.viewer_relationship_page_info_label,
                "pagination.page_results",
                page=current_page,
                total_pages=total_pages,
                results=f"{total_items:,}",
            )
    def set_viewer_page(self, page_number):
        target_page = min(max(int(page_number or 1), 1), max(getattr(self, "viewer_total_pages", 1), 1))
        if target_page == getattr(self, "viewer_current_page", 1) and self.viewer_table_model.rowCount() > 0:
            return
        self.viewer_current_page = target_page
        self.populate_viewer_table(getattr(self, "viewer_filtered_records", []))
        if hasattr(self, "viewer_table"):
            self.viewer_table.scrollToTop()
    def set_relationship_page(self, page_number):
        target_page = min(max(int(page_number or 1), 1), max(getattr(self, "viewer_relationship_total_pages", 1), 1))
        if target_page == getattr(self, "viewer_relationship_current_page", 1) and self.viewer_relationship_model.rowCount() > 0:
            return
        self.viewer_relationship_current_page = target_page
        self.refresh_viewer_relationships_panel()
        if hasattr(self, "viewer_relationships_table"):
            self.viewer_relationships_table.scrollToTop()
    def populate_relationship_table(self, rows):
        page_rows, current_page, total_pages, _total_items = self.paginate_rows(
            rows,
            getattr(self, "viewer_relationship_current_page", 1),
            getattr(self, "viewer_relationship_page_size", 50),
        )
        self.viewer_relationship_current_page = current_page
        self.viewer_relationship_total_pages = total_pages
        model_rows = [
            values
            if isinstance(values, dict) and "cells" in values
            else self.make_incremental_table_row(
                values,
                alignments={
                    0: Qt.AlignLeft | Qt.AlignVCenter,
                    1: Qt.AlignLeft | Qt.AlignVCenter,
                    2: Qt.AlignRight | Qt.AlignVCenter,
                },
                localized_columns={1, 2},
            )
            for values in list(page_rows or [])
        ]
        self.viewer_relationships_model.set_rows(
            model_rows,
            empty_row=self.make_incremental_table_row(
                ("No data yet", "Reconnect/sync if needed", "--"),
                alignments={
                    0: Qt.AlignLeft | Qt.AlignVCenter,
                    1: Qt.AlignLeft | Qt.AlignVCenter,
                    2: Qt.AlignRight | Qt.AlignVCenter,
                },
                localized_columns={0, 1},
            ),
        )
        self.viewer_relationships_table.scrollToTop()
        self.rebuild_relationship_pagination_controls()
    def set_relationship_panel_expanded(self, expanded, animate=True):
        self.viewer_relationships_panel_expanded = bool(expanded)
        if hasattr(self, "viewer_relationships_toggle_button"):
            self.set_localized_text(self.viewer_relationships_toggle_button, "Hide Lists" if expanded else "Show Lists")
        if not hasattr(self, "viewer_relationships_content"):
            return

        content = self.viewer_relationships_content
        target_height = max(content.sizeHint().height(), 320) if expanded else 0
        if self.viewer_relationships_animation is None:
            self.viewer_relationships_animation = QPropertyAnimation(content, b"maximumHeight", self)
            self.viewer_relationships_animation.setDuration(220)
            self.viewer_relationships_animation.setEasingCurve(QEasingCurve.OutCubic)

        self.viewer_relationships_animation.stop()
        if animate:
            self.viewer_relationships_animation.setStartValue(content.maximumHeight())
            self.viewer_relationships_animation.setEndValue(target_height)
            self.viewer_relationships_animation.start()
        else:
            content.setMaximumHeight(target_height)
    def toggle_viewer_relationships_panel(self):
        self.set_relationship_panel_expanded(not self.viewer_relationships_panel_expanded, animate=True)
    def refresh_viewer_relationships_panel(self):
        if not hasattr(self, "viewer_relationships_model"):
            return

        self.sync_viewer_list_category_buttons()
        rows = self.viewer_relationship_rows_cache.get(self.viewer_list_category)
        if rows is None:
            rows = self.build_relationship_rows(self.viewer_list_category)
            self.viewer_relationship_rows_cache[self.viewer_list_category] = rows
        self.viewer_relationship_current_rows = rows
        self.populate_relationship_table(rows)
        self.update_viewer_relationships_status_label()
    def merge_snapshot_and_removed(self, previous_items, current_items, removed_at):
        previous_map = {
            str(item.get("user_id") or item.get("broadcaster_id") or item.get("user_login") or item.get("broadcaster_login")): item
            for item in previous_items
        }
        current_map = {
            str(item.get("user_id") or item.get("broadcaster_id") or item.get("user_login") or item.get("broadcaster_login")): item
            for item in current_items
        }
        removed_items = []
        for item_id, item in previous_map.items():
            if item_id and item_id not in current_map:
                removed_item = dict(item)
                removed_item["removed_at"] = removed_at
                removed_items.append(removed_item)
        return removed_items
    def classify_removed_followers(self, removed_items, access_token):
        removed_followers = [dict(item) for item in list(removed_items or [])]
        removed_ids = [str(item.get("user_id", "")).strip() for item in removed_followers if str(item.get("user_id", "")).strip()]
        removed_logins = [
            str(item.get("user_login", "")).strip().lower()
            for item in removed_followers
            if str(item.get("user_login", "")).strip()
        ]
        existing_users = {}
        existing_users_by_login = {}
        availability_error = None

        if removed_ids:
            try:
                existing_users = get_users_by_ids(CLIENT_ID, access_token, removed_ids)
            except Exception as exc:
                availability_error = str(exc)
        if removed_logins and not availability_error:
            try:
                existing_users_by_login = get_users_by_logins(CLIENT_ID, access_token, removed_logins)
            except Exception as exc:
                availability_error = str(exc)

        for item in removed_followers:
            user_id = str(item.get("user_id", "")).strip()
            fallback_login = str(item.get("user_login", "")).strip().lower()
            known_user = existing_users.get(user_id) or existing_users_by_login.get(fallback_login)
            if known_user:
                login_name = (known_user.get("login") or item.get("user_login") or "").strip()
                item["user_login"] = login_name
                item["user_name"] = (known_user.get("display_name") or item.get("user_name") or login_name or "Unknown").strip()
                item["status"] = "Unfollowed"
                item["account_available"] = True
                item["profile_url"] = f"https://www.twitch.tv/{login_name}" if login_name else ""
            elif availability_error:
                item["status"] = "Account Unavailable"
                item["account_available"] = False
                item["profile_url"] = ""
            else:
                item["status"] = "Account Closed"
                item["account_available"] = False
                item["profile_url"] = ""

        return removed_followers, availability_error
    def refresh_existing_unfollowers(self, state, access_token):
        refreshed_unfollowers, availability_error = self.classify_removed_followers(state.get("unfollowers", []), access_token)
        state["unfollowers"] = list(refreshed_unfollowers)[-200:]
        return availability_error
    def sync_viewer_relationships_from_api(self, details):
        state = self.normalize_viewer_relationships_state(load_json(VIEWER_RELATIONSHIPS_FILE, default_viewer_relationships_state()))
        token = details.get("access_token")
        channel_user_id = details.get("user_id", "")
        scopes = set(details.get("scopes", []))
        sync_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        errors = []
        new_alerts = []

        followers = list(state.get("followers_snapshot", []))
        subscriptions = list(state.get("subscriptions_snapshot", []))
        followed_channels = list(state.get("followed_channels_snapshot", []))

        if token:
            availability_error = self.refresh_existing_unfollowers(state, token)
            if availability_error:
                errors.append(f"Stored unfollower verification failed: {availability_error}")

        if "moderator:read:followers" in scopes:
            try:
                previous_followers = list(state.get("followers_snapshot", []))
                followers = get_all_channel_followers(CLIENT_ID, token, channel_user_id)
                new_alerts.extend(build_new_follower_alerts(previous_followers, followers))
                removed_followers = self.merge_snapshot_and_removed(state.get("followers_snapshot", []), followers, sync_timestamp)
                removed_followers, availability_error = self.classify_removed_followers(removed_followers, token)
                existing = {
                    str(item.get("user_id") or item.get("user_login")): item
                    for item in state.get("unfollowers", [])
                }
                for item in removed_followers:
                    key = str(item.get("user_id") or item.get("user_login"))
                    existing[key] = item
                state["unfollowers"] = list(existing.values())[-200:]
                state["followers_snapshot"] = followers
                if availability_error:
                    errors.append(f"Unfollower account verification failed: {availability_error}")
            except Exception as exc:
                errors.append(f"Followers sync failed: {exc}")
        else:
            errors.append("Reconnect Channel Account to grant moderator:read:followers")

        if "channel:read:subscriptions" in scopes:
            try:
                previous_subscriptions = list(state.get("subscriptions_snapshot", []))
                subscriptions = get_all_broadcaster_subscriptions(CLIENT_ID, token, channel_user_id)
                new_alerts.extend(build_new_subscription_alerts(previous_subscriptions, subscriptions, sync_timestamp))
                removed_subscribers = self.merge_snapshot_and_removed(
                    state.get("subscriptions_snapshot", []),
                    subscriptions,
                    sync_timestamp,
                )
                existing = {
                    str(item.get("user_id") or item.get("user_login")): item
                    for item in state.get("unsubscribers", [])
                }
                for item in removed_subscribers:
                    key = str(item.get("user_id") or item.get("user_login"))
                    existing[key] = item
                state["unsubscribers"] = list(existing.values())[-200:]
                state["subscriptions_snapshot"] = subscriptions
            except Exception as exc:
                errors.append(f"Subscribers sync failed: {exc}")
        else:
            errors.append("Reconnect Channel Account to grant channel:read:subscriptions")

        if "user:read:follows" in scopes:
            try:
                followed_channels = get_all_followed_channels(CLIENT_ID, token, channel_user_id)
                state["followed_channels_snapshot"] = followed_channels
            except Exception as exc:
                errors.append(f"Followed channels sync failed: {exc}")
        else:
            errors.append("Reconnect Channel Account to grant user:read:follows")

        state["last_synced_at"] = sync_timestamp
        state["last_error"] = " • ".join(errors[:3]) if errors else ""
        save_json(VIEWER_RELATIONSHIPS_FILE, state)
        if new_alerts:
            add_alert_items(ALERTS_FILE, new_alerts)
        return state
    def request_viewer_relationships_sync(self, force=False):
        if not hasattr(self, "viewer_relationships_model"):
            return
        if not self.is_bot_process_running():
            state = self.normalize_viewer_relationships_state(self.viewer_relationships_state)
            state["last_error"] = "Start the bot to sync followers, subscribers, and followed channels."
            self.viewer_relationships_state = state
            self.refresh_viewer_relationships_panel()
            return
        if self.viewer_relationships_request_inflight:
            return

        details = load_token_details(CHANNEL_AUTH_ROLE)
        if not details.get("access_token"):
            state = self.normalize_viewer_relationships_state(self.viewer_relationships_state)
            state["last_error"] = "Connect the Channel Account to load followers, subscribers, and followed channels."
            self.viewer_relationships_state = state
            self.refresh_viewer_relationships_panel()
            return

        now = time.time()
        if not force and (now - self.viewer_relationships_last_fetch_at) < 180:
            self.refresh_viewer_relationships_panel()
            return

        self.viewer_relationships_request_inflight = True
        if hasattr(self, "viewer_relationships_status_label"):
            self.set_localized_text(self.viewer_relationships_status_label, "Syncing Twitch relationship lists...")

        def worker():
            payload = {
                "state": self.sync_viewer_relationships_from_api(details),
            }
            self.bridge.viewer_relationships_signal.emit(payload)

        threading.Thread(target=worker, daemon=True).start()
    def _apply_viewer_relationships_payload(self, payload):
        self.viewer_relationships_request_inflight = False
        self.viewer_relationships_last_fetch_at = time.time()
        self.viewer_relationships_state = self.normalize_viewer_relationships_state(payload.get("state", {}))
        self.viewer_relationship_rows_cache = {}
        self.refresh_viewer_relationships_panel()
        if hasattr(self, "load_alert_feed_items"):
            self.load_alert_feed_items(force=True)
            self.refresh_alert_feed()
    def open_relationship_profile(self, index):
        if not index.isValid() or index.column() != 0:
            return

        payload = self.viewer_relationships_model.data(index, Qt.UserRole)
        if not isinstance(payload, dict):
            return

        profile_url = str(payload.get("profile_url", "")).strip()
        if payload.get("clickable") and profile_url:
            opened = QDesktopServices.openUrl(QUrl(profile_url))
            if not opened:
                webbrowser.open(profile_url)
            return

        if hasattr(self, "viewer_relationships_status_label"):
            username = payload.get("username") or "This account"
            status = payload.get("account_status") or "Account Unavailable"
            self.set_dynamic_text(self.viewer_relationships_status_label, f"{username}: {status} - Twitch profile is no longer available.")
    def apply_viewer_table_style(self, table):
        table.horizontalHeader().setStyleSheet(
            f"""
            QHeaderView::section {{
                background: transparent;
                color: {self.theme.text_secondary};
                border: none;
                padding: 0 0 10px 0;
                font-size: 12px;
                font-weight: 700;
            }}
            """
        )
        table.setStyleSheet(
            f"""
            QTableView, QTableWidget {{
                background: transparent;
                border: none;
                gridline-color: {self.theme.card_border};
                color: {self.theme.text_primary};
                font-size: 13px;
                selection-background-color: {self.theme.nav_active_bg};
                selection-color: {self.theme.text_primary};
            }}
            QTableView::item, QTableWidget::item {{
                border-bottom: 1px solid {self.theme.card_border};
                padding: 12px 8px;
            }}
            QTableView::item:selected, QTableWidget::item:selected {{
                background: {self.theme.nav_active_bg};
                color: {self.theme.text_primary};
            }}
            """
        )
    def sync_viewer_filter_buttons(self):
        for filter_name, button in self.viewer_filter_buttons.items():
            active = filter_name == self.viewer_filter_name
            if active:
                background = self.theme.nav_active_bg
                border = self.theme.nav_active_border
                color = self.theme.nav_active_text
            else:
                background = self.theme.subtle_bg
                border = self.theme.subtle_border
                color = self.theme.text_secondary

            button.setStyleSheet(
                f"""
                QPushButton {{
                    background: {background};
                    color: {color};
                    border: 1px solid {border};
                    border-radius: 10px;
                    padding: 6px 12px;
                    font-size: 12px;
                    font-weight: 700;
                }}
                QPushButton:hover {{
                    background: {self.theme.nav_hover_bg};
                    border-color: {self.theme.nav_hover_border};
                    color: {self.theme.text_primary};
                }}
                """
            )
            button.blockSignals(True)
            button.setChecked(active)
            button.blockSignals(False)
    def set_viewer_filter(self, filter_name):
        if filter_name == self.viewer_filter_name:
            return
        self.viewer_filter_name = filter_name
        self.viewer_current_page = 1
        self.sync_viewer_filter_buttons()
        self.refresh_viewers_dashboard()
    def set_sort_selector_value(self, selector, sort_key):
        if selector is None:
            return
        index = selector.findData(sort_key)
        if index >= 0 and selector.currentIndex() != index:
            selector.blockSignals(True)
            selector.setCurrentIndex(index)
            selector.blockSignals(False)
    def on_viewer_search_changed(self):
        self.viewer_current_page = 1
        self.refresh_viewers_dashboard()
    def populate_viewer_table(self, records):
        page_records, current_page, total_pages, _total_items = self.paginate_rows(
            records,
            getattr(self, "viewer_current_page", 1),
            getattr(self, "viewer_page_size", 50),
        )
        self.viewer_current_page = current_page
        self.viewer_total_pages = total_pages

        if not records:
            self.viewer_table_model.set_rows(
                [],
                empty_row=self.make_incremental_table_row(
                    ("No viewers matched your search", "", "", ""),
                    alignments={0: Qt.AlignLeft | Qt.AlignVCenter},
                    localized_columns={0},
                ),
            )
            self.viewer_table.clearSelection()
            self.selected_viewer_username = ""
            self.clear_viewer_details_panel()
            self.update_viewer_results_summary_label()
            self.rebuild_viewer_pagination_controls()
            return

        selected_row = 0
        selected_username = self.selected_viewer_username
        available_usernames = [record["username"] for record in page_records]
        if selected_username not in available_usernames:
            selected_username = available_usernames[0]

        role_colors = {
            "Broadcaster": self.theme.warning,
            "Mod": self.theme.success,
            "VIP": self.theme.accent_secondary,
            "Subscriber": self.theme.accent,
            "Viewer": self.theme.text_secondary,
        }
        activity_colors = {
            "Active now": self.theme.success,
            "Active": self.theme.accent,
            "Lurking": self.theme.text_secondary,
            "Muted": self.theme.danger,
        }
        model_rows = []
        for row_index, record in enumerate(page_records):
            model_rows.append(
                self.make_incremental_table_row(
                    (record["username"], f"{record['messages']}", record["role"], record["activity"]),
                    user_data={0: record["username"]},
                    alignments={
                        0: Qt.AlignLeft | Qt.AlignVCenter,
                        1: Qt.AlignRight | Qt.AlignVCenter,
                        2: Qt.AlignCenter,
                        3: Qt.AlignCenter,
                    },
                    foregrounds={
                        2: role_colors.get(record["role"], self.theme.text_primary),
                        3: activity_colors.get(record["activity"], self.theme.text_primary),
                    },
                    localized_columns={2, 3},
                )
            )

            if record["username"] == selected_username:
                selected_row = row_index

        self.viewer_table_model.set_rows(model_rows)
        self.viewer_table.selectRow(selected_row)
        self.viewer_table.scrollToTop()
        self.selected_viewer_username = selected_username
        self.update_viewer_details_panel(selected_username)
        self.update_viewer_results_summary_label()
        self.rebuild_viewer_pagination_controls()
    def refresh_viewers_dashboard(self):
        if not hasattr(self, "viewer_table_model"):
            return

        records = self.build_viewer_records()
        search_query = self.viewer_search_input.text().strip().lower() if hasattr(self, "viewer_search_input") else ""
        if search_query:
            records = [record for record in records if search_query in record["username"].lower()]
        records = [record for record in records if self.viewer_matches_filter(record)]
        records = self.sort_viewer_records(records)
        self.viewer_filtered_records = records

        self.populate_viewer_table(records)

        top_chatters = sorted(
            self.dashboard_state.get("top_chatters", {}).items(),
            key=lambda item: item[1],
            reverse=True,
        )[:6]
        self.populate_dashboard_table(
            self.viewer_top_chatters_table,
            top_chatters,
            empty_left="No chatter data yet",
            empty_right="0",
        )

        history = self.dashboard_state.get("analytics_history", [])[-7:]
        labels = []
        tooltip_labels = []
        messages_series = []
        commands_series = []
        timeouts_series = []
        for bucket in history:
            bucket_date = bucket.get("date", "")
            try:
                parsed_date = datetime.fromisoformat(bucket_date)
                labels.append(parsed_date.strftime("%a"))
                tooltip_labels.append(parsed_date.strftime("%A, %d %b"))
            except Exception:
                labels.append(bucket_date[-5:] if bucket_date else "")
                tooltip_labels.append(bucket_date or "")
            messages_series.append(int(bucket.get("messages", 0) or 0))
            commands_series.append(int(bucket.get("commands", 0) or 0))
            timeouts_series.append(int(bucket.get("timeouts", 0) or 0))

        self.viewer_activity_chart.set_series_data(
            labels,
            {
                "Messages": messages_series,
                "Commands": commands_series,
                "Timeouts": timeouts_series,
            },
            tooltip_labels=tooltip_labels,
        )

        self.request_stream_summary_refresh(force=False)
        self.request_viewer_relationships_sync(force=False)
    def clear_viewer_details_panel(self):
        self.set_localized_text(self.viewer_selected_name_label, "Select a viewer")
        self.set_localized_text(self.viewer_selected_role_badge, "Viewer")
        self.apply_badge_style(self.viewer_selected_role_badge, "neutral")
        self.set_localized_text(self.viewer_selected_activity_badge, "Waiting")
        self.apply_badge_style(self.viewer_selected_activity_badge, "neutral")
        self.viewer_detail_messages_value.setText("--")
        self.set_localized_text(self.viewer_detail_last_active_value, "No activity yet")
        self.set_localized_text(self.viewer_detail_relative_value, "No recent activity")
        self.set_localized_text(self.viewer_detail_behavior_value, "Neutral")
        self.set_localized_text(self.viewer_detail_last_message_value, "No messages yet")
        self.set_localized_text(self.viewer_detail_notes_value, "Select a viewer from the left to inspect their recent activity.")
        self.set_localized_text(self.viewer_mute_button, "Mute")
        self.viewer_mute_button.setEnabled(False)
        self.viewer_timeout_button.setEnabled(False)
        self.viewer_vip_button.setEnabled(False)
    def update_viewer_details_panel(self, username):
        if not username:
            self.clear_viewer_details_panel()
            return

        profile = self.users_data.get(username, {})
        role_lookup = self.build_viewer_role_lookup()
        role = role_lookup.get(username, "Viewer")
        activity = self.derive_viewer_activity_state(profile)
        last_messages = get_recent_user_only_messages(username, limit=4)
        last_message = last_messages[-1] if last_messages else "No messages yet"
        notes = profile.get("notes", "not enough information yet")
        behavior = profile.get("behavior", "neutral").replace("_", " ").title()

        self.set_dynamic_text(self.viewer_selected_name_label, username)
        self.set_localized_text(self.viewer_selected_role_badge, role)
        self.apply_badge_style(
            self.viewer_selected_role_badge,
            "success" if role in {"Mod", "Broadcaster"} else ("info" if role == "VIP" else "neutral"),
        )
        self.set_localized_text(self.viewer_selected_activity_badge, activity)
        activity_tone = "danger" if activity == "Muted" else ("success" if activity == "Active now" else "neutral")
        self.apply_badge_style(self.viewer_selected_activity_badge, activity_tone)

        self.viewer_detail_messages_value.setText(str(int(profile.get("messages", 0) or 0)))
        self.set_dynamic_text(self.viewer_detail_last_active_value, self.format_last_active_display(profile.get("last_seen", "")))
        self.set_localized_text(self.viewer_detail_relative_value, self.format_relative_activity(profile.get("last_seen", "")))
        self.set_localized_text(self.viewer_detail_behavior_value, behavior)
        self.set_dynamic_text(self.viewer_detail_last_message_value, last_message)
        self.set_dynamic_text(self.viewer_detail_notes_value, notes)

        self.set_localized_text(self.viewer_mute_button, "Unmute" if profile.get("muted") else "Mute")
        self.set_localized_text(self.viewer_vip_button, "Remove VIP" if (profile.get("manual_role") or "").strip() == "VIP" else "Add VIP")
        self.viewer_mute_button.setEnabled(True)
        self.viewer_timeout_button.setEnabled(True)
        self.viewer_vip_button.setEnabled(True)
    def on_viewer_table_selection_changed(self):
        if not hasattr(self, "viewer_table_model"):
            return

        index = self.viewer_table.currentIndex()
        if not index.isValid():
            self.selected_viewer_username = ""
            self.clear_viewer_details_panel()
            return

        username = self.viewer_table_model.data(self.viewer_table_model.index(index.row(), 0), Qt.UserRole)
        if not username:
            self.selected_viewer_username = ""
            self.clear_viewer_details_panel()
            return
        self.selected_viewer_username = username
        self.update_viewer_details_panel(username)
    def update_selected_viewer_profile(self, **changes):
        username = self.selected_viewer_username
        if not username:
            return
        profile = dict(self.users_data.get(username, {}))
        profile.update(changes)
        self.users_data[username] = profile
        save_user_profiles(self.users_data)
        self.refresh_viewers_dashboard()
    def toggle_selected_viewer_mute(self):
        if not self.selected_viewer_username:
            return
        profile = self.users_data.get(self.selected_viewer_username, {})
        next_value = not bool(profile.get("muted", False))
        self.update_selected_viewer_profile(muted=next_value)
        action = "Muted" if next_value else "Unmuted"
        self.append_log(f"[Viewers] {action} {self.selected_viewer_username} in the local moderation dashboard")
    def timeout_selected_viewer(self):
        if not self.selected_viewer_username:
            return
        self.update_selected_viewer_profile(muted=True)
        self.append_log(
            f"[Viewers] Timeout shortcut flagged {self.selected_viewer_username}. "
            "This dashboard action currently applies a local mute marker for moderation follow-up."
        )
    def toggle_selected_viewer_vip(self):
        if not self.selected_viewer_username:
            return
        profile = self.users_data.get(self.selected_viewer_username, {})
        current_manual_role = (profile.get("manual_role") or "").strip()
        next_role = "" if current_manual_role == "VIP" else "VIP"
        self.update_selected_viewer_profile(manual_role=next_role)
        if next_role:
            self.append_log(f"[Viewers] Added VIP tag for {self.selected_viewer_username}")
        else:
            self.append_log(f"[Viewers] Removed VIP tag for {self.selected_viewer_username}")
    def build_viewers_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        body = QWidget()
        outer = QVBoxLayout(body)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(18)

        header_row = QHBoxLayout()
        header_row.setSpacing(16)

        header_text = QVBoxLayout()
        header_text.setSpacing(4)
        header_text.addWidget(self.make_title("Viewers Dashboard"))
        subtitle = QLabel(
            "Track your live audience with searchable viewer profiles, moderation shortcuts, and chatter analytics."
        )
        subtitle.setWordWrap(True)
        self.set_label_role(subtitle, "heroSubtitle")
        header_text.addWidget(subtitle)
        header_row.addLayout(header_text, 1)

        helper_badge = self.make_badge_label("Live moderation view", "info")
        header_row.addWidget(helper_badge, 0, Qt.AlignTop)
        outer.addLayout(header_row)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(14)
        summary_row.addWidget(
            self.build_viewer_summary_card("Current Viewers", "viewer_summary_count_value", "viewer_summary_count_detail")
        )
        summary_row.addWidget(
            self.build_viewer_summary_card("Stream Status", "viewer_summary_status_value", "viewer_summary_status_detail")
        )
        summary_row.addWidget(
            self.build_viewer_summary_card("Stream Uptime", "viewer_summary_uptime_value", "viewer_summary_uptime_detail")
        )
        outer.addLayout(summary_row)

        content_row = QHBoxLayout()
        content_row.setSpacing(16)

        directory_card = Card()
        directory_layout = QVBoxLayout(directory_card)
        directory_layout.setContentsMargins(18, 18, 18, 18)
        directory_layout.setSpacing(12)
        directory_layout.addWidget(self.make_title("Viewer Directory"))

        directory_subtitle = QLabel(
            "Search viewers, filter by role or activity, and click a row to inspect the profile panel."
        )
        directory_subtitle.setWordWrap(True)
        self.set_label_role(directory_subtitle, "cardSubtitle")
        directory_layout.addWidget(directory_subtitle)

        self.viewer_search_input = QLineEdit()
        self.viewer_search_input.setPlaceholderText("Search by username")
        self.viewer_search_input.textChanged.connect(self.on_viewer_search_changed)
        directory_layout.addWidget(self.viewer_search_input)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        for filter_name in ("All", "Active", "Mods", "VIP", "Lurkers"):
            filter_row.addWidget(self.make_viewer_filter_button(filter_name))
        filter_row.addStretch()
        filter_row.addWidget(self.make_small_title("Sort by"))
        self.viewer_sort_selector = QComboBox()
        self.viewer_sort_selector.addItem("Newest", "newest")
        self.viewer_sort_selector.addItem("Oldest", "oldest")
        self.viewer_sort_selector.addItem("Messages", "messages")
        self.viewer_sort_selector.addItem("Role", "role")
        self.viewer_sort_selector.currentIndexChanged.connect(self.on_viewer_sort_changed)
        filter_row.addWidget(self.viewer_sort_selector)
        directory_layout.addLayout(filter_row)

        self.viewer_results_summary_label = QLabel("Showing 0 viewers")
        self.set_label_role(self.viewer_results_summary_label, "mutedBody")
        directory_layout.addWidget(self.viewer_results_summary_label)

        self.viewer_table = QTableView()
        self.viewer_table_model = IncrementalTableModel(("Username", "Messages", "Role", "Status"), batch_size=180, parent=self)
        self.viewer_table.setModel(self.viewer_table_model)
        self.viewer_table.verticalHeader().setVisible(False)
        self.viewer_table.setAlternatingRowColors(False)
        self.viewer_table.setShowGrid(False)
        self.viewer_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.viewer_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.viewer_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.viewer_table.setFocusPolicy(Qt.NoFocus)
        self.viewer_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.viewer_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.viewer_table.horizontalHeader().setStretchLastSection(False)
        self.viewer_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.viewer_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.viewer_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.viewer_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.viewer_table.verticalHeader().setDefaultSectionSize(44)
        self.viewer_table.selectionModel().selectionChanged.connect(lambda *_args: self.on_viewer_table_selection_changed())
        self.viewer_table.setMinimumHeight(500)
        self.apply_viewer_table_style(self.viewer_table)
        directory_layout.addWidget(self.viewer_table)

        directory_layout.addSpacing(6)
        viewer_pagination_row = QHBoxLayout()
        viewer_pagination_row.setSpacing(8)
        viewer_pagination_row.setContentsMargins(0, 6, 0, 0)
        self.viewer_page_info_label = QLabel("Page 1 / 1")
        self.set_label_role(self.viewer_page_info_label, "mutedBody")
        viewer_pagination_row.addWidget(self.viewer_page_info_label)
        viewer_pagination_row.addStretch()
        self.viewer_pagination_buttons_layout = QHBoxLayout()
        self.viewer_pagination_buttons_layout.setSpacing(6)
        viewer_pagination_row.addLayout(self.viewer_pagination_buttons_layout)
        directory_layout.addLayout(viewer_pagination_row)
        content_row.addWidget(directory_card, 3)

        right_column = QWidget()
        right_layout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(16)

        details_card = Card()
        details_layout = QVBoxLayout(details_card)
        details_layout.setContentsMargins(18, 18, 18, 18)
        details_layout.setSpacing(12)
        details_layout.addWidget(self.make_title("Selected Viewer"))

        detail_intro = QLabel("Inspect message volume, recent activity, and moderation tags for the currently selected chatter.")
        detail_intro.setWordWrap(True)
        self.set_label_role(detail_intro, "cardSubtitle")
        details_layout.addWidget(detail_intro)

        detail_header_row = QHBoxLayout()
        detail_header_row.setSpacing(8)
        self.viewer_selected_name_label = self.set_label_role(QLabel("Select a viewer"), "cardTitle")
        detail_header_row.addWidget(self.viewer_selected_name_label, 1)
        self.viewer_selected_role_badge = self.make_badge_label("Viewer", "neutral")
        detail_header_row.addWidget(self.viewer_selected_role_badge, 0, Qt.AlignRight)
        self.viewer_selected_activity_badge = self.make_badge_label("Waiting", "neutral")
        detail_header_row.addWidget(self.viewer_selected_activity_badge, 0, Qt.AlignRight)
        details_layout.addLayout(detail_header_row)

        detail_stats_grid = QGridLayout()
        detail_stats_grid.setHorizontalSpacing(16)
        detail_stats_grid.setVerticalSpacing(10)

        detail_stats_grid.addWidget(self.make_small_title("Total Messages"), 0, 0)
        self.viewer_detail_messages_value = self.make_info_value_label("--")
        detail_stats_grid.addWidget(self.viewer_detail_messages_value, 0, 1)

        detail_stats_grid.addWidget(self.make_small_title("Last Active"), 1, 0)
        self.viewer_detail_last_active_value = self.make_info_value_label("No activity yet")
        detail_stats_grid.addWidget(self.viewer_detail_last_active_value, 1, 1)

        detail_stats_grid.addWidget(self.make_small_title("Relative Activity"), 2, 0)
        self.viewer_detail_relative_value = self.make_info_value_label("No recent activity")
        detail_stats_grid.addWidget(self.viewer_detail_relative_value, 2, 1)

        detail_stats_grid.addWidget(self.make_small_title("Behavior"), 3, 0)
        self.viewer_detail_behavior_value = self.make_info_value_label("Neutral")
        detail_stats_grid.addWidget(self.viewer_detail_behavior_value, 3, 1)
        details_layout.addLayout(detail_stats_grid)

        details_layout.addWidget(self.make_small_title("Last Message"))
        self.viewer_detail_last_message_value = QLabel("No messages yet")
        self.viewer_detail_last_message_value.setWordWrap(True)
        self.set_label_role(self.viewer_detail_last_message_value, "mutedBody")
        details_layout.addWidget(self.viewer_detail_last_message_value)

        details_layout.addWidget(self.make_small_title("Profile Notes"))
        self.viewer_detail_notes_value = QLabel("Select a viewer from the left to inspect their recent activity.")
        self.viewer_detail_notes_value.setWordWrap(True)
        self.set_label_role(self.viewer_detail_notes_value, "mutedBody")
        details_layout.addWidget(self.viewer_detail_notes_value)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.viewer_mute_button = self.make_button("Mute", "muted", self.toggle_selected_viewer_mute)
        self.viewer_timeout_button = self.make_button("Timeout", "warning", self.timeout_selected_viewer)
        self.viewer_vip_button = self.make_button("Add VIP", "primary", self.toggle_selected_viewer_vip)
        action_row.addWidget(self.viewer_mute_button)
        action_row.addWidget(self.viewer_timeout_button)
        action_row.addWidget(self.viewer_vip_button)
        action_row.addStretch()
        details_layout.addLayout(action_row)
        right_layout.addWidget(details_card)

        graph_card = Card()
        graph_layout = QVBoxLayout(graph_card)
        graph_layout.setContentsMargins(18, 18, 18, 18)
        graph_layout.setSpacing(12)
        graph_layout.addWidget(self.make_title("Viewer Activity"))

        graph_subtitle = QLabel("A quick view of recent message, command, and timeout volume over the last 7 days.")
        graph_subtitle.setWordWrap(True)
        self.set_label_role(graph_subtitle, "cardSubtitle")
        graph_layout.addWidget(graph_subtitle)

        self.viewer_activity_chart = AnalyticsChartWidget()
        self.viewer_activity_chart.setMinimumHeight(250)
        graph_layout.addWidget(self.viewer_activity_chart)
        right_layout.addWidget(graph_card)

        relationship_card = Card()
        relationship_layout = QVBoxLayout(relationship_card)
        relationship_layout.setContentsMargins(18, 18, 18, 18)
        relationship_layout.setSpacing(12)

        relationship_header_row = QHBoxLayout()
        relationship_header_row.setSpacing(8)
        relationship_header_row.addWidget(self.make_title("Channel Lists"), 1)
        self.viewer_relationships_toggle_button = self.make_button("Hide Lists", "muted", self.toggle_viewer_relationships_panel)
        relationship_header_row.addWidget(self.viewer_relationships_toggle_button, 0, Qt.AlignRight)
        relationship_layout.addLayout(relationship_header_row)

        relationship_subtitle = QLabel(
            "Switch between followers, unfollowers, subscribers, unsubscribers, and channels followed. "
            "These lists sync from Twitch and track removals locally over time."
        )
        relationship_subtitle.setWordWrap(True)
        self.set_label_role(relationship_subtitle, "cardSubtitle")
        relationship_layout.addWidget(relationship_subtitle)

        self.viewer_relationships_content = QWidget()
        relationship_content_layout = QVBoxLayout(self.viewer_relationships_content)
        relationship_content_layout.setContentsMargins(0, 0, 0, 0)
        relationship_content_layout.setSpacing(12)

        category_row = QHBoxLayout()
        category_row.setSpacing(8)
        for category_name in ("Followers", "Unfollowers", "Subscribers", "Unsubscribers", "Channels Followed"):
            category_row.addWidget(self.make_viewer_list_category_button(category_name))
        category_row.addStretch()
        category_row.addWidget(self.make_small_title("Sort by"))
        self.relationship_sort_selector = QComboBox()
        self.relationship_sort_selector.addItem("Newest", "newest")
        self.relationship_sort_selector.addItem("Oldest", "oldest")
        self.relationship_sort_selector.addItem("Role", "role")
        self.relationship_sort_selector.currentIndexChanged.connect(self.on_relationship_sort_changed)
        category_row.addWidget(self.relationship_sort_selector)
        relationship_content_layout.addLayout(category_row)

        self.viewer_relationships_status_label = QLabel("No relationship sync yet")
        self.set_label_role(self.viewer_relationships_status_label, "mutedBody")
        self.viewer_relationships_status_label.setWordWrap(True)
        relationship_content_layout.addWidget(self.viewer_relationships_status_label)

        self.viewer_relationships_table = QTableView()
        self.viewer_relationships_model = IncrementalTableModel(("Account", "Details", "When"), batch_size=220, parent=self)
        self.viewer_relationships_table.setModel(self.viewer_relationships_model)
        self.viewer_relationships_table.verticalHeader().setVisible(False)
        self.viewer_relationships_table.setAlternatingRowColors(False)
        self.viewer_relationships_table.setShowGrid(False)
        self.viewer_relationships_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.viewer_relationships_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.viewer_relationships_table.setFocusPolicy(Qt.NoFocus)
        self.viewer_relationships_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.viewer_relationships_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.viewer_relationships_table.horizontalHeader().setStretchLastSection(False)
        self.viewer_relationships_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.viewer_relationships_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.viewer_relationships_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.viewer_relationships_table.verticalHeader().setDefaultSectionSize(42)
        self.viewer_relationships_table.setMinimumHeight(240)
        self.apply_dashboard_table_style(self.viewer_relationships_table)
        self.viewer_relationships_table.clicked.connect(self.open_relationship_profile)
        self.viewer_relationships_table.activated.connect(self.open_relationship_profile)
        self.viewer_relationships_table.doubleClicked.connect(self.open_relationship_profile)
        relationship_content_layout.addWidget(self.viewer_relationships_table)

        relationship_content_layout.addSpacing(6)
        relationship_pagination_row = QHBoxLayout()
        relationship_pagination_row.setSpacing(8)
        relationship_pagination_row.setContentsMargins(0, 6, 0, 0)
        self.viewer_relationship_page_info_label = QLabel("Page 1 / 1")
        self.set_label_role(self.viewer_relationship_page_info_label, "mutedBody")
        relationship_pagination_row.addWidget(self.viewer_relationship_page_info_label)
        relationship_pagination_row.addStretch()
        self.viewer_relationship_pagination_buttons_layout = QHBoxLayout()
        self.viewer_relationship_pagination_buttons_layout.setSpacing(6)
        relationship_pagination_row.addLayout(self.viewer_relationship_pagination_buttons_layout)
        relationship_content_layout.addLayout(relationship_pagination_row)

        relationship_actions = QHBoxLayout()
        relationship_actions.setSpacing(8)
        relationship_actions.addWidget(self.make_button("Refresh Lists", "primary", lambda: self.request_viewer_relationships_sync(force=True)))
        relationship_actions.addStretch()
        relationship_content_layout.addLayout(relationship_actions)

        relationship_layout.addWidget(self.viewer_relationships_content)
        right_layout.addWidget(relationship_card)

        right_layout.addWidget(
            self.build_dashboard_table_card(
                "Top Chatters",
                "Your most active chatters in the current snapshot, useful for quick moderation triage.",
                ("Viewer", "Messages"),
                "viewer_top_chatters_table",
            )
        )
        right_layout.addStretch()

        content_row.addWidget(right_column, 2)
        outer.addLayout(content_row)
        outer.addStretch()

        layout.addWidget(self.make_scroll_container(body))
        self.viewer_page_size = 50
        self.viewer_current_page = 1
        self.viewer_total_pages = 1
        self.viewer_filtered_records = []
        self.viewer_relationship_page_size = 50
        self.viewer_relationship_current_page = 1
        self.viewer_relationship_total_pages = 1
        self.viewer_relationship_current_rows = []
        self.viewer_relationship_rows_cache = {}
        self.set_sort_selector_value(self.viewer_sort_selector, getattr(self, "viewer_sort_key", "newest"))
        self.set_sort_selector_value(self.relationship_sort_selector, getattr(self, "relationship_sort_key", "newest"))
        self.sync_viewer_filter_buttons()
        self.clear_viewer_details_panel()
        self._apply_stream_summary(self.build_default_stream_summary())
        self.sync_viewer_list_category_buttons()
        self.refresh_viewer_relationships_panel()
        self.set_relationship_panel_expanded(True, animate=False)
        return page

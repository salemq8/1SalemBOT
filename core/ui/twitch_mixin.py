import threading
import time

import requests
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit, QMenu, QSizePolicy, QVBoxLayout, QWidget

from core.app_paths import TWITCH_GLITCH_LOGO_SVG
from core.auth import (
    BOT_AUTH_ROLE,
    CHANNEL_AUTH_ROLE,
    REDIRECT_URI,
    clear_token,
    extract_auth_state_from_redirect_url,
    extract_token_from_redirect_url,
    get_role_label,
    get_role_scopes,
    load_token_details,
    open_twitch_login,
    save_token,
)
from .widgets import Card, StatusDot


class DashboardTwitchMixin:
    def get_sidebar_account_card(self, role):
        if role == BOT_AUTH_ROLE:
            return getattr(self, "bot_account_card", None)
        if role == CHANNEL_AUTH_ROLE:
            return getattr(self, "channel_account_card", None)
        return None
    def get_auth_widgets(self, role):
        return self.auth_widgets.get(role, {})
    def open_twitch_setup_for_role(self, role):
        self.switch_page("Twitch")
        self.login_with_twitch(role)
    def get_auth_connection_state(self):
        bot_details = load_token_details(BOT_AUTH_ROLE)
        channel_details = load_token_details(CHANNEL_AUTH_ROLE)
        bot_health = self.get_role_auth_health(BOT_AUTH_ROLE, bot_details)
        channel_health = self.get_role_auth_health(CHANNEL_AUTH_ROLE, channel_details)
        return {
            "bot_details": bot_details,
            "channel_details": channel_details,
            "bot_connected": bot_health.get("state") == "connected",
            "channel_connected": channel_health.get("state") == "connected",
        }
    def get_role_auth_health(self, role, details=None):
        details = details or load_token_details(role)
        if not details.get("access_token"):
            return {"state": "disconnected", "message": "No saved token"}
        state = dict(getattr(self, "auth_health_state", {}).get(role, {}))
        if not state:
            return {"state": "connecting", "message": "Checking Twitch token"}
        if state.get("state") == "disconnected" and state.get("message") == "No saved token":
            return {"state": "connecting", "message": "Checking Twitch token"}
        return state
    def auth_dot_state(self, health_state):
        state = str((health_state or {}).get("state") or "disconnected")
        if state == "connected":
            return "connected"
        if state in {"connecting", "reconnecting", "waiting"}:
            return "connecting"
        return "disconnected"
    def auth_dot_tooltip(self, role, health_state):
        label = get_role_label(role)
        state = str((health_state or {}).get("state") or "disconnected")
        message = str((health_state or {}).get("message") or "").strip()
        if state == "connected":
            return self.localize("twitch.role_tooltip_connected", role=self.localize(label))
        if state in {"connecting", "reconnecting", "waiting"}:
            return self.localize("twitch.role_tooltip_checking", role=self.localize(label))
        if not message or message == "disconnected":
            return self.localize("twitch.role_tooltip_disconnected", role=self.localize(label))
        return f"{self.localize(label)}: {message}"
    def set_role_auth_health(self, role, state, message=""):
        if not hasattr(self, "auth_health_state"):
            return
        self.auth_health_state[role] = {
            "state": str(state or "disconnected"),
            "message": str(message or ""),
            "checked_at": time.time(),
        }
        self.refresh_token_status()
    def apply_login_defaults_from_auth(self, role, login_name):
        login_name = (login_name or "").strip()
        if not login_name:
            return

        widget_names = (
            ("settings_bot_login", "bot_login_entry")
            if role == BOT_AUTH_ROLE
            else ("settings_channel_login", "channel_login_entry")
        )
        for widget_name in widget_names:
            widget = getattr(self, widget_name, None)
            if widget is not None and not widget.text().strip():
                widget.setText(login_name)
    def copy_token_path(self, role=BOT_AUTH_ROLE):
        details = load_token_details(role)
        QApplication.clipboard().setText(details.get("path", ""))
        self.set_twitch_auth_feedback(
            role,
            f"{get_role_label(role)} token path copied. You only need this for backup or troubleshooting.",
            "info",
        )
        self.append_log(f"{get_role_label(role)} token file path copied")
    def mask_token(self, token: str):
        token = (token or "").strip()
        if len(token) <= 10:
            return token
        return f"{token[:6]}...{token[-4:]}"
    def paste_from_clipboard(self, apply_text, success_message):
        try:
            apply_text(QApplication.clipboard().text())
            self.append_log(success_message)
        except Exception:
            self.append_log("Clipboard unavailable")
    def build_twitch_logo_pixmap(self, size=38):
        pixmap = QPixmap(str(TWITCH_GLITCH_LOGO_SVG))
        if pixmap.isNull():
            return QPixmap()
        return pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def apply_soft_shadow(self, widget, *, blur=28, offset_y=10, alpha=78):
        if widget is None:
            return
        shadow = QGraphicsDropShadowEffect(widget)
        shadow.setBlurRadius(blur)
        shadow.setOffset(0, offset_y)
        shadow_color = QColor(self.theme.app_background)
        shadow_color.setAlpha(alpha)
        shadow.setColor(shadow_color)
        widget.setGraphicsEffect(shadow)

    def apply_twitch_auth_card_style(self, card, role):
        if card is None:
            return
        card.setStyleSheet(
            f"""
            QFrame[twitchAuthCard="true"] {{
                background: {self.theme.card_background};
                border: 1px solid {self.theme.border_color};
                border-radius: 20px;
            }}
            """
        )

    def apply_twitch_status_badge_style(self, label, tone="neutral"):
        if label is None:
            return
        if tone == "success":
            background = self.theme.success
            color = self.theme.text_inverse
        elif tone == "warning":
            background = self.theme.warning
            color = self.theme.warning_text
        elif tone in {"danger", "error"}:
            background = self.theme.danger
            color = self.theme.text_inverse
        else:
            background = self.theme.subtle_bg
            color = self.theme.text_secondary
        label.setStyleSheet(
            f"""
            QLabel {{
                background: {background};
                color: {color};
                border: none;
                border-radius: 14px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 800;
            }}
            """
        )
    def set_twitch_auth_feedback(self, role, text, tone="neutral"):
        helper_label = self.get_auth_widgets(role).get("helper_label")
        if helper_label is None:
            return

        color = self.theme.status_colors(tone).body
        self.set_localized_text(helper_label, text)
        helper_label.setStyleSheet(f"color:{color};font-size:12px;line-height:1.4;")
    def set_twitch_auth_summary(self, role, title, body, tone="neutral"):
        widgets = self.get_auth_widgets(role)
        summary_card = widgets.get("summary_card")
        summary_title = widgets.get("summary_title")
        summary_body = widgets.get("summary_body")
        if summary_card is None or summary_title is None or summary_body is None:
            return

        colors = self.theme.status_colors(tone)
        if tone == "success":
            summary_card.setStyleSheet(
                f"""
                QFrame[authSummaryCard="true"] {{
                    background: {self.theme.success};
                    border: none;
                    border-radius: 16px;
                }}
                """
            )
            title_color = self.theme.text_inverse
            body_color = "#ecfdf5"
        else:
            summary_card.setStyleSheet(
                f"""
                QFrame[authSummaryCard="true"] {{
                    background: {colors.background};
                    border: none;
                    border-radius: 16px;
                }}
                """
            )
            title_color = colors.title
            body_color = colors.body
        self.set_localized_text(summary_title, title)
        summary_title.setStyleSheet(f"color:{title_color};font-size:14px;font-weight:800;")
        self.set_localized_text(summary_body, body)
        summary_body.setStyleSheet(f"color:{body_color};font-size:12px;line-height:1.4;font-weight:500;")
    def build_twitch_step_card(self, step_number, title, description):
        card = QFrame()
        card.setProperty("surfaceRole", "twitchStepFlat")
        card.setStyleSheet(
            """
            QFrame[surfaceRole="twitchStepFlat"] {
                background: transparent;
                border: none;
            }
            """
        )

        layout = QHBoxLayout(card)
        layout.setContentsMargins(2, 6, 2, 6)
        layout.setSpacing(10)

        number_badge = QLabel(str(step_number))
        number_badge.setAlignment(Qt.AlignCenter)
        number_badge.setFixedSize(28, 28)
        number_badge.setProperty("badgeRole", "step")
        layout.addWidget(number_badge, 0, Qt.AlignTop)

        text_column = QVBoxLayout()
        text_column.setSpacing(2)

        title_label = QLabel(title)
        self.set_label_role(title_label, "stepTitle")
        text_column.addWidget(title_label)

        description_label = QLabel(description)
        description_label.setWordWrap(True)
        self.set_label_role(description_label, "stepBody")
        text_column.addWidget(description_label)

        layout.addLayout(text_column, 1)
        return card
    def build_twitch_account_card(self, role, title, description, capability_text):
        card = QFrame()
        card.setProperty("twitchAuthCard", "true")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.apply_twitch_auth_card_style(card, role)
        self.apply_soft_shadow(card, blur=30, offset_y=10, alpha=68)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        icon_label = QLabel()
        icon_label.setPixmap(self.build_twitch_logo_pixmap(40))
        icon_label.setFixedSize(44, 44)
        icon_label.setAlignment(Qt.AlignCenter)
        header_row.addWidget(icon_label, 0, Qt.AlignTop)

        heading_column = QVBoxLayout()
        heading_column.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        status_dot = StatusDot("disconnected", size=18, dot_size=7)
        title_row.addWidget(status_dot, 0, Qt.AlignVCenter)
        title_label = self.set_label_role(QLabel(title), "sectionTitle")
        title_row.addWidget(title_label, 1, Qt.AlignVCenter)
        heading_column.addLayout(title_row)
        subtitle_label = QLabel(description)
        subtitle_label.setWordWrap(True)
        self.set_label_role(subtitle_label, "muted")
        heading_column.addWidget(subtitle_label)
        header_row.addLayout(heading_column, 1)

        status_badge = QLabel("Not Connected")
        status_badge.setAlignment(Qt.AlignCenter)
        status_badge.setMinimumHeight(28)
        status_badge.setMinimumWidth(108)
        self.apply_twitch_status_badge_style(status_badge, "danger")
        header_row.addWidget(status_badge, 0, Qt.AlignTop)
        layout.addLayout(header_row)

        summary_card = QFrame()
        summary_card.setProperty("authSummaryCard", "true")
        self.apply_soft_shadow(summary_card, blur=20, offset_y=6, alpha=46)
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(14, 13, 14, 13)
        summary_layout.setSpacing(5)
        summary_title = self.set_label_role(QLabel(""), "smallTitle")
        summary_body = QLabel()
        summary_body.setWordWrap(True)
        self.set_label_role(summary_body, "mutedBody")
        summary_layout.addWidget(summary_title)
        summary_layout.addWidget(summary_body)
        layout.addWidget(summary_card)

        layout.addWidget(
            self.build_twitch_step_card(
                1,
                f"Connect {get_role_label(role)}",
                "Open Twitch approval in the browser for this specific role.",
            )
        )
        layout.addWidget(
            self.build_twitch_step_card(
                2,
                "Approve access",
                "Twitch redirects to the registered URL after approval. Copy the full final browser URL.",
            )
        )
        layout.addWidget(
            self.build_twitch_step_card(
                3,
                "Paste and save this role",
                f"Save the token only into {get_role_label(role)} so sessions never get mixed.",
            )
        )

        capability_label = QLabel(capability_text)
        capability_label.setWordWrap(True)
        self.set_label_role(capability_label, "mutedBody")
        layout.addWidget(capability_label)

        scope_label = QLabel("Required scopes: " + ", ".join(get_role_scopes(role)))
        scope_label.setWordWrap(True)
        self.set_label_role(scope_label, "muted")
        layout.addWidget(scope_label)

        callback_note = QLabel(f"Registered Twitch redirect URL: {REDIRECT_URI}")
        callback_note.setWordWrap(True)
        self.set_label_role(callback_note, "muted")
        layout.addWidget(callback_note)

        layout.addWidget(self.make_small_title("Browser Redirect URL"))
        redirect_entry = QLineEdit()
        redirect_entry.setPlaceholderText(f"Paste the full Twitch redirect URL for {title}")
        redirect_entry.setClearButtonEnabled(True)
        layout.addWidget(redirect_entry)

        account_row = QHBoxLayout()
        account_row.setSpacing(12)

        account_column = QVBoxLayout()
        account_column.setSpacing(2)
        account_label = self.set_label_role(QLabel("Connected Account"), "smallTitle")
        connected_value = self.set_label_role(QLabel("Not connected"), "valueLarge")
        account_column.addWidget(account_label)
        account_column.addWidget(connected_value)
        account_row.addLayout(account_column, 1)

        saved_column = QVBoxLayout()
        saved_column.setSpacing(2)
        saved_label = self.set_label_role(QLabel("Saved Session"), "smallTitle")
        token_meta_label = QLabel("No token saved on this PC yet.")
        token_meta_label.setWordWrap(True)
        self.set_label_role(token_meta_label, "mutedBody")
        saved_column.addWidget(saved_label)
        saved_column.addWidget(token_meta_label)
        account_row.addLayout(saved_column, 1)
        layout.addLayout(account_row)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)
        connect_button = self.make_button(f"Connect {get_role_label(role)}", "twitch", lambda: self.login_with_twitch(role))
        save_button = self.make_button("Paste & Save", "primary", lambda: self.paste_and_save_redirect_token(role))
        logout_button = self.make_button("Logout", "muted", lambda: self.logout_twitch_account(role))
        actions_row.addWidget(connect_button)
        actions_row.addWidget(save_button)
        actions_row.addWidget(logout_button)
        layout.addLayout(actions_row)

        helper_label = QLabel()
        helper_label.setWordWrap(True)
        layout.addWidget(helper_label)

        advanced_row = QHBoxLayout()
        advanced_row.setContentsMargins(0, 0, 0, 0)
        advanced_row.setSpacing(8)
        advanced_row.addStretch()
        copy_button = self.make_button(
            "Advanced: Copy Token File Path",
            "muted",
            lambda: self.copy_token_path(role),
        )
        advanced_row.addWidget(copy_button)
        layout.addLayout(advanced_row)

        self.auth_widgets[role] = {
            "account_card": card,
            "status_badge": status_badge,
            "status_dot": status_dot,
            "summary_card": summary_card,
            "summary_title": summary_title,
            "summary_body": summary_body,
            "redirect_entry": redirect_entry,
            "connected_value": connected_value,
            "token_meta_label": token_meta_label,
            "connect_button": connect_button,
            "save_button": save_button,
            "logout_button": logout_button,
            "helper_label": helper_label,
            "copy_button": copy_button,
        }
        return card
    def paste_and_save_redirect_token(self, role=BOT_AUTH_ROLE):
        clipboard_text = QApplication.clipboard().text().strip()
        if not clipboard_text:
            self.set_twitch_auth_feedback(
                role,
                "Nothing was found in the clipboard. Copy the full URL from your browser first, then click Paste & Save.",
                "error",
            )
            self.append_log(f"[TWITCH] Clipboard does not contain a redirect URL for {get_role_label(role)}")
            return

        widgets = self.get_auth_widgets(role)
        redirect_entry = widgets.get("redirect_entry")
        if redirect_entry is not None:
            redirect_entry.setText(clipboard_text)
        self.save_redirect_token(role, clipboard_text)
    def save_redirect_token(self, role=BOT_AUTH_ROLE, full_url=None):
        widgets = self.get_auth_widgets(role)
        redirect_entry = widgets.get("redirect_entry")
        full_url = (full_url or (redirect_entry.text() if redirect_entry is not None else "")).strip()
        if not full_url:
            self.set_twitch_auth_feedback(
                role,
                "Paste the full browser URL from the final Twitch page, then click save.",
                "error",
            )
            self.append_log(f"[TWITCH] Paste the full redirect URL first for {get_role_label(role)}")
            return

        auth_state = extract_auth_state_from_redirect_url(full_url)
        if auth_state and auth_state != role:
            self.set_twitch_auth_feedback(
                role,
                f"This redirect URL belongs to {get_role_label(auth_state)}, not {get_role_label(role)}. Use the matching save button so the two sessions stay separate.",
                "error",
            )
            self.append_log(
                f"[TWITCH] Role mismatch while saving token: expected {role}, received state={auth_state}"
            )
            return

        token = extract_token_from_redirect_url(full_url)
        if not token:
            self.set_twitch_auth_feedback(
                role,
                "This URL does not contain a Twitch access token. Copy the entire address from the browser page that opened after approval.",
                "error",
            )
            self.append_log(f"[TWITCH] Could not extract access token for {get_role_label(role)}")
            return

        try:
            details = save_token(token, role=role, source="redirect_url")
            if redirect_entry is not None:
                redirect_entry.clear()
            self.apply_login_defaults_from_auth(role, details.get("login"))
            self.refresh_token_status()
            self.refresh_account_widget(force=True)
            if hasattr(self, "request_auth_health_check"):
                self.request_auth_health_check(force=True)
            success_message = (
                "Bot account connected. You can now confirm Bot Login, then connect the Channel Account for full system access."
                if role == BOT_AUTH_ROLE
                else "Channel account connected. Live Alerts will start automatically, separate from Start Bot."
            )
            self.set_twitch_auth_feedback(
                role,
                success_message,
                "success",
            )
            self.append_log(
                f"[TWITCH] {get_role_label(role)} token saved successfully: {self.mask_token(details.get('access_token') or '')}"
            )
            self.append_log(f"[TWITCH] {get_role_label(role)} token file: {details.get('path')}")
            if role == CHANNEL_AUTH_ROLE and hasattr(self, "ensure_alerts_listener"):
                self.ensure_alerts_listener(force=True)
        except Exception as exc:
            self.set_twitch_auth_feedback(role, f"Could not save the Twitch token: {exc}", "error")
            self.append_log(f"[TWITCH] Failed to save {get_role_label(role)} token: {exc}")
    def login_with_twitch(self, role=BOT_AUTH_ROLE):
        try:
            self.set_role_auth_health(role, "waiting", "Waiting for Twitch approval")
            open_twitch_login(role)
            self.set_twitch_auth_summary(
                role,
                "Browser opened",
                f"Approve the Twitch request for {get_role_label(role)} in your browser. Then copy the final redirect URL and return here to save it.",
                "info",
            )
            self.set_twitch_auth_feedback(
                role,
                "After approval, copy the full browser URL and click Paste & Save.",
                "info",
            )
            self.append_log(f"[TWITCH] Opened login page for {get_role_label(role)}")
        except Exception as exc:
            self.set_twitch_auth_summary(
                role,
                "Could not open Twitch login",
                f"Browser step failed: {exc}",
                "error",
            )
            self.set_twitch_auth_feedback(role, f"Could not open the Twitch login page: {exc}", "error")
            self.append_log(f"[TWITCH] Login open failed for {get_role_label(role)}: {exc}")
    def refresh_token_status(self):
        connection_state = self.get_auth_connection_state()
        bot_details = connection_state["bot_details"]
        channel_details = connection_state["channel_details"]
        bot_connected = connection_state["bot_connected"]
        channel_connected = connection_state["channel_connected"]

        if bot_connected and channel_connected:
            summary_text = "BOT + CHANNEL"
            summary_caption = "Both Twitch roles are connected. Full channel features are available."
            summary_tone = "success"
        elif bot_connected:
            summary_text = "BOT ONLY"
            summary_caption = "Bot account is connected. Channel-level dashboard features stay limited until the channel account connects."
            summary_tone = "info"
        elif channel_connected:
            summary_text = "CHANNEL ONLY"
            summary_caption = "Channel account is connected, but the bot account is still required to send chat messages."
            summary_tone = "warning"
        else:
            summary_text = "NOT CONNECTED"
            summary_caption = "Connect Bot Account and Channel Account separately in Twitch Setup."
            summary_tone = "danger"

        self.set_localized_text(self.twitch_status_value, summary_text)
        self.set_status_value_style(self.twitch_status_value, summary_tone)
        if hasattr(self, "twitch_status_caption"):
            self.set_localized_text(self.twitch_status_caption, summary_caption)

        for role, details in ((BOT_AUTH_ROLE, bot_details), (CHANNEL_AUTH_ROLE, channel_details)):
            widgets = self.get_auth_widgets(role)
            if not widgets:
                continue

            token = details.get("access_token")
            saved_at = details.get("saved_at", "")
            configured_login = self.current_bot_login() if role == BOT_AUTH_ROLE else self.current_channel_login()
            login_name = details.get("login", "").strip() or configured_login.strip()
            health = self.get_role_auth_health(role, details)
            health_state = str(health.get("state") or "disconnected")
            health_message = str(health.get("message") or "").strip()
            dot_state = self.auth_dot_state(health)
            dot_tooltip = self.auth_dot_tooltip(role, health)
            status_badge = widgets.get("status_badge")
            status_dot = widgets.get("status_dot")
            account_card = widgets.get("account_card")
            connect_button = widgets.get("connect_button")
            save_button = widgets.get("save_button")
            logout_button = widgets.get("logout_button")
            connected_value = widgets.get("connected_value")
            token_meta_label = widgets.get("token_meta_label")

            if status_dot is not None:
                status_dot.set_state(dot_state, dot_tooltip)
            if account_card is not None:
                self.apply_twitch_auth_card_style(account_card, role)
            sidebar_card = self.get_sidebar_account_card(role)
            if sidebar_card is not None:
                sidebar_card.set_account_state(status_state=dot_state, status_tooltip=dot_tooltip)
            if status_badge is not None:
                status_text_map = {
                    "connected": "Connected",
                    "connecting": "Connecting",
                    "reconnecting": "Connecting",
                    "waiting": "Connecting",
                    "failed": "Token Invalid",
                    "disconnected": "Not Connected",
                }
                tone_map = {
                    "connected": "success",
                    "connecting": "warning",
                    "reconnecting": "warning",
                    "waiting": "warning",
                    "failed": "danger",
                    "disconnected": "danger",
                }
                self.set_localized_text(status_badge, status_text_map.get(health_state, "Not Connected"))
                self.apply_twitch_status_badge_style(status_badge, tone_map.get(health_state, "danger"))
            if connect_button is not None:
                connect_button.setEnabled(True)
                self.set_localized_text(
                    connect_button,
                    "twitch.reconnect_role" if token else "twitch.connect_role",
                    role=self.localize(get_role_label(role)),
                )
            if save_button is not None:
                save_button.setEnabled(True)
            if logout_button is not None:
                logout_button.setEnabled(bool(token))
            if connected_value is not None:
                if token:
                    self.clear_i18n_binding(connected_value)
                    connected_value.setText(login_name)
                else:
                    self.set_localized_text(connected_value, "Not connected")

            if token:
                scope_count = len(details.get("scopes", []))
                if token_meta_label is not None:
                    meta_text = f"Saved token: {self.mask_token(token)}"
                    if saved_at:
                        meta_text += f"  |  Saved at {saved_at}"
                    meta_text += f"  |  {scope_count} granted scopes"
                    self.set_localized_text(token_meta_label, meta_text)

                if health_state != "connected":
                    if health_state in {"connecting", "reconnecting", "waiting"}:
                        title = f"{get_role_label(role)} checking connection"
                        body = health_message or "Validating this Twitch session."
                        tone = "warning"
                        helper_text = "Checking Twitch connection."
                    else:
                        title = f"{get_role_label(role)} needs reconnect"
                        body = health_message or "The saved Twitch token is not valid."
                        tone = "error"
                        helper_text = "Reconnect this Twitch role to restore access."
                    if login_name:
                        body += f" Last saved as {login_name}."
                    self.set_twitch_auth_summary(role, title, body, tone)
                    self.set_twitch_auth_feedback(role, helper_text, tone)
                    continue

                if role == BOT_AUTH_ROLE:
                    title = "Bot account ready"
                    body = "This role is used for sending chat messages, handling commands, and moderation actions."
                    helper = "Use the bot account that should speak in chat."
                else:
                    title = "Channel account ready"
                    body = "This role unlocks broadcaster-level dashboard features, moderation context, analytics, and channel controls."
                    helper = "Use the streamer/channel account here so advanced channel features stay enabled."

                if login_name:
                    body += f"\nConnected as {login_name}."
                self.set_twitch_auth_summary(role, title, body, "success")
                helper_text = "Twitch connected successfully."
                if saved_at:
                    helper_text += f" Saved at {saved_at}."
                self.set_twitch_auth_feedback(role, helper_text + f" {helper}", "success")
            else:
                if token_meta_label is not None:
                    self.set_localized_text(token_meta_label, "No token saved on this PC yet.")
                if role == BOT_AUTH_ROLE:
                    title = "Connect the bot account"
                    body = "Log in with the account that will send messages, respond to commands, and perform moderation actions."
                else:
                    title = "Connect the channel account"
                    body = "Log in with the streamer or broadcaster account to unlock analytics, music controls, viewer data, and channel-level features."
                self.set_twitch_auth_summary(role, title, body, "neutral")
                self.set_twitch_auth_feedback(
                    role,
                    "Open Twitch in the browser, approve access, then paste the final redirect URL here and save it for this role only.",
                    "neutral",
                )
        self.update_dashboard_status_badge()
    def show_account_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(
            f"""
            QMenu {
                background-color: {self.theme.panel_background};
                color: {self.theme.text_primary};
                border: 1px solid {self.theme.border_color};
                border-radius: 12px;
                padding: 8px;
            }
            QMenu::item {
                background-color: transparent;
                color: {self.theme.text_primary};
                padding: 8px 16px;
                border-radius: 8px;
            }
            QMenu::item:selected {
                background-color: {self.theme.accent_color};
                color: {self.theme.text_inverse};
            }
            """
        )

        settings_action = menu.addAction(self.localize("Bot Settings"))
        twitch_action = menu.addAction(self.localize("Twitch Setup"))
        refresh_action = menu.addAction(self.localize("Refresh Account"))
        bot_details = load_token_details(BOT_AUTH_ROLE)
        channel_details = load_token_details(CHANNEL_AUTH_ROLE)
        bot_connected = bool(bot_details.get("access_token"))
        channel_connected = bool(channel_details.get("access_token"))
        reconnect_bot_action = menu.addAction(self.localize("Reconnect Bot Account"))
        reconnect_channel_action = menu.addAction(self.localize("Reconnect Channel Account"))
        copy_bot_path_action = menu.addAction(self.localize("Copy Bot Token Path"))
        copy_channel_path_action = menu.addAction(self.localize("Copy Channel Token Path"))
        logout_bot_action = menu.addAction(self.localize("Logout Bot Account"))
        logout_channel_action = menu.addAction(self.localize("Logout Channel Account"))
        copy_bot_path_action.setEnabled(bool(bot_details.get("path")))
        copy_channel_path_action.setEnabled(bool(channel_details.get("path")))
        logout_bot_action.setEnabled(bot_connected)
        logout_channel_action.setEnabled(channel_connected)

        anchor_widget = getattr(self, "sidebar_accounts_card", None) or self
        selected = menu.exec(anchor_widget.mapToGlobal(anchor_widget.rect().bottomLeft()))
        if selected == settings_action:
            self.switch_page("Bot Settings")
        elif selected == twitch_action:
            self.switch_page("Twitch")
        elif selected == refresh_action:
            self.refresh_account_widget(force=True)
        elif selected == reconnect_bot_action:
            self.switch_page("Twitch")
            self.login_with_twitch(BOT_AUTH_ROLE)
        elif selected == reconnect_channel_action:
            self.switch_page("Twitch")
            self.login_with_twitch(CHANNEL_AUTH_ROLE)
        elif selected == copy_bot_path_action:
            self.copy_token_path(BOT_AUTH_ROLE)
        elif selected == copy_channel_path_action:
            self.copy_token_path(CHANNEL_AUTH_ROLE)
        elif selected == logout_bot_action:
            self.logout_twitch_account(BOT_AUTH_ROLE)
        elif selected == logout_channel_action:
            self.logout_twitch_account(CHANNEL_AUTH_ROLE)
    def logout_twitch_account(self, role=BOT_AUTH_ROLE):
        if self.process is not None and self.process.poll() is None:
            self.stop_bot()
        if role == CHANNEL_AUTH_ROLE and hasattr(self, "stop_alerts_listener"):
            self.stop_alerts_listener()
        try:
            clear_token(role)
            self.set_role_auth_health(role, "disconnected", "No saved token")
            self.refresh_token_status()
            self.refresh_account_widget(force=True)
            if hasattr(self, "update_alerts_status_ui"):
                self.update_alerts_status_ui()
            self.append_log(f"[TWITCH] {get_role_label(role)} logged out")
        except Exception as exc:
            self.append_log(f"[TWITCH] Failed to log out {get_role_label(role)}: {exc}")
    def _apply_account_profile(self, payload):
        role = payload.get("role", BOT_AUTH_ROLE)
        request_id = payload.get("request_id")
        current_request_id = self.account_profile_request_ids.get(role)
        if request_id is not None and request_id != current_request_id:
            return

        card = self.get_sidebar_account_card(role)
        if card is None:
            return

        display_name = payload.get("display_name") or "Not connected"
        avatar_bytes = payload.get("avatar_bytes")
        fallback_text = (payload.get("login") or display_name or ("B" if role == BOT_AUTH_ROLE else "C"))[:1]

        avatar_pixmap = None
        if avatar_bytes:
            image = QPixmap()
            image.loadFromData(avatar_bytes)
            avatar_pixmap = self.build_avatar_pixmap(image, fallback_text=fallback_text, size=30)
        else:
            avatar_pixmap = self.build_avatar_pixmap(fallback_text=fallback_text, size=30)

        card.set_account_state(
            role_title=payload.get("role_title") or ("Bot" if role == BOT_AUTH_ROLE else "Channel"),
            username=display_name,
            avatar=avatar_pixmap,
            status_state=self.auth_dot_state(self.get_role_auth_health(role)),
            status_tooltip=self.auth_dot_tooltip(role, self.get_role_auth_health(role)),
        )
    def _base_sidebar_account_payload(self, role, request_id, display_name, login_name, *, connected):
        return {
            "role": role,
            "request_id": request_id,
            "role_title": "Bot" if role == BOT_AUTH_ROLE else "Channel",
            "display_name": display_name,
            "login": login_name,
            "avatar_bytes": None,
        }
    def _refresh_sidebar_account(self, role, force=False):
        details = load_token_details(role)
        token = details.get("access_token")
        stored_login = details.get("login", "").strip()
        stored_display_name = details.get("display_name", "").strip()
        stored_profile_image_url = details.get("profile_image_url", "").strip()
        configured_login = self.current_bot_login() if role == BOT_AUTH_ROLE else self.current_channel_login()
        lookup_login = stored_login or configured_login
        display_login = stored_display_name or lookup_login or configured_login

        self.account_profile_request_ids[role] = self.account_profile_request_ids.get(role, 0) + 1
        request_id = self.account_profile_request_ids[role]

        if not token:
            self._apply_account_profile(
                self._base_sidebar_account_payload(
                    role,
                    request_id,
                display_login or "Not connected",
                    stored_login or configured_login or ("bot" if role == BOT_AUTH_ROLE else "channel"),
                    connected=False,
                )
            )
            return

        self._apply_account_profile(
            self._base_sidebar_account_payload(
                role,
                request_id,
                display_login or stored_login or "Connected",
                stored_login or configured_login or ("bot" if role == BOT_AUTH_ROLE else "channel"),
                connected=True,
            )
        )

        def worker():
            try:
                user = None
                avatar_bytes = None
                display_name = stored_display_name or lookup_login or stored_login or "Connected"
                login_name = stored_login or lookup_login or ("bot" if role == BOT_AUTH_ROLE else "channel")
                avatar_url = stored_profile_image_url

                if lookup_login:
                    try:
                        user = get_user_by_login(CLIENT_ID, token, lookup_login)
                    except Exception as exc:
                        self.bridge.log_signal.emit(
                            f"[TWITCH] {get_role_label(role)} profile lookup failed for {lookup_login}: {exc}"
                        )

                if user:
                    display_name = user.get("display_name") or display_name
                    login_name = user.get("login") or login_name
                    avatar_url = user.get("profile_image_url") or avatar_url

                if avatar_url:
                    try:
                        response = requests.get(avatar_url, timeout=15)
                        response.raise_for_status()
                        avatar_bytes = response.content
                    except Exception as exc:
                        self.bridge.log_signal.emit(
                            f"[TWITCH] {get_role_label(role)} avatar load failed from {avatar_url}: {exc}"
                        )
                else:
                    self.bridge.log_signal.emit(
                        f"[TWITCH] {get_role_label(role)} avatar URL missing; using fallback avatar"
                    )

                payload = self._base_sidebar_account_payload(
                    role,
                    request_id,
                    display_name,
                    login_name,
                    connected=True,
                )
                payload["avatar_bytes"] = avatar_bytes
                self.bridge.account_signal.emit(payload)
            except Exception as exc:
                if force:
                    self.bridge.log_signal.emit(
                        f"[TWITCH] Failed to refresh {get_role_label(role)} sidebar card: {exc}"
                    )
                self.bridge.account_signal.emit(
                    self._base_sidebar_account_payload(
                        role,
                        request_id,
                        display_login or stored_login or "Connected",
                        display_login or stored_login or ("bot" if role == BOT_AUTH_ROLE else "channel"),
                        connected=True,
                    )
                )

        threading.Thread(target=worker, daemon=True).start()
    def refresh_account_widget(self, force=False):
        self._refresh_sidebar_account(BOT_AUTH_ROLE, force=force)
        self._refresh_sidebar_account(CHANNEL_AUTH_ROLE, force=force)
    def build_twitch_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(14)

        self.twitch_page_intro_card = Card()
        intro_layout = QVBoxLayout(self.twitch_page_intro_card)
        intro_layout.setContentsMargins(14, 14, 14, 14)
        intro_layout.setSpacing(8)
        intro_layout.addWidget(self.make_title("Twitch Setup"))

        intro_text = QLabel(
            "This page is only for Twitch connection and account authorization. "
            "Use Bot Settings for bot login, channel login, triggers, and the rest of the bot configuration."
        )
        intro_text.setWordWrap(True)
        self.set_label_role(intro_text, "mutedBody")
        intro_layout.addWidget(intro_text)

        unlocks_label = QLabel(
            "Bot Account: sends chat messages, runs commands, and performs moderation actions.\n"
            "Channel Account: unlocks broadcaster-level dashboard access, analytics, music control, and channel context.\n"
            "If both are connected, the full system is enabled."
        )
        unlocks_label.setWordWrap(True)
        self.set_label_role(unlocks_label, "mutedBody")
        intro_layout.addWidget(unlocks_label)
        body_layout.addWidget(self.twitch_page_intro_card)

        body_layout.addWidget(
            self.build_twitch_account_card(
                BOT_AUTH_ROLE,
                "Bot Account Login",
                "Used for sending chat messages, handling commands, and moderation actions.",
                "Connect the dedicated bot account here. Even if you use the same Twitch account for both roles, the app stores this login separately as the bot session.",
            )
        )
        body_layout.addWidget(
            self.build_twitch_account_card(
                CHANNEL_AUTH_ROLE,
                "Channel Account Login",
                "Used for broadcaster-level permissions, dashboard analytics, music control, and channel systems.",
                "Connect the streamer or channel owner account here so dashboard features can use the broader broadcaster and moderation scopes independently from the bot session.",
            )
        )
        body_layout.addStretch()

        layout.addWidget(self.make_scroll_container(body))
        return page

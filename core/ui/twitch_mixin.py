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
    CLIENT_ID,
    REDIRECT_URI,
    begin_role_auth_flow,
    clear_token,
    exchange_device_code,
    extract_auth_state_from_redirect_url,
    extract_token_from_redirect_url,
    get_role_label,
    get_role_scopes,
    load_token_details,
    mark_role_disconnected,
    open_twitch_login,
    save_token_response,
    save_token,
    set_role_auth_runtime_state,
    start_device_code_authorization,
    validate_token,
)
from core.twitch_api import get_user_by_login
from .twitch_device_dialog import TwitchDeviceAuthDialog
from .widgets import Card, StatusDot


PROFILE_LOOKUP_COOLDOWN_SECONDS = 180


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
                "Connect with Twitch",
                "The app opens Twitch and shows a short authorization code for this specific role.",
            )
        )
        layout.addWidget(
            self.build_twitch_step_card(
                2,
                "Approve access",
                "Enter the displayed code if needed, then approve access on Twitch.",
            )
        )
        layout.addWidget(
            self.build_twitch_step_card(
                3,
                "Connected automatically",
                f"1SalemBOT validates and securely saves only the {get_role_label(role)} session.",
            )
        )

        capability_label = QLabel(capability_text)
        capability_label.setWordWrap(True)
        self.set_label_role(capability_label, "mutedBody")
        layout.addWidget(capability_label)

        scope_label = QLabel("Required Twitch permissions are requested automatically for this role.")
        scope_label.setWordWrap(True)
        self.set_label_role(scope_label, "muted")
        layout.addWidget(scope_label)

        legacy_frame = QFrame()
        legacy_frame.setProperty("surfaceRole", "subtle")
        legacy_frame.setVisible(False)
        legacy_layout = QVBoxLayout(legacy_frame)
        legacy_layout.setContentsMargins(12, 12, 12, 12)
        legacy_layout.setSpacing(8)
        callback_note = QLabel(f"Registered Twitch redirect URL: {REDIRECT_URI}")
        callback_note.setWordWrap(True)
        self.set_label_role(callback_note, "muted")
        legacy_layout.addWidget(callback_note)
        legacy_scope_label = QLabel("Required scopes: " + ", ".join(get_role_scopes(role)))
        legacy_scope_label.setWordWrap(True)
        self.set_label_role(legacy_scope_label, "muted")
        legacy_layout.addWidget(legacy_scope_label)

        legacy_layout.addWidget(self.make_small_title("Browser Redirect URL"))
        redirect_entry = QLineEdit()
        redirect_entry.setPlaceholderText(f"Paste the full Twitch redirect URL for {title}")
        redirect_entry.setClearButtonEnabled(True)
        legacy_layout.addWidget(redirect_entry)
        save_button = self.make_button("Paste & Save", "primary", lambda: self.paste_and_save_redirect_token(role))
        legacy_layout.addWidget(save_button, 0, Qt.AlignLeft)

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
        connect_button = self.make_button("Connect with Twitch", "twitch", lambda: self.login_with_twitch(role))
        logout_button = self.make_button("Logout", "muted", lambda: self.logout_twitch_account(role))
        legacy_toggle_button = self.make_button(
            "Developer Diagnostics: Legacy Redirect Login",
            "muted",
            lambda frame=legacy_frame: frame.setVisible(not frame.isVisible()),
        )
        actions_row.addWidget(connect_button)
        actions_row.addWidget(logout_button)
        actions_row.addWidget(legacy_toggle_button)
        layout.addLayout(actions_row)
        layout.addWidget(legacy_frame)

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
            "legacy_frame": legacy_frame,
            "legacy_toggle_button": legacy_toggle_button,
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
    def twitch_device_auth_task_name(self, role):
        return f"twitch_device_auth_{role}"

    def emit_twitch_device_auth_event(self, role, request_id, **payload):
        event = {"role": role, "request_id": request_id}
        event.update(payload)
        self.bridge.twitch_device_auth_signal.emit(event)

    def friendly_twitch_device_error(self, error_code):
        code = str(error_code or "").lower()
        if code == "authorization_pending":
            return "Waiting for Twitch authorization..."
        if code == "slow_down":
            return "Twitch asked the app to slow down. Waiting before checking again..."
        if code in {"access_denied", "authorization_declined", "denied"}:
            return "Twitch authorization was not approved."
        if code in {"expired_token", "expired_device_code", "invalid_device_code"}:
            return "This authorization code has expired. Generate a new code to continue."
        if "timeout" in code or "connection" in code or "network" in code:
            return "Could not reach Twitch. Check your internet connection and try again."
        if "missing" in code and "scope" in code:
            return "Twitch connected, but some required permissions were not approved. Please reconnect and approve all requested access."
        return "Twitch authorization failed. Please try again."

    def cancel_twitch_device_auth(self, role, request_id=None):
        current_request = self.twitch_device_auth_request_ids.get(role)
        if request_id is not None and request_id != current_request:
            return
        task_manager = getattr(self, "task_manager", None)
        if task_manager is not None:
            task_manager.cancel(self.twitch_device_auth_task_name(role))
        set_role_auth_runtime_state(role, "needs_reconnect", "Authorization cancelled")
        self.set_twitch_auth_feedback(role, "Cancelled", "warning")
        self.refresh_token_status()
        self.append_log(f"[TWITCH] {get_role_label(role)} authorization cancelled")

    def login_with_twitch(self, role=BOT_AUTH_ROLE):
        role = BOT_AUTH_ROLE if role == BOT_AUTH_ROLE else CHANNEL_AUTH_ROLE
        task_name = self.twitch_device_auth_task_name(role)
        task_manager = getattr(self, "task_manager", None)
        if task_manager is not None and task_manager.is_running(task_name):
            dialog = self.twitch_device_auth_dialogs.get(role)
            if dialog is not None:
                dialog.show()
                dialog.raise_()
                dialog.activateWindow()
            self.append_log(f"[TWITCH] {get_role_label(role)} authorization already in progress")
            return

        begin_role_auth_flow(role)
        self.twitch_device_auth_request_ids[role] = self.twitch_device_auth_request_ids.get(role, 0) + 1
        request_id = self.twitch_device_auth_request_ids[role]
        self.set_role_auth_health(role, "waiting", "Preparing Twitch authorization")
        self.set_twitch_auth_summary(role, f"Connect {get_role_label(role)} to Twitch", "Preparing Twitch authorization.", "warning")
        self.set_twitch_auth_feedback(role, "Preparing authorization", "warning")
        self.refresh_token_status()
        expected_login = self.current_bot_login() if role == BOT_AUTH_ROLE else self.current_channel_login()

        dialog = TwitchDeviceAuthDialog(role=role, theme=self.theme, localize=self.localize, parent=self)
        dialog.cancelled.connect(lambda role_name=role, rid=request_id: self.cancel_twitch_device_auth(role_name, rid))
        self.twitch_device_auth_dialogs[role] = dialog
        dialog.show()

        def worker(cancel_event=None, role_name=role, rid=request_id, configured_login=expected_login):
            try:
                if cancel_event is not None and cancel_event.is_set():
                    self.emit_twitch_device_auth_event(role_name, rid, state="cancelled", message="Cancelled")
                    return {"cancelled": True}
                self.emit_twitch_device_auth_event(role_name, rid, state="preparing", message="Preparing authorization")
                session = start_device_code_authorization(role_name)
                expires_at = time.time() + int(session.get("expires_in") or 0)
                interval = max(1, int(session.get("interval") or 5))
                self.emit_twitch_device_auth_event(
                    role_name,
                    rid,
                    state="waiting",
                    message="Waiting for Twitch authorization...",
                    user_code=session.get("user_code"),
                    verification_uri=session.get("verification_uri"),
                    expires_at=expires_at,
                    interval=interval,
                )
                while time.time() < expires_at:
                    if cancel_event is not None and cancel_event.wait(interval):
                        self.emit_twitch_device_auth_event(role_name, rid, state="cancelled", message="Cancelled")
                        return {"cancelled": True}
                    token_result = exchange_device_code(session.get("device_code"), role_name)
                    if cancel_event is not None and cancel_event.is_set():
                        self.emit_twitch_device_auth_event(role_name, rid, state="cancelled", message="Cancelled")
                        return {"cancelled": True}
                    if token_result.get("ok"):
                        self.emit_twitch_device_auth_event(role_name, rid, state="validating", message="Validating account")
                        validation = validate_token(token_result.get("access_token"))
                        if cancel_event is not None and cancel_event.is_set():
                            self.emit_twitch_device_auth_event(role_name, rid, state="cancelled", message="Cancelled")
                            return {"cancelled": True}
                        actual_login = str(validation.get("login") or "").strip()
                        if configured_login and actual_login and configured_login.casefold() != actual_login.casefold():
                            self.emit_twitch_device_auth_event(
                                role_name,
                                rid,
                                state="failed",
                                message=(
                                    f"Twitch connected as {actual_login}, but this role is configured for {configured_login}. "
                                    "Update the configured login or reconnect with the matching account."
                                ),
                            )
                            return {"error": "wrong_account"}
                        self.emit_twitch_device_auth_event(role_name, rid, state="saving", message="Saving session")
                        details = save_token_response(token_result, role=role_name, source="device_code", validation_details=validation)
                        self.emit_twitch_device_auth_event(
                            role_name,
                            rid,
                            state="connected",
                            message=f"Twitch connected. Connected as {details.get('display_name') or details.get('login') or actual_login}.",
                            login=details.get("login", ""),
                            display_name=details.get("display_name", ""),
                        )
                        return {"details": details}
                    error_code = token_result.get("error")
                    if error_code == "authorization_pending":
                        continue
                    if error_code == "slow_down":
                        interval += 5
                        self.emit_twitch_device_auth_event(role_name, rid, state="waiting", message=self.friendly_twitch_device_error(error_code))
                        continue
                    if error_code in {"access_denied", "authorization_declined", "denied"}:
                        self.emit_twitch_device_auth_event(role_name, rid, state="denied", message=self.friendly_twitch_device_error(error_code))
                        return {"error": error_code}
                    if error_code in {"expired_token", "expired_device_code", "invalid_device_code"}:
                        self.emit_twitch_device_auth_event(role_name, rid, state="expired", message=self.friendly_twitch_device_error(error_code))
                        return {"error": error_code}
                    self.emit_twitch_device_auth_event(role_name, rid, state="failed", message=self.friendly_twitch_device_error(error_code))
                    return {"error": error_code}
                self.emit_twitch_device_auth_event(role_name, rid, state="expired", message="This authorization code has expired. Generate a new code to continue.")
                return {"error": "expired_device_code"}
            except Exception as exc:
                self.emit_twitch_device_auth_event(
                    role_name,
                    rid,
                    state="failed",
                    message=self.friendly_twitch_device_error(exc.__class__.__name__),
                    diagnostic=exc.__class__.__name__,
                )
                return {"error": exc.__class__.__name__}

        def on_error(error_text, role_name=role, rid=request_id):
            self.emit_twitch_device_auth_event(role_name, rid, state="failed", message=self.friendly_twitch_device_error(error_text))

        if task_manager is not None:
            if not task_manager.start(task_name, worker, on_success=lambda _result: None, on_error=on_error):
                self.append_log(f"[TWITCH] {get_role_label(role)} authorization already in progress")
            return

        threading.Thread(target=lambda: worker(), daemon=True).start()

    def handle_twitch_device_auth_event(self, payload):
        if not isinstance(payload, dict):
            return
        role = payload.get("role")
        if role not in (BOT_AUTH_ROLE, CHANNEL_AUTH_ROLE):
            return
        request_id = payload.get("request_id")
        if request_id != self.twitch_device_auth_request_ids.get(role):
            return
        state = str(payload.get("state") or "").strip()
        dialog = self.twitch_device_auth_dialogs.get(role)
        if dialog is not None:
            dialog.update_state(payload)
        status_map = {
            "preparing": ("waiting", "Preparing Twitch authorization"),
            "waiting": ("waiting", "Waiting for Twitch authorization"),
            "validating": ("connecting", "Validating Twitch session"),
            "saving": ("connecting", "Saving Twitch session"),
            "connected": ("connected", "Twitch connected successfully."),
            "failed": ("failed", payload.get("message") or "Twitch authorization failed"),
            "expired": ("failed", "Code expired"),
            "denied": ("failed", "Authorization declined"),
            "cancelled": ("disconnected", "Cancelled"),
        }
        health_state, health_message = status_map.get(state, ("waiting", payload.get("message") or "Waiting for Twitch authorization"))
        runtime_state_map = {
            "preparing": "waiting_for_device_code",
            "waiting": "waiting_for_user_approval",
            "validating": "validating",
            "saving": "validating",
            "connected": "connected",
            "failed": "failed",
            "expired": "needs_reconnect",
            "denied": "needs_reconnect",
            "cancelled": "needs_reconnect",
        }
        if state in runtime_state_map and state != "connected":
            set_role_auth_runtime_state(role, runtime_state_map[state], health_message, explicit_disconnected=False)
        self.set_role_auth_health(role, health_state, health_message)
        if state == "connected":
            self.append_log(f"[TWITCH] {get_role_label(role)} connected")
            self.refresh_token_status()
            self.refresh_account_widget(force=True)
            self.request_auth_health_check(force=True)
            if role == CHANNEL_AUTH_ROLE:
                self.ensure_alerts_listener(force=True)
            return
        if state in {"failed", "expired", "denied", "cancelled"}:
            self.append_log(f"[TWITCH] {get_role_label(role)} authorization {state}")
        self.refresh_token_status()
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
                    "Reconnect" if token else "Connect with Twitch",
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
                if token_meta_label is not None:
                    meta_text = "Secure session saved"
                    if saved_at:
                        meta_text += f"  |  Saved at {saved_at}"
                    if details.get("last_validated_at"):
                        meta_text += f"  |  Last validated {details.get('last_validated_at')}"
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
                    "Press Connect with Twitch. The app will open Twitch, show a code, and save the approved session automatically.",
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
        role = BOT_AUTH_ROLE if role == BOT_AUTH_ROLE else CHANNEL_AUTH_ROLE
        task_manager = getattr(self, "task_manager", None)
        if task_manager is not None:
            task_manager.cancel(self.twitch_device_auth_task_name(role))
            task_manager.cancel(f"auth_check_{role}")
            task_manager.cancel(self.account_profile_task_name(role))
        self.twitch_device_auth_request_ids[role] = self.twitch_device_auth_request_ids.get(role, 0) + 1
        self.account_profile_request_ids[role] = self.account_profile_request_ids.get(role, 0) + 1
        self.auth_health_request_ids[role] = self.auth_health_request_ids.get(role, 0) + 1
        self.auth_health_inflight[role] = False
        dialog = self.twitch_device_auth_dialogs.get(role)
        if dialog is not None:
            dialog.close()
            self.twitch_device_auth_dialogs[role] = None
        mark_role_disconnected(role)
        if role == BOT_AUTH_ROLE and self.process is not None and self.process.poll() is None:
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
        if getattr(self, "_closing", False):
            return
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
    def account_profile_task_name(self, role):
        return f"account_profile_{role}"
    def account_profile_failure_key(self, error):
        return str(error or "").strip().splitlines()[-1][:180]
    def should_skip_account_profile_lookup(self, role, error_key, *, force=False):
        if force:
            return False
        state = getattr(self, "account_profile_failure_state", {}).get(role, {})
        if not state:
            return False
        if state.get("error") != error_key:
            return False
        return time.time() < float(state.get("next_retry_at", 0.0) or 0.0)
    def mark_account_profile_failure(self, role, error):
        error_key = self.account_profile_failure_key(error)
        state = getattr(self, "account_profile_failure_state", {}).setdefault(role, {"error": "", "next_retry_at": 0.0})
        should_log = state.get("error") != error_key
        state["error"] = error_key
        state["next_retry_at"] = time.time() + PROFILE_LOOKUP_COOLDOWN_SECONDS
        if should_log:
            self.bridge.log_signal.emit(f"[TWITCH] {get_role_label(role)} profile lookup failed: {error_key}")
        return error_key
    def mark_account_profile_success(self, role):
        state = getattr(self, "account_profile_failure_state", {}).setdefault(role, {"error": "", "next_retry_at": 0.0})
        if state.get("error"):
            self.bridge.log_signal.emit(f"[TWITCH] {get_role_label(role)} profile lookup recovered")
        state["error"] = ""
        state["next_retry_at"] = 0.0
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

        lookup_signature = "|".join(
            [
                str(role),
                str(lookup_login or "").strip().lower(),
                str(stored_profile_image_url or "").strip(),
                "token" if token else "no-token",
            ]
        )
        task_manager = getattr(self, "task_manager", None)
        task_name = self.account_profile_task_name(role)
        if task_manager is not None and task_manager.is_running(task_name):
            if force or self.account_profile_lookup_signatures.get(role) != lookup_signature:
                task_manager.cancel(task_name)
            else:
                return

        self.account_profile_request_ids[role] = self.account_profile_request_ids.get(role, 0) + 1
        request_id = self.account_profile_request_ids[role]
        self.account_profile_lookup_signatures[role] = lookup_signature

        if not token:
            if task_manager is not None:
                task_manager.cancel(task_name)
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

        failure_state = getattr(self, "account_profile_failure_state", {}).get(role, {})
        if (
            not force
            and failure_state.get("error")
            and time.time() < float(failure_state.get("next_retry_at", 0.0) or 0.0)
        ):
            return

        def worker(cancel_event=None):
            if cancel_event is not None and cancel_event.is_set():
                return None
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
                        error_key = self.mark_account_profile_failure(role, exc)
                        if self.should_skip_account_profile_lookup(role, error_key, force=force):
                            return None

                if user:
                    self.mark_account_profile_success(role)
                    display_name = user.get("display_name") or display_name
                    login_name = user.get("login") or login_name
                    avatar_url = user.get("profile_image_url") or avatar_url

                if avatar_url:
                    try:
                        response = requests.get(avatar_url, timeout=15)
                        response.raise_for_status()
                        avatar_bytes = response.content
                    except Exception as exc:
                        if force:
                            self.bridge.log_signal.emit(f"[TWITCH] {get_role_label(role)} avatar load failed: {exc}")

                payload = self._base_sidebar_account_payload(
                    role,
                    request_id,
                    display_name,
                    login_name,
                    connected=True,
                )
                payload["avatar_bytes"] = avatar_bytes
                return payload
            except Exception as exc:
                if force:
                    self.mark_account_profile_failure(role, exc)
                return self._base_sidebar_account_payload(
                    role,
                    request_id,
                    display_login or stored_login or "Connected",
                    display_login or stored_login or ("bot" if role == BOT_AUTH_ROLE else "channel"),
                    connected=True,
                )

        def on_result(payload):
            if payload is not None and not getattr(self, "_closing", False):
                self.bridge.account_signal.emit(payload)

        def on_error(error_text):
            self.mark_account_profile_failure(role, error_text)
            on_result(
                self._base_sidebar_account_payload(
                    role,
                    request_id,
                    display_login or stored_login or "Connected",
                    display_login or stored_login or ("bot" if role == BOT_AUTH_ROLE else "channel"),
                    connected=True,
                )
            )

        if task_manager is not None:
            task_manager.start(task_name, worker, on_success=on_result, on_error=on_error)
            return

        on_result(worker())
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

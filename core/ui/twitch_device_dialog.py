import time

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
from PySide6.QtGui import QDesktopServices

from core.auth import BOT_AUTH_ROLE, get_role_label


class TwitchDeviceAuthDialog(QDialog):
    cancelled = Signal()

    def __init__(self, *, role, theme, localize, parent=None):
        super().__init__(parent)
        self.role = role
        self.theme = theme
        self.localize = localize
        self.verification_uri = ""
        self.user_code = ""
        self.expires_at = 0.0
        self.finished_successfully = False
        self._cancel_emitted = False

        self.setModal(False)
        self.setWindowTitle(self._text("Connect Bot Account to Twitch" if role == BOT_AUTH_ROLE else "Connect Channel Account to Twitch"))
        self.setMinimumWidth(460)
        self.setLayoutDirection(Qt.LeftToRight)
        self.build_ui()
        self.countdown_timer = QTimer(self)
        self.countdown_timer.timeout.connect(self.refresh_countdown)
        self.countdown_timer.start(1000)
        self.update_state({"state": "preparing", "message": "Preparing authorization"})

    def _text(self, text):
        try:
            return self.localize(text)
        except Exception:
            return str(text)

    def build_ui(self):
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {self.theme.panel_background};
                color: {self.theme.text_primary};
            }}
            QLabel {{
                color: {self.theme.text_primary};
            }}
            QPushButton {{
                background-color: {self.theme.accent_color};
                color: {self.theme.text_inverse};
                border: 1px solid {self.theme.accent_color};
                border-radius: 9px;
                padding: 8px 12px;
                font-weight: 700;
                min-height: 30px;
            }}
            QPushButton:hover {{
                background-color: {self.theme.accent_hover};
            }}
            QPushButton#mutedButton {{
                background-color: {self.theme.elevated_card_background};
                color: {self.theme.text_primary};
                border: 1px solid {self.theme.border_color};
            }}
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        title = QLabel(self._text("Connect Bot Account to Twitch" if self.role == BOT_AUTH_ROLE else "Connect Channel Account to Twitch"))
        title.setStyleSheet("font-size:18px;font-weight:800;")
        layout.addWidget(title)

        description = QLabel(self._text(
            "A Twitch authorization page has been opened in your browser.\n"
            "Enter the code below if Twitch does not fill it automatically, then approve access."
        ))
        description.setWordWrap(True)
        description.setStyleSheet(f"color:{self.theme.text_secondary};font-size:13px;")
        layout.addWidget(description)

        code_card = QFrame()
        code_card.setStyleSheet(
            f"""
            QFrame {{
                background-color: {self.theme.input_bg};
                border: 1px solid {self.theme.border_color};
                border-radius: 12px;
            }}
            """
        )
        code_layout = QVBoxLayout(code_card)
        code_layout.setContentsMargins(18, 16, 18, 16)
        code_layout.setSpacing(7)
        code_title = QLabel(self._text("User Code"))
        code_title.setStyleSheet(f"color:{self.theme.text_secondary};font-size:12px;font-weight:700;")
        self.code_label = QLabel("------")
        self.code_label.setAlignment(Qt.AlignCenter)
        self.code_label.setLayoutDirection(Qt.LeftToRight)
        self.code_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.code_label.setStyleSheet(f"color:{self.theme.text_primary};font-size:34px;font-weight:900;letter-spacing:2px;")
        code_layout.addWidget(code_title)
        code_layout.addWidget(self.code_label)
        layout.addWidget(code_card)

        self.status_label = QLabel(self._text("Preparing authorization"))
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"color:{self.theme.text_primary};font-size:13px;font-weight:700;")
        layout.addWidget(self.status_label)

        self.countdown_label = QLabel("")
        self.countdown_label.setStyleSheet(f"color:{self.theme.text_secondary};font-size:12px;")
        layout.addWidget(self.countdown_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.copy_button = QPushButton(self._text("Copy Code"))
        self.copy_button.clicked.connect(self.copy_code)
        self.open_button = QPushButton(self._text("Open Twitch Again"))
        self.open_button.clicked.connect(self.open_twitch)
        self.cancel_button = QPushButton(self._text("Cancel"))
        self.cancel_button.setObjectName("mutedButton")
        self.cancel_button.clicked.connect(self.cancel_auth)
        button_row.addWidget(self.copy_button)
        button_row.addWidget(self.open_button)
        button_row.addStretch()
        button_row.addWidget(self.cancel_button)
        layout.addLayout(button_row)

        self.copy_button.setEnabled(False)
        self.open_button.setEnabled(False)

    def copy_code(self):
        if self.user_code:
            QGuiApplication.clipboard().setText(self.user_code)
            self.status_label.setText(self._text("Code copied. Waiting for Twitch authorization..."))

    def open_twitch(self):
        if not self.verification_uri:
            return False
        ok = QDesktopServices.openUrl(QUrl(self.verification_uri))
        if not ok:
            self.status_label.setText(self._text("Could not open Twitch. Copy the code and open the authorization page manually."))
        return ok

    def cancel_auth(self):
        if not self.finished_successfully and not self._cancel_emitted:
            self._cancel_emitted = True
            self.cancelled.emit()
        self.reject()

    def refresh_countdown(self):
        if not self.expires_at or self.finished_successfully:
            self.countdown_label.setText("")
            return
        remaining = max(0, int(self.expires_at - time.time()))
        minutes, seconds = divmod(remaining, 60)
        self.countdown_label.setText(self._text(f"Code expires in {minutes:02d}:{seconds:02d}"))
        if remaining <= 0:
            self.status_label.setText(self._text("This authorization code has expired. Generate a new code to continue."))

    def update_state(self, payload):
        state = str((payload or {}).get("state") or "").strip()
        message = str((payload or {}).get("message") or "").strip()
        if payload.get("user_code"):
            self.user_code = str(payload.get("user_code") or "")
            self.code_label.setText(self.user_code)
            self.copy_button.setEnabled(True)
        if payload.get("verification_uri"):
            self.verification_uri = str(payload.get("verification_uri") or "")
            self.open_button.setEnabled(True)
        if payload.get("expires_at"):
            self.expires_at = float(payload.get("expires_at") or 0.0)
            self.refresh_countdown()
        if message:
            self.status_label.setText(self._text(message))
        if state == "waiting" and not getattr(self, "_opened_initial_browser", False):
            self._opened_initial_browser = True
            self.open_twitch()
        if state == "connected":
            self.finished_successfully = True
            self.status_label.setText(self._text(message or "Connected"))
            self.cancel_button.setText(self._text("Close"))
            QTimer.singleShot(1000, self.accept)
        elif state in {"failed", "expired", "denied", "cancelled"}:
            self.cancel_button.setText(self._text("Close"))

    def closeEvent(self, event):
        if not self.finished_successfully and not self._cancel_emitted:
            self._cancel_emitted = True
            self.cancelled.emit()
        super().closeEvent(event)

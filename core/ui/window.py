import os
import subprocess
import sys
import threading
import time
import weakref
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.app_paths import (
    ALERTS_FILE,
    ALERT_ICONS_DIR,
    ALERT_STATUS_FILE,
    CHAT_LOG_FILE,
    DASHBOARD_STATE_FILE,
    LOGS_DIR,
    MUSIC_COMMAND_FILE,
    PROJECT_ROOT,
    SETTINGS_FILE,
    TWITCH_STYLE_ALERT_ICONS_DIR,
    USERS_FILE,
    VIEWER_RELATIONSHIPS_FILE,
    WINDOW_ICON_ICO,
    WINDOW_ICON_JPEG,
    WINDOW_ICON_JPG,
    WINDOW_ICON_PNG,
)
from core.alert_storage import (
    alert_filter_required_scopes,
    format_alert_time_ago,
    get_alert_badge_colors as storage_get_alert_badge_colors,
    get_alert_icon_name as storage_get_alert_icon_name,
    load_alert_items,
    load_alert_status,
    missing_alert_scopes,
    parse_alert_datetime,
    resolve_alert_type,
)
from core.bot_runtime import (
    clear_alert_runtime_state,
    clear_bot_runtime_state,
    get_active_alert_runtime_state,
    get_active_bot_runtime_state,
    terminate_bot_process,
    write_alert_runtime_state,
    write_bot_runtime_state,
)
from core.app_state import (
    DEFAULT_PROMPT,
    DEFAULT_ALERT_FEED_FILTER,
    default_viewer_relationships_state,
    ensure_app_files,
    load_json,
    save_json,
)
from core.auth import (
    BOT_AUTH_ROLE,
    CHANNEL_AUTH_ROLE,
    CLIENT_ID,
    get_role_scopes,
    load_best_token,
    load_token_details,
    refresh_role_token,
    validate_token,
)
from core.twitch_api import (
    get_channel_chat_badges,
    get_global_chat_badges,
    get_user_by_login,
    send_chat_message,
)
from core.update_manager import UpdateCancelled, UpdateError, UpdateManager
from core.support import (
    SUPPORT_EMAIL,
    clear_pending_crash_report,
    create_crash_outlook_draft,
    create_support_outlook_draft,
    crash_mailto_url,
    diagnostic_summary,
    ensure_logs_dir,
    pending_crash_report,
    support_mailto_url,
)
from core.tasks import BackgroundTaskManager
from core.telemetry import sync_installation
from core.runtime_logging import flush_repeated_log_summaries, route_diagnostic_line

from .chat_renderer import ChatRenderer
from .constants import (
    APP_NAME,
    APP_DISPLAY_NAME,
    APP_VERSION,
    DEFAULT_WINDOW_SIZE,
    MUSIC_INPUT_PLACEHOLDER,
    NAVIGATION_ITEMS,
)
from core.version import APP_VERSION_CHANNEL_NAME, APP_VERSION_LABEL
from .localization import (
    ARABIC_FONT_FAMILY,
    ARABIC_FONT_FAMILIES,
    DEFAULT_LANGUAGE,
    contains_arabic,
    format_text,
    is_rtl_language,
    language_display_name,
    normalize_language,
    resolve_text_key,
    translate_text,
)
from .themes import ThemeManager, build_app_stylesheet, build_combo_popup_stylesheet
from core.chat_storage import load_dashboard_state

from .music_mixin import DashboardMusicMixin
from .twitch_mixin import DashboardTwitchMixin
from .viewers_mixin import DashboardViewersMixin
from .widgets import ActionButton, AnalyticsChartWidget, Bridge, Card, SidebarAccountCard, SidebarButton, StatusDot, ThemedCheckBox, ThumbnailWidget, TriggerChipWidget

ALERT_FEED_TYPES = (
    "All",
    "Followers",
    "Subs",
    "Gifted Subs",
    "Raids",
    "Bits",
    "Clips",
    "Hype Train",
    "Polls",
    "Predictions",
    "Reward Requests",
    "Shoutouts",
    "Watch Streaks",
    "Collaboration Requests",
)
SUPPORTED_ALERT_TYPES = {
    "Followers",
    "Subs",
    "Gifted Subs",
    "Raids",
    "Bits",
    "Polls",
    "Predictions",
    "Reward Requests",
    "Shoutouts",
    "Hype Train",
}
EVENTSUB_REQUIRED_ALERT_TYPES = {
    "Bits",
    "Hype Train",
    "Polls",
    "Predictions",
    "Reward Requests",
    "Shoutouts",
}
UNAVAILABLE_ALERT_TYPES = {
    "Clips",
    "Watch Streaks",
    "Collaboration Requests",
}
TRANSLATION_SOURCE_ROLE = Qt.UserRole + 417
MAX_LIVE_LOG_LINES = 200
MAX_PENDING_LOG_LINES = 400
LIVE_LOG_FLUSH_INTERVAL_MS = 750
LIVE_LOG_REPEAT_SUMMARY_EVERY = 25
DEFAULT_LOG_RETENTION_MINUTES = 60
LOG_RETENTION_OPTIONS = (
    ("30 minutes", 30),
    ("1 hour", 60),
    ("6 hours", 360),
    ("24 hours", 1440),
)
PROCESS_STOP_TIMEOUT_SECONDS = 5
PROCESS_CLOSE_TIMEOUT_SECONDS = 2
PROCESS_KILL_TIMEOUT_SECONDS = 1
STARTUP_AUTO_RESTART_DELAY_MS = 3000
BOT_RUNTIME_HEARTBEAT_STALE_SECONDS = 75
BOT_HEALTH_RECONNECT_DELAYS_SECONDS = (5, 15, 30, 60)


class DashboardApp(DashboardViewersMixin, DashboardMusicMixin, DashboardTwitchMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        ensure_app_files(
            SETTINGS_FILE,
            USERS_FILE,
            DASHBOARD_STATE_FILE,
            MUSIC_COMMAND_FILE,
            CHAT_LOG_FILE,
            VIEWER_RELATIONSHIPS_FILE,
            ALERTS_FILE,
        )

        self.setWindowTitle(APP_DISPLAY_NAME)
        self.resize(*DEFAULT_WINDOW_SIZE)

        icon = self.get_app_icon()
        if icon is not None:
            self.setWindowIcon(icon)
            app = QApplication.instance()
            if app is not None:
                app.setWindowIcon(icon)

        self.process = None
        self.alerts_process = None
        self._closing = False
        self.alerts_autostart_attempted = False
        self.restart_in_progress = False
        self.bot_health_reconnect_attempts = 0
        self.bot_health_next_reconnect_at = 0.0
        self.bot_health_last_reason = ""
        self.startup_auto_restart_show_scheduled = False
        self.startup_auto_restart_scheduled = False
        self.startup_auto_restart_ran = False
        self.bridge = Bridge()
        self.bridge.log_signal.connect(self.append_log)
        self.bridge.cover_signal.connect(self._apply_cover_pixmap)
        self.bridge.title_signal.connect(self.set_now_playing_title)
        self.bridge.clear_cover_signal.connect(self.clear_current_track_ui)
        self.bridge.account_signal.connect(self._apply_account_profile)
        self.bridge.chat_assets_ready_signal.connect(self._finish_chat_asset_warmup)
        self.bridge.stream_summary_signal.connect(self._apply_stream_summary)
        self.bridge.viewer_relationships_signal.connect(self._apply_viewer_relationships_payload)
        self.bridge.auth_health_signal.connect(self._apply_auth_health_payload)
        self.bridge.update_status_signal.connect(self.apply_update_status_payload)
        self.bridge.update_check_result_signal.connect(self.handle_update_check_result)
        self.bridge.update_progress_signal.connect(self.handle_update_progress_payload)
        self.bridge.update_download_result_signal.connect(self.handle_update_download_result)
        self.bridge.music_playlist_signal.connect(self.apply_playlist_import_result)
        self.bridge.music_track_request_signal.connect(self.apply_track_request_result)
        self.bridge.twitch_device_auth_signal.connect(self.handle_twitch_device_auth_event)

        self.settings = load_json(SETTINGS_FILE, {})
        self.language = normalize_language(self.settings.get("language", DEFAULT_LANGUAGE))
        self.update_manager = UpdateManager.from_settings(self.settings)
        self.update_config = self.update_manager.config
        self.update_check_inflight = False
        self.update_download_inflight = False
        self.update_install_inflight = False
        self.update_cancel_event = None
        self.pending_update_release = None
        self.pending_update_asset = None
        self.installing_update = False
        self.telemetry_thread = None
        self._localized_bindings = []
        self._localized_binding_keys = set()
        self._language_applying = False
        self.theme_manager = ThemeManager(self.settings.get("theme", "blue"))
        self.theme_name = self.theme_manager.current_name
        self.theme = self.theme_manager.current_theme
        self.dashboard_state = load_dashboard_state()
        self.users_data = load_json(USERS_FILE, {})
        self.viewer_relationships_state = load_json(VIEWER_RELATIONSHIPS_FILE, default_viewer_relationships_state())
        self.file_signature_cache = {}
        self.dashboard_ui_signatures = {}
        self.alert_feed_signature = None
        self.alert_feed_render_signature = None
        self.alert_status_signature = None
        self.music_command_signature = None
        self.music_queue_render_signature = None
        self.viewer_dashboard_signature = None

        self.music_player = None
        self.music_player_initialized = False
        self.music_playback_generation = 0
        self.music_playback_lock = threading.RLock()
        self.music_skip_in_progress = False
        self.music_queue = []
        self.music_queue_titles = {}
        self.current_track_query = ""
        self.current_track_active = False
        self.current_track_title = ""
        self.current_track_started_at = 0.0
        self.music_loading = False
        self.playlist_import_loading = False
        self.last_music_command_timestamp = None
        self.trigger_list = []
        self.auth_widgets = {}
        self.auth_health_state = {
            BOT_AUTH_ROLE: {"state": "disconnected", "message": "No saved token"},
            CHANNEL_AUTH_ROLE: {"state": "disconnected", "message": "No saved token"},
        }
        self.auth_health_request_ids = {
            BOT_AUTH_ROLE: 0,
            CHANNEL_AUTH_ROLE: 0,
        }
        self.auth_health_inflight = {
            BOT_AUTH_ROLE: False,
            CHANNEL_AUTH_ROLE: False,
        }
        self.auth_health_last_check_at = {
            BOT_AUTH_ROLE: 0.0,
            CHANNEL_AUTH_ROLE: 0.0,
        }
        self.account_profile_request_ids = {
            BOT_AUTH_ROLE: 0,
            CHANNEL_AUTH_ROLE: 0,
        }
        self.account_profile_lookup_signatures = {
            BOT_AUTH_ROLE: "",
            CHANNEL_AUTH_ROLE: "",
        }
        self.account_profile_failure_state = {
            BOT_AUTH_ROLE: {"error": "", "next_retry_at": 0.0},
            CHANNEL_AUTH_ROLE: {"error": "", "next_retry_at": 0.0},
        }
        self.twitch_device_auth_request_ids = {BOT_AUTH_ROLE: 0, CHANNEL_AUTH_ROLE: 0}
        self.twitch_device_auth_dialogs = {BOT_AUTH_ROLE: None, CHANNEL_AUTH_ROLE: None}
        self.music_enabled = bool(self.settings.get("music_enabled", True))
        self.audio_volume = max(0, min(100, int(self.settings.get("audio_volume", 100))))
        self.audio_muted = bool(self.settings.get("audio_muted", False))
        self.audio_session_attached = False
        self.prevent_duplicate_tracks = bool(self.settings.get("prevent_duplicate_tracks", True))
        self.auto_restart_bot_on_startup = bool(self.settings.get("auto_restart_bot_on_startup", True))
        self.queue_count_labels = []
        self.prevent_duplicate_checkboxes = []
        self.volume_control_rows = []
        self.volume_slider_widgets = []
        self.volume_value_labels = []
        self.volume_mute_buttons = []
        self.chat_asset_warmup_inflight = False
        self.chat_asset_signature = None
        self.pending_chat_asset_signature = None
        self.viewer_filter_name = "All"
        self.viewer_sort_key = str(self.settings.get("viewer_sort", "messages") or "messages")
        self.relationship_sort_key = str(self.settings.get("relationship_sort", "newest") or "newest")
        self.viewer_filter_buttons = {}
        self.selected_viewer_username = ""
        self.stream_summary_cache = None
        self.stream_summary_request_inflight = False
        self.stream_summary_last_fetch_at = 0.0
        self.viewer_list_category = "Followers"
        self.viewer_list_category_buttons = {}
        self.viewer_relationships_request_inflight = False
        self.viewer_relationships_last_fetch_at = 0.0
        self.viewer_relationships_panel_expanded = True
        self.viewer_relationships_animation = None
        self.session_started_at = datetime.now()
        self.alert_feed_filter = str(self.settings.get("alert_feed_filter", DEFAULT_ALERT_FEED_FILTER) or DEFAULT_ALERT_FEED_FILTER)
        self.alert_feed_items = []
        self.alert_feed_loaded = False
        self.rendered_alert_log_ids = set()
        self.log_retention_minutes = self.resolve_log_retention_minutes(
            self.settings.get("log_retention_minutes", DEFAULT_LOG_RETENTION_MINUTES)
        )
        self.pending_log_lines = []
        self.live_log_entries = []
        self.live_log_repeat_state = {}
        self.log_flush_timer = QTimer(self)
        self.log_flush_timer.setSingleShot(True)
        self.log_flush_timer.timeout.connect(self.flush_pending_log_lines)
        self.task_manager = BackgroundTaskManager(self)

        self.chat_renderer = ChatRenderer(
            client_id=CLIENT_ID,
            load_token=load_best_token,
            get_user_by_login=get_user_by_login,
            get_global_chat_badges=get_global_chat_badges,
            get_channel_chat_badges=get_channel_chat_badges,
        )

        self.build_ui()
        self.load_initial_values()
        self.start_timers()
        QTimer.singleShot(900, self.start_telemetry_sync)

    # =========================
    # Lifecycle helpers
    # =========================
    def create_music_player(self):
        try:
            from core.music_player import MusicPlayer
        except Exception as exc:
            print("MUSIC PLAYER IMPORT ERROR:", exc)
            return None
        try:
            return MusicPlayer(initial_volume=self.audio_volume, initial_muted=self.audio_muted)
        except Exception as exc:
            print("MUSIC PLAYER ERROR:", exc)
            return None

    def ensure_music_player(self):
        if not self.music_player_initialized:
            self.music_player_initialized = True
            self.music_player = self.create_music_player()
            if self.music_player is not None:
                self.apply_master_volume_to_player("player_create", persist=False)
        return self.music_player

    def start_telemetry_sync(self):
        settings_snapshot = {
            "channel_login": self.settings.get("channel_login", ""),
            "bot_login": self.settings.get("bot_login", ""),
        }

        def on_result(result):
            if result is None:
                return
            if getattr(result, "ok", False):
                self.bridge.log_signal.emit(f"[Telemetry] Usage tracking {result.action}.")
            else:
                self.bridge.log_signal.emit("[Telemetry] Usage tracking skipped.")

        def on_error(_error_text):
            self.bridge.log_signal.emit("[Telemetry] Usage tracking skipped.")

        task_manager = getattr(self, "task_manager", None)
        if task_manager is None:
            on_result(sync_installation(settings_snapshot))
            return
        task_manager.start(
            "telemetry_sync",
            lambda cancel_event: None if cancel_event.is_set() else sync_installation(settings_snapshot),
            on_success=on_result,
            on_error=on_error,
        )

    def get_app_icon(self):
        for path in [WINDOW_ICON_ICO, WINDOW_ICON_PNG, WINDOW_ICON_JPG, WINDOW_ICON_JPEG]:
            if path.exists():
                return QIcon(str(path))
        return None

    def get_brand_logo_pixmap(self, size=42):
        for path in [WINDOW_ICON_PNG, WINDOW_ICON_JPG, WINDOW_ICON_JPEG]:
            if not path.exists():
                continue
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                return pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return QPixmap()

    def build_avatar_pixmap(self, source_pixmap=None, fallback_text="B", size=38):
        if source_pixmap is None or source_pixmap.isNull():
            canvas = QPixmap(size, size)
            canvas.fill(Qt.transparent)
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setBrush(QColor(self.theme.avatar_bg))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(0, 0, size, size)
            painter.setPen(QColor("white"))
            font = painter.font()
            font.setBold(True)
            font.setPointSize(12)
            painter.setFont(font)
            painter.drawText(canvas.rect(), Qt.AlignCenter, (fallback_text or "B")[:1].upper())
            painter.end()
            return canvas

        target = QPixmap(size, size)
        target.fill(Qt.transparent)
        painter = QPainter(target)
        painter.setRenderHint(QPainter.Antialiasing, True)
        clip_path = QPainterPath()
        clip_path.addEllipse(0, 0, size, size)
        painter.setClipPath(clip_path)
        scaled = source_pixmap.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x_offset = (size - scaled.width()) // 2
        y_offset = (size - scaled.height()) // 2
        painter.drawPixmap(x_offset, y_offset, scaled)
        painter.end()
        return target

    def closeEvent(self, event):
        self._closing = True
        try:
            for value in list(vars(self).values()):
                if isinstance(value, QTimer):
                    value.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "task_manager"):
                self.task_manager.shutdown()
        except Exception:
            pass
        try:
            player = getattr(self, "music_player", None)
            if player is not None:
                player.stop()
                player.clear_current_track()
        except Exception:
            pass
        try:
            self.shutdown_child_processes()
        except Exception:
            pass
        try:
            flush_repeated_log_summaries()
        except Exception:
            pass
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self.startup_auto_restart_show_scheduled:
            return
        self.startup_auto_restart_show_scheduled = True
        QTimer.singleShot(0, self.schedule_startup_auto_restart)

    def stop_process_with_timeout(
        self,
        process,
        *,
        terminate_timeout=PROCESS_STOP_TIMEOUT_SECONDS,
        kill_timeout=PROCESS_KILL_TIMEOUT_SECONDS,
    ):
        if process is None:
            return True
        try:
            if process.poll() is not None:
                return True
        except Exception:
            return False

        try:
            process.terminate()
        except Exception:
            pass

        try:
            process.wait(timeout=terminate_timeout)
        except subprocess.TimeoutExpired:
            pid = getattr(process, "pid", 0)
            force_stopped = terminate_bot_process(pid) if pid else False
            if not force_stopped:
                try:
                    process.kill()
                except Exception:
                    pass
            try:
                process.wait(timeout=kill_timeout)
            except Exception:
                pass
        except Exception:
            return False

        try:
            return process.poll() is not None
        except Exception:
            return False

    def shutdown_child_processes(self):
        bot_process = getattr(self, "process", None)
        if bot_process is not None:
            bot_pid = getattr(bot_process, "pid", None)
            bot_stopped = self.stop_process_with_timeout(
                bot_process,
                terminate_timeout=PROCESS_CLOSE_TIMEOUT_SECONDS,
                kill_timeout=PROCESS_KILL_TIMEOUT_SECONDS,
            )
            if bot_stopped and bot_pid:
                clear_bot_runtime_state(bot_pid)
                self.process = None

        alerts_process = getattr(self, "alerts_process", None)
        if alerts_process is not None:
            alerts_pid = getattr(alerts_process, "pid", None)
            alerts_stopped = self.stop_process_with_timeout(
                alerts_process,
                terminate_timeout=PROCESS_CLOSE_TIMEOUT_SECONDS,
                kill_timeout=PROCESS_KILL_TIMEOUT_SECONDS,
            )
            if alerts_stopped and alerts_pid:
                clear_alert_runtime_state(alerts_pid)
                self.alerts_process = None

    # =========================
    # Generic helpers
    # =========================
    def resolve_log_retention_minutes(self, value):
        valid_values = {minutes for _, minutes in LOG_RETENTION_OPTIONS}
        try:
            minutes = int(value)
        except (TypeError, ValueError):
            minutes = DEFAULT_LOG_RETENTION_MINUTES
        return minutes if minutes in valid_values else DEFAULT_LOG_RETENTION_MINUTES

    def log_retention_seconds(self):
        return max(60, int(self.log_retention_minutes) * 60)

    def prune_live_log_entries(self, *, now=None):
        now = time.monotonic() if now is None else now
        cutoff = now - self.log_retention_seconds()
        before_count = len(self.live_log_entries)
        self.live_log_entries = [
            (entry_time, entry_text)
            for entry_time, entry_text in self.live_log_entries
            if entry_time >= cutoff
        ]
        if len(self.live_log_entries) > MAX_LIVE_LOG_LINES:
            self.live_log_entries = self.live_log_entries[-MAX_LIVE_LOG_LINES:]
        return len(self.live_log_entries) != before_count

    def append_log(self, text):
        text = str(text or "").strip()
        if not text:
            return
        if route_diagnostic_line(text):
            return
        text = self.prepare_live_log_line(text)
        if not text:
            return
        self.pending_log_lines.append((time.monotonic(), text))
        if len(self.pending_log_lines) > MAX_PENDING_LOG_LINES:
            self.pending_log_lines = self.pending_log_lines[-MAX_PENDING_LOG_LINES:]

        log_widget = getattr(self, "live_log", None)
        if log_widget is None:
            try:
                print(text, flush=True)
            except Exception:
                pass
            return

        timer = getattr(self, "log_flush_timer", None)
        if timer is None:
            self.flush_pending_log_lines()
        elif not timer.isActive():
            timer.start(LIVE_LOG_FLUSH_INTERVAL_MS)

    def prepare_live_log_line(self, text):
        now = time.monotonic()
        repeat_state = getattr(self, "live_log_repeat_state", None)
        if repeat_state is None:
            self.live_log_repeat_state = {}
            repeat_state = self.live_log_repeat_state
        state = repeat_state.get(text)
        if state is None:
            repeat_state[text] = {"last_at": now, "suppressed": 0}
            return text

        state["last_at"] = now
        state["suppressed"] = int(state.get("suppressed") or 0) + 1
        if state["suppressed"] >= LIVE_LOG_REPEAT_SUMMARY_EVERY:
            suppressed = state["suppressed"]
            state["suppressed"] = 0
            return f"Repeated {suppressed} times: {text}"
        return ""

    def flush_pending_log_lines(self):
        log_widget = getattr(self, "live_log", None)
        if log_widget is None:
            return
        had_pending = bool(self.pending_log_lines)
        if self.pending_log_lines:
            self.live_log_entries.extend(self.pending_log_lines)
            self.pending_log_lines = []
        pruned = self.prune_live_log_entries()
        if not had_pending and not pruned:
            return
        scrollbar = log_widget.verticalScrollBar()
        was_near_bottom = scrollbar.value() >= max(0, scrollbar.maximum() - 24)
        log_widget.setPlainText("\n".join(entry_text for _, entry_text in self.live_log_entries))
        if was_near_bottom:
            scrollbar.setValue(scrollbar.maximum())

    def is_bot_process_running(self):
        if self.process is not None and self.process.poll() is None:
            return True
        runtime_state = get_active_bot_runtime_state()
        return bool(runtime_state.get("pid"))

    def current_bot_login(self):
        candidates = [
            getattr(self, "settings_bot_login", None),
            getattr(self, "bot_login_entry", None),
        ]
        for widget in candidates:
            if widget is not None:
                value = widget.text().strip()
                if value:
                    return value
        return self.settings.get("bot_login", "").strip()

    def current_channel_login(self):
        candidates = [
            getattr(self, "settings_channel_login", None),
            getattr(self, "channel_login_entry", None),
        ]
        for widget in candidates:
            if widget is not None:
                value = widget.text().strip()
                if value:
                    return value
        return self.settings.get("channel_login", "").strip()

    def request_auth_health_check(self, force=False):
        now = time.time()
        for role in (BOT_AUTH_ROLE, CHANNEL_AUTH_ROLE):
            details = load_token_details(role)
            token = details.get("access_token")
            if not token:
                self.auth_health_inflight[role] = False
                self.set_role_auth_health(role, "disconnected", "No saved token")
                continue
            if self.auth_health_inflight.get(role):
                continue
            if not force and now - float(self.auth_health_last_check_at.get(role, 0.0) or 0.0) < 45:
                continue

            self.auth_health_request_ids[role] = self.auth_health_request_ids.get(role, 0) + 1
            request_id = self.auth_health_request_ids[role]
            self.auth_health_inflight[role] = True
            self.auth_health_last_check_at[role] = now
            self.set_role_auth_health(role, "connecting", "Checking Twitch session")

            def worker(cancel_event=None, role_name=role, role_token=token, role_request_id=request_id):
                if cancel_event is not None and cancel_event.is_set():
                    return None
                try:
                    try:
                        validation = validate_token(role_token)
                    except Exception as exc:
                        status_code = getattr(getattr(exc, "response", None), "status_code", None)
                        if status_code != 401:
                            raise
                        refreshed = refresh_role_token(role_name)
                        role_token = refreshed.get("access_token") or role_token
                        validation = validate_token(role_token)
                    granted_scopes = validation.get("scopes") or []
                    missing = [scope for scope in get_role_scopes(role_name) if scope not in granted_scopes]
                    if missing:
                        payload = {
                            "role": role_name,
                            "request_id": role_request_id,
                            "state": "failed",
                            "message": f"Missing required permissions: {', '.join(missing)}",
                        }
                    else:
                        login = validation.get("login") or load_token_details(role_name).get("login") or "Twitch"
                        payload = {
                            "role": role_name,
                            "request_id": role_request_id,
                            "state": "connected",
                            "message": f"Authenticated as {login}",
                        }
                except Exception as exc:
                    payload = {
                        "role": role_name,
                        "request_id": role_request_id,
                        "state": "failed",
                        "message": f"Token validation failed: {exc}",
                    }
                return payload

            def on_result(payload):
                if payload is not None:
                    self.bridge.auth_health_signal.emit(payload)

            def on_error(error_text, role_name=role, role_request_id=request_id):
                summary = str(error_text or "Unknown auth error").strip().splitlines()[-1]
                self.bridge.auth_health_signal.emit(
                    {
                        "role": role_name,
                        "request_id": role_request_id,
                        "state": "failed",
                        "message": f"Token validation failed: {summary}",
                    }
                )

            task_manager = getattr(self, "task_manager", None)
            if task_manager is not None:
                started = task_manager.start(
                    f"auth_check_{role}",
                    worker,
                    on_success=on_result,
                    on_error=on_error,
                )
                if not started:
                    self.auth_health_inflight[role] = False
                    if hasattr(self, "refresh_token_status"):
                        self.refresh_token_status()
                continue

            threading.Thread(target=lambda: on_result(worker()), daemon=True).start()

    def _apply_auth_health_payload(self, payload):
        role = payload.get("role")
        if role not in (BOT_AUTH_ROLE, CHANNEL_AUTH_ROLE):
            return
        request_id = payload.get("request_id")
        if request_id is not None and request_id != self.auth_health_request_ids.get(role):
            return
        self.auth_health_inflight[role] = False
        self.set_role_auth_health(role, payload.get("state"), payload.get("message", ""))
        if role == CHANNEL_AUTH_ROLE:
            if payload.get("state") == "connected":
                self.ensure_alerts_listener()
            else:
                self.update_alerts_status_ui()
        self.update_runtime_timer_policy()

    def build_chat_asset_signature(self, entries):
        badge_keys = set()
        emote_ids = set()

        for item in entries:
            for badge in item.get("badges", []):
                if isinstance(badge, dict):
                    badge_keys.add((badge.get("set_id", ""), badge.get("id", "")))
                else:
                    badge_keys.add((str(badge), "1"))

            for fragment in item.get("fragments", []):
                if fragment.get("type") != "emote":
                    continue
                emote_id = (fragment.get("emote") or {}).get("id")
                if emote_id:
                    emote_ids.add(str(emote_id))

        return (
            self.current_channel_login().strip().lower(),
            tuple(sorted(badge_keys)),
            tuple(sorted(emote_ids)),
        )

    def request_chat_asset_warmup(self, entries):
        if not entries:
            return
        if not self.is_bot_process_running():
            return

        signature = self.build_chat_asset_signature(entries)
        if not signature[0]:
            return
        if signature == self.chat_asset_signature or signature == self.pending_chat_asset_signature:
            return
        if self.chat_asset_warmup_inflight:
            return

        self.chat_asset_warmup_inflight = True
        self.pending_chat_asset_signature = signature
        channel_login = self.current_channel_login()
        entries_snapshot = [dict(item) for item in entries]

        def worker():
            try:
                self.chat_renderer.warm_entries(entries_snapshot, channel_login)
            except Exception as exc:
                self.bridge.log_signal.emit(f"Chat asset warmup failed: {exc}")
            finally:
                self.bridge.chat_assets_ready_signal.emit()

        threading.Thread(target=worker, daemon=True).start()

    def _finish_chat_asset_warmup(self):
        self.chat_asset_warmup_inflight = False
        self.chat_asset_signature = self.pending_chat_asset_signature
        self.pending_chat_asset_signature = None
        if hasattr(self, "chat_live"):
            self.refresh_dashboard_chat_preview(force=True)







    def set_label_role(self, label, role):
        label.setProperty("labelRole", role)
        label.style().unpolish(label)
        label.style().polish(label)
        return label

    def polish_widget(self, widget):
        if widget is None:
            return
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def combo_popup_stylesheet(self):
        return build_combo_popup_stylesheet(self.theme)

    def combo_box_stylesheet(self):
        return f"""
        QComboBox {{
            background-color: {self.theme.input_bg};
            color: {self.theme.input_text};
            border: 1px solid {self.theme.border_color};
            border-radius: 10px;
            padding: 8px 34px 8px 10px;
            min-height: 20px;
            font-size: 13px;
            selection-background-color: {self.theme.accent_color};
            selection-color: {self.theme.text_inverse};
        }}
        QComboBox:hover {{
            border-color: {self.theme.accent_border};
        }}
        QComboBox:focus {{
            border-color: {self.theme.accent_color};
            background-color: {self.theme.input_bg};
        }}
        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 30px;
            border-left: 1px solid {self.theme.border_color};
            border-top-right-radius: 10px;
            border-bottom-right-radius: 10px;
            background-color: {self.theme.elevated_card_background};
        }}
        """

    def input_control_stylesheet(self, widget_type="QLineEdit"):
        return f"""
        {widget_type} {{
            background-color: {self.theme.input_bg};
            color: {self.theme.input_text};
            border: 1px solid {self.theme.border_color};
            border-radius: 10px;
            padding: 8px 10px;
            min-height: 20px;
            font-size: 13px;
            selection-background-color: {self.theme.accent_color};
            selection-color: {self.theme.text_inverse};
        }}
        {widget_type}:hover {{
            border-color: {self.theme.accent_border};
        }}
        {widget_type}:focus {{
            border-color: {self.theme.accent_color};
            background-color: {self.theme.input_bg};
        }}
        QLineEdit[readOnlyDisplay="true"] {{
            background-color: {self.theme.elevated_card_background};
            color: {self.theme.text_secondary};
            border: 1px solid {self.theme.border_color};
            border-radius: 10px;
            padding: 8px 10px;
            min-height: 20px;
        }}
        """

    def apply_input_control_style(self, widget):
        if widget is None:
            return
        if isinstance(widget, QPlainTextEdit):
            widget_type = "QPlainTextEdit"
            widget.setMinimumHeight(max(widget.minimumHeight(), 90))
        elif isinstance(widget, QTextEdit):
            widget_type = "QTextEdit"
        else:
            widget_type = "QLineEdit"
            widget.setMinimumHeight(max(widget.minimumHeight(), 38))
        widget.setStyleSheet(self.input_control_stylesheet(widget_type))
        self.polish_widget(widget)

    def apply_combo_popup_style(self, combo):
        if combo is None:
            return
        view = combo.view()
        if not isinstance(view, QListView):
            view = QListView(combo)
            combo.setView(view)
        combo.setMinimumHeight(max(combo.minimumHeight(), 38))
        view.setAutoFillBackground(True)
        view.setUniformItemSizes(True)
        view.setMouseTracking(True)
        view.setStyleSheet(self.combo_popup_stylesheet())
        combo.setStyleSheet(self.combo_box_stylesheet())
        self.polish_widget(combo)
        self.polish_widget(view)

    def save_theme_preference(self):
        self.settings["theme"] = self.theme_name
        save_json(SETTINGS_FILE, self.settings)

    def save_language_preference(self):
        self.settings["language"] = self.language
        save_json(SETTINGS_FILE, self.settings)

    def is_rtl_language(self):
        return is_rtl_language(getattr(self, "language", DEFAULT_LANGUAGE))

    def localize(self, text, **params):
        language = normalize_language(getattr(self, "language", DEFAULT_LANGUAGE))
        if params:
            return format_text(text, language, **params)
        return translate_text(text, language)

    def localization_key(self, key_or_text):
        return resolve_text_key(key_or_text)

    def _localized_value(self, key_or_text, params=None):
        params = dict(params or {})
        if params:
            return format_text(key_or_text, self.language, **params)
        return translate_text(key_or_text, self.language)

    def _is_live_widget(self, widget):
        if widget is None:
            return False
        try:
            widget.objectName()
            return True
        except RuntimeError:
            return False

    def _register_i18n_binding(self, widget, attr, key_or_text, params=None, role=None):
        key = self.localization_key(key_or_text)
        if widget is None or not key:
            return None

        params = dict(params or {})
        role = str(role or "")
        binding_identity = (id(widget), str(attr), role)
        for binding in getattr(self, "_localized_bindings", []):
            if binding.get("identity") == binding_identity:
                binding["key"] = key
                binding["params"] = params
                widget.setProperty(f"i18n_{attr}_key", key)
                widget.setProperty(f"i18n_{attr}_params", params)
                return key

        self._localized_bindings.append(
            {
                "identity": binding_identity,
                "widget": weakref.ref(widget),
                "attr": str(attr),
                "key": key,
                "params": params,
                "role": role,
            }
        )
        widget.setProperty(f"i18n_{attr}_key", key)
        widget.setProperty(f"i18n_{attr}_params", params)
        return key

    def clear_i18n_binding(self, widget, attr="text"):
        if widget is None:
            return
        attr = str(attr)
        self._localized_bindings = [
            binding
            for binding in getattr(self, "_localized_bindings", [])
            if not (
                (binding.get("widget")() if callable(binding.get("widget")) else None) is widget
                and binding.get("attr") == attr
            )
        ]
        widget.setProperty(f"i18n_{attr}_key", "")
        widget.setProperty(f"i18n_{attr}_params", {})
        if attr == "text":
            widget.setProperty("i18n_source_text", "")

    def refresh_localized_widgets(self):
        direction = Qt.RightToLeft if self.is_rtl_language() else Qt.LeftToRight
        active_bindings = []
        for binding in list(getattr(self, "_localized_bindings", [])):
            widget_ref = binding.get("widget")
            widget = widget_ref() if callable(widget_ref) else None
            if not self._is_live_widget(widget):
                continue

            attr = binding.get("attr")
            key = binding.get("key")
            params = binding.get("params") or {}
            value = self._localized_value(key, params)
            try:
                if attr == "text" and hasattr(widget, "setText"):
                    if widget.text() != value:
                        widget.blockSignals(True)
                        widget.setText(value)
                        widget.blockSignals(False)
                    if isinstance(widget, QLabel) and not (widget.alignment() & Qt.AlignHCenter):
                        widget.setAlignment((Qt.AlignRight if self.is_rtl_language() else Qt.AlignLeft) | Qt.AlignVCenter)
                elif attr == "placeholder" and hasattr(widget, "setPlaceholderText"):
                    widget.setPlaceholderText(value)
                    widget.setLayoutDirection(direction)
                    widget.setAlignment(Qt.AlignRight if self.is_rtl_language() else Qt.AlignLeft)
                elif attr == "tooltip" and hasattr(widget, "setToolTip"):
                    widget.setToolTip(value)
                elif attr == "combo_items" and isinstance(widget, QComboBox):
                    self._refresh_localized_combo_items(widget)
                elif attr == "table_headers":
                    self._refresh_localized_table_headers(widget)
            except RuntimeError:
                continue
            active_bindings.append(binding)
        self._localized_bindings = active_bindings

    def _set_i18n_source(self, widget, source_text):
        if widget is not None:
            widget.setProperty("i18n_source_text", str(source_text or ""))
            self._register_i18n_binding(widget, "text", source_text)

    def set_localized_text(self, widget, source_text, **params):
        if widget is None:
            return
        key = self._register_i18n_binding(widget, "text", source_text, params=params)
        if key:
            widget.setProperty("i18n_source_text", str(source_text or ""))
            localized_text = self._localized_value(key, params)
        else:
            self.clear_i18n_binding(widget)
            widget.setProperty("i18n_source_text", "")
            localized_text = "" if source_text is None else str(source_text)
        if not hasattr(widget, "text") or widget.text() != localized_text:
            widget.setText(localized_text)

    def set_localized_placeholder(self, widget, source_text):
        if widget is None:
            return
        key = self._register_i18n_binding(widget, "placeholder", source_text)
        widget.setProperty("i18n_source_placeholder", str(source_text or ""))
        widget.setPlaceholderText(self._localized_value(key) if key else str(source_text or ""))

    def set_dynamic_text(self, widget, text):
        if widget is None:
            return
        self.clear_i18n_binding(widget)
        widget.setText("" if text is None else str(text))

    def set_localized_tooltip(self, widget, source_text):
        if widget is None:
            return
        key = self._register_i18n_binding(widget, "tooltip", source_text)
        widget.setProperty("i18n_source_tooltip", str(source_text or ""))
        widget.setToolTip(self._localized_value(key) if key else str(source_text or ""))

    def _localized_widget_source(self, widget, current_text):
        current_text = str(current_text or "")
        key = widget.property("i18n_text_key")
        if key:
            return str(key)
        source_text = widget.property("i18n_source_text")
        source_text = str(source_text) if source_text not in (None, "") else ""
        if source_text and self.localization_key(source_text):
            return source_text
        return current_text

    def _localize_label_or_button(self, widget):
        if widget is None or not hasattr(widget, "text") or not hasattr(widget, "setText"):
            return
        current_text = widget.text()
        if current_text is None:
            return
        source_text = self._localized_widget_source(widget, current_text)
        next_text = self.localize(source_text)
        if current_text != next_text:
            widget.blockSignals(True)
            widget.setText(next_text)
            widget.blockSignals(False)
        if widget.toolTip():
            source_tip = str(widget.property("i18n_source_tooltip") or widget.toolTip())
            self.set_localized_tooltip(widget, source_tip)

    def _localize_line_edit(self, widget):
        placeholder = widget.placeholderText()
        if placeholder:
            source = str(widget.property("i18n_source_placeholder") or placeholder)
            if source and placeholder == translate_text(source, "ar"):
                pass
            elif not (self.is_rtl_language() and contains_arabic(placeholder)):
                source = placeholder
                widget.setProperty("i18n_source_placeholder", source)
            widget.setPlaceholderText(self.localize(source))
        widget.setLayoutDirection(Qt.RightToLeft if self.is_rtl_language() else Qt.LeftToRight)
        widget.setAlignment(Qt.AlignRight if self.is_rtl_language() else Qt.AlignLeft)

    def _localize_combo_box(self, combo):
        if combo is getattr(self, "language_selector", None):
            self.sync_language_selector()
            return
        combo.blockSignals(True)
        try:
            for index in range(combo.count()):
                current_text = combo.itemText(index)
                source_text = combo.itemData(index, TRANSLATION_SOURCE_ROLE)
                source_text = str(source_text) if source_text not in (None, "") else ""
                if source_text and current_text == translate_text(source_text, "ar"):
                    pass
                elif not source_text or not (self.is_rtl_language() and contains_arabic(current_text)):
                    source_text = current_text
                    combo.setItemData(index, source_text, TRANSLATION_SOURCE_ROLE)
                combo.setItemText(index, self.localize(source_text))
        finally:
            combo.blockSignals(False)
        combo.setLayoutDirection(Qt.RightToLeft if self.is_rtl_language() else Qt.LeftToRight)

    def _localize_table_headers(self, table):
        if isinstance(table, QTableWidget):
            for section in range(table.columnCount()):
                item = table.horizontalHeaderItem(section)
                if item is None:
                    continue
                current_text = item.text()
                source_text = item.data(TRANSLATION_SOURCE_ROLE)
                source_text = str(source_text) if source_text not in (None, "") else ""
                if source_text and current_text == translate_text(source_text, "ar"):
                    pass
                elif not source_text or not (self.is_rtl_language() and contains_arabic(current_text)):
                    source_text = current_text
                    item.setData(TRANSLATION_SOURCE_ROLE, source_text)
                item.setText(self.localize(source_text))
        model = table.model() if hasattr(table, "model") else None
        if hasattr(model, "apply_translator"):
            model.apply_translator(self.localize)
        table.horizontalHeader().setDefaultAlignment(
            (Qt.AlignRight if self.is_rtl_language() else Qt.AlignLeft) | Qt.AlignVCenter
        )

    def _refresh_localized_combo_items(self, combo):
        if combo is getattr(self, "language_selector", None):
            self.sync_language_selector()
            return
        combo.blockSignals(True)
        try:
            for index in range(combo.count()):
                key = combo.itemData(index, TRANSLATION_SOURCE_ROLE)
                if not key:
                    key = self.localization_key(combo.itemText(index))
                    if key:
                        combo.setItemData(index, key, TRANSLATION_SOURCE_ROLE)
                if key:
                    combo.setItemText(index, self.localize(str(key)))
        finally:
            combo.blockSignals(False)
        combo.setLayoutDirection(Qt.RightToLeft if self.is_rtl_language() else Qt.LeftToRight)

    def _refresh_localized_table_headers(self, table):
        if isinstance(table, QTableWidget):
            for section in range(table.columnCount()):
                item = table.horizontalHeaderItem(section)
                if item is None:
                    continue
                key = item.data(TRANSLATION_SOURCE_ROLE)
                if not key:
                    key = self.localization_key(item.text())
                    if key:
                        item.setData(TRANSLATION_SOURCE_ROLE, key)
                if key:
                    item.setText(self.localize(str(key)))
        model = table.model() if hasattr(table, "model") else None
        if hasattr(model, "apply_translator"):
            model.apply_translator(self.localize)
        table.horizontalHeader().setDefaultAlignment(
            (Qt.AlignRight if self.is_rtl_language() else Qt.AlignLeft) | Qt.AlignVCenter
        )

    def register_static_localized_widgets(self):
        if getattr(self, "_static_i18n_registered", False):
            return
        self._static_i18n_registered = True

        def managed_by_localized_parent(widget):
            parent = widget.parent()
            while parent is not None:
                if isinstance(parent, SidebarAccountCard):
                    return True
                parent = parent.parent()
            return False

        for widget in self.findChildren(QLabel) + self.findChildren(QPushButton):
            if managed_by_localized_parent(widget):
                continue
            try:
                text = widget.text()
            except RuntimeError:
                continue
            if text and self.localization_key(text):
                self._set_i18n_source(widget, text)
            tooltip = widget.toolTip() if hasattr(widget, "toolTip") else ""
            if tooltip and self.localization_key(tooltip):
                self.set_localized_tooltip(widget, tooltip)

        for entry in self.findChildren(QLineEdit):
            try:
                placeholder = entry.placeholderText()
            except RuntimeError:
                continue
            if placeholder and self.localization_key(placeholder):
                self.set_localized_placeholder(entry, placeholder)

        for combo in self.findChildren(QComboBox):
            if combo is getattr(self, "language_selector", None):
                continue
            should_bind = False
            for index in range(combo.count()):
                key = combo.itemData(index, TRANSLATION_SOURCE_ROLE) or self.localization_key(combo.itemText(index))
                if key:
                    combo.setItemData(index, key, TRANSLATION_SOURCE_ROLE)
                    should_bind = True
            if should_bind:
                self._register_i18n_binding(combo, "combo_items", "settings.language", role="items")

        for table in self.findChildren(QTableWidget) + self.findChildren(QTableView):
            should_bind = False
            if isinstance(table, QTableWidget):
                for section in range(table.columnCount()):
                    item = table.horizontalHeaderItem(section)
                    if item is None:
                        continue
                    key = item.data(TRANSLATION_SOURCE_ROLE) or self.localization_key(item.text())
                    if key:
                        item.setData(TRANSLATION_SOURCE_ROLE, key)
                        should_bind = True
            model = table.model() if hasattr(table, "model") else None
            if hasattr(model, "apply_translator"):
                should_bind = True
            if should_bind:
                self._register_i18n_binding(table, "table_headers", "settings.language", role="headers")

    def sync_language_selector(self):
        selector = getattr(self, "language_selector", None)
        if selector is None:
            return
        selector.blockSignals(True)
        try:
            options = (
                (language_display_name("en", "en"), "en"),
                (language_display_name("ar", "ar"), "ar"),
            )
            if selector.count() != len(options):
                selector.clear()
                for label, code in options:
                    selector.addItem(label, code)
            else:
                for index, (label, code) in enumerate(options):
                    selector.setItemText(index, label)
                    selector.setItemData(index, code)
            selected_index = selector.findData(self.language)
            if selected_index >= 0:
                selector.setCurrentIndex(selected_index)
        finally:
            selector.blockSignals(False)

    def on_language_selector_changed(self, index):
        if index < 0 or not hasattr(self, "language_selector"):
            return
        language = normalize_language(self.language_selector.itemData(index))
        if language == self.language:
            return
        self.language = language
        self.apply_language(refresh_content=True)
        self.save_language_preference()
        self.append_log(f"Language switched to {language_display_name(language, language)}")

    def retranslate_ui_text(self):
        self.refresh_localized_widgets()

    def retranslate_dynamic_ui_if_needed(self):
        # Dynamic refresh paths update their own localized values. The expensive
        # full widget-tree scan belongs only in apply_language().
        return

    def build_localized_app_stylesheet(self):
        stylesheet = build_app_stylesheet(self.theme)
        if self.is_rtl_language():
            font_family_css = ", ".join(f'"{family}"' for family in ARABIC_FONT_FAMILIES)
            stylesheet += f"""
            QWidget {{
                font-family: {font_family_css};
            }}
            QComboBox {{
                padding-left: 28px;
                padding-right: 10px;
            }}
            """
        return stylesheet

    def apply_language(self, refresh_content=True):
        if getattr(self, "_language_applying", False):
            return
        self._language_applying = True
        try:
            self.language = normalize_language(getattr(self, "language", DEFAULT_LANGUAGE))
            direction = Qt.RightToLeft if self.is_rtl_language() else Qt.LeftToRight
            app = QApplication.instance()
            if app is not None:
                app.setLayoutDirection(direction)
                font = QFont()
                if self.is_rtl_language():
                    available_families = set(QFontDatabase.families())
                    preferred_families = [family for family in ARABIC_FONT_FAMILIES if family in available_families]
                    if hasattr(font, "setFamilies") and preferred_families:
                        font.setFamilies(preferred_families)
                    else:
                        font.setFamily(preferred_families[0] if preferred_families else ARABIC_FONT_FAMILY)
                font.setPointSize(10)
                app.setFont(font)
            self.setStyleSheet(self.build_localized_app_stylesheet())
            self.setLayoutDirection(direction)
            central = self.centralWidget()
            if central is not None:
                central.setLayoutDirection(direction)
            self.sync_media_control_directions()
            self.sync_volume_button_order()
            for widget in self.findChildren(SidebarButton):
                widget.apply_language(self.language)
            for widget in self.findChildren(SidebarAccountCard):
                widget.apply_language(self.language)
            for widget in self.findChildren(ThumbnailWidget):
                widget.apply_language(self.language)
            for widget in self.findChildren(AnalyticsChartWidget):
                widget.apply_language(self.language)
            for widget in self.findChildren(QComboBox):
                self.apply_combo_popup_style(widget)
            self.sync_language_selector()
            if refresh_content:
                self.refresh_token_status()
                self.update_alerts_status_ui()
                self.sync_music_toggle_buttons()
                self.sync_volume_controls()
                self.refresh_queue_list_widgets()
                if hasattr(self, "alert_feed_rows_layout"):
                    self.refresh_alert_feed()
                if hasattr(self, "viewer_table_model"):
                    self.refresh_viewers_dashboard()
                if hasattr(self, "messages_today_value"):
                    self.refresh_dashboard()
            self.retranslate_ui_text()
        finally:
            self._language_applying = False

    def set_status_value_style(self, label, tone):
        colors = self.theme.status_colors(tone)
        label.setStyleSheet(f"color:{colors.title};font-size:18px;font-weight:700;")

    def make_title(self, text):
        label = QLabel(self.localize(text))
        self._set_i18n_source(label, text)
        return self.set_label_role(label, "sectionTitle")

    def make_small_title(self, text):
        label = QLabel(self.localize(text))
        self._set_i18n_source(label, text)
        return self.set_label_role(label, "smallTitle")

    def make_info_value_label(self, text="Not connected"):
        label = QLabel(self.localize(text))
        self._set_i18n_source(label, text)
        label.setWordWrap(True)
        return self.set_label_role(label, "infoValue")

    def file_signature(self, path):
        try:
            stats = Path(path).stat()
            return (int(stats.st_mtime_ns), int(stats.st_size))
        except Exception:
            return None

    def cached_file_changed(self, key, path, *, force=False):
        signature = self.file_signature(path)
        previous = self.file_signature_cache.get(key)
        if force or signature != previous:
            self.file_signature_cache[key] = signature
            return True, signature
        return False, signature

    def refresh_cached_runtime_state(self, *, force=False):
        dashboard_changed, _ = self.cached_file_changed("dashboard_state", DASHBOARD_STATE_FILE, force=force)
        if dashboard_changed:
            self.dashboard_state = load_dashboard_state()

        users_changed, _ = self.cached_file_changed("users", USERS_FILE, force=force)
        if users_changed:
            self.users_data = load_json(USERS_FILE, {})

        return {"dashboard": dashboard_changed, "users": users_changed}

    def save_alert_settings(self):
        self.settings["alert_feed_filter"] = self.alert_feed_filter
        save_json(SETTINGS_FILE, self.settings)

    def load_alert_feed_items(self, force=False):
        changed, signature = self.cached_file_changed("alerts", ALERTS_FILE, force=force)
        if not changed and self.alert_feed_loaded:
            return self.alert_feed_items
        self.alert_feed_items = list(load_alert_items(ALERTS_FILE))
        self.alert_feed_loaded = True
        self.alert_feed_signature = signature
        return self.alert_feed_items

    def alert_subscription_issues(self, alert_filter="All"):
        changed, signature = self.cached_file_changed("alert_status", ALERT_STATUS_FILE)
        if changed or not hasattr(self, "alert_status_cache"):
            self.alert_status_cache = load_alert_status(ALERT_STATUS_FILE)
            self.alert_status_signature = signature
        status = getattr(self, "alert_status_cache", {})
        issues = []
        for event_type, entry in status.get("subscriptions", {}).items():
            if alert_filter != "All" and resolve_alert_type(event_type, "") != alert_filter:
                continue
            entry_status = str(entry.get("status") or "").strip()
            if entry_status not in {"failed", "missing_scope"}:
                continue
            issues.append((event_type, entry))
        return issues

    def alert_subscription_status_text(self):
        issues = self.alert_subscription_issues("All")
        missing_permissions = []
        failures = []
        for event_type, entry in issues:
            for scope in entry.get("missing_scopes", []) or []:
                if scope not in missing_permissions:
                    missing_permissions.append(scope)
            if entry.get("status") == "failed":
                reason = str(entry.get("reason") or "subscription failed").strip()
                failures.append(f"{event_type}: {reason}")
        if missing_permissions:
            return f"Missing alert permissions: {', '.join(missing_permissions)}"
        if failures:
            return f"Alert subscription issue: {'; '.join(failures[:2])}"
        return ""

    def alert_filter_empty_message(self):
        selected_filter = getattr(self, "alert_feed_filter", DEFAULT_ALERT_FEED_FILTER)
        channel_details = load_token_details(CHANNEL_AUTH_ROLE)
        scopes = set(channel_details.get("scopes", []))
        if not channel_details.get("access_token"):
            return "Connect Channel Account to enable Twitch alert EventSub subscriptions"
        required_scopes = alert_filter_required_scopes(selected_filter)
        missing = missing_alert_scopes(scopes, required_scopes)
        if missing:
            return f"Requires Channel Account permission: {', '.join(missing)}"

        issues = self.alert_subscription_issues(selected_filter)
        if issues:
            event_type, entry = issues[0]
            reason = str(entry.get("reason") or "subscription failed").strip()
            if entry.get("missing_scopes"):
                return f"Requires Channel Account permission: {', '.join(entry.get('missing_scopes'))}"
            return f"Failed to subscribe to {event_type}: {reason}"

        if selected_filter == "All":
            if self.alert_feed_items:
                return "No alerts match the current filter"
            return "No stored Twitch alert events captured yet"
        if selected_filter == "Followers":
            return "No recent follower alerts captured yet"
        if selected_filter in {"Subs", "Gifted Subs"}:
            return "No recent subscription alerts captured yet"
        if selected_filter == "Raids":
            return "No recent raid alerts captured yet"
        if selected_filter in UNAVAILABLE_ALERT_TYPES:
            return "Not currently available via Twitch API/EventSub"
        return "No recent alerts captured yet"

    def filtered_alert_feed_items(self):
        selected_filter = getattr(self, "alert_feed_filter", DEFAULT_ALERT_FEED_FILTER)
        if selected_filter == "All":
            items = list(self.alert_feed_items)
        else:
            items = [item for item in self.alert_feed_items if item.get("type") == selected_filter]
        return sorted(
            items,
            key=lambda item: (
                0 if item.get("occurred_at") else 1,
                -(parse_alert_datetime(item.get("occurred_at")).timestamp()) if item.get("occurred_at") and parse_alert_datetime(item.get("occurred_at")) else 0,
                int(item.get("minutes_ago", 10**9)),
            ),
        )[:50]

    def update_alert_summary_label(self):
        if not hasattr(self, "alerts_summary_label"):
            return
        items = self.filtered_alert_feed_items()
        filter_name = getattr(self, "alert_feed_filter", DEFAULT_ALERT_FEED_FILTER)
        if filter_name == "All":
            self.set_localized_text(self.alerts_summary_label, "alerts.latest_count", count=f"{len(items):,}")
        else:
            self.set_localized_text(
                self.alerts_summary_label,
                "alerts.latest_type_count",
                count=f"{len(items):,}",
                alert_type=self.localize(filter_name).lower(),
            )
        self.update_alerts_status_ui()

    def reset_alert_settings(self):
        self.alert_feed_filter = DEFAULT_ALERT_FEED_FILTER
        if hasattr(self, "alert_filter_selector"):
            index = self.alert_filter_selector.findData(DEFAULT_ALERT_FEED_FILTER)
            if index >= 0:
                self.alert_filter_selector.blockSignals(True)
                self.alert_filter_selector.setCurrentIndex(index)
                self.alert_filter_selector.blockSignals(False)
        self.refresh_alert_feed()
        self.save_alert_settings()
        self.append_log("[Alerts] Reset filter to default")

    def on_alert_filter_changed(self, index):
        if not hasattr(self, "alert_filter_selector") or index < 0:
            return
        filter_name = self.alert_filter_selector.itemData(index)
        if not filter_name:
            return
        self.alert_feed_filter = str(filter_name)
        self.refresh_alert_feed()
        self.save_alert_settings()
        self.append_log(f"[Alerts] Filter changed to {self.alert_feed_filter}")

    def clear_layout_widgets(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self.clear_layout_widgets(child_layout)

    def get_alert_icon_name(self, item):
        return storage_get_alert_icon_name(item)

    def get_alert_icon_path(self, item):
        icon_name = self.get_alert_icon_name(item)
        for directory in (TWITCH_STYLE_ALERT_ICONS_DIR, ALERT_ICONS_DIR):
            icon_path = directory / f"{icon_name}.svg"
            if icon_path.exists():
                return icon_path
        for directory in (TWITCH_STYLE_ALERT_ICONS_DIR, ALERT_ICONS_DIR):
            fallback = directory / "bell.svg"
            if fallback.exists():
                return fallback
        return None

    def get_alert_badge_colors(self, item):
        return storage_get_alert_badge_colors(item)

    def build_alert_icon_badge(self, item):
        badge = QLabel()
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(34, 34)
        background, accent, border = self.get_alert_badge_colors(item)
        badge.setStyleSheet(
            f"""
            QLabel {{
                background: {background};
                border: 1px solid {border};
                border-radius: 17px;
                padding: 0;
            }}
            """
        )
        icon_path = self.get_alert_icon_path(item)
        if icon_path is not None:
            pixmap = QIcon(str(icon_path)).pixmap(QSize(18, 18))
            if not pixmap.isNull():
                badge.setPixmap(pixmap)
                return badge
        fallback_pixmap = QIcon.fromTheme("notifications").pixmap(QSize(18, 18))
        if not fallback_pixmap.isNull():
            badge.setPixmap(fallback_pixmap)
        return badge

    def localize_time_ago(self, value):
        text = str(value or "").strip()
        normalized = text.lower()
        if not text:
            return ""
        if normalized == "unknown time":
            return self.localize("time.unknown")
        if normalized == "just now":
            return self.localize("time.just_now")
        if normalized == "yesterday":
            return self.localize("time.yesterday")
        parts = normalized.split()
        if len(parts) >= 3 and parts[-1] == "ago":
            try:
                count = int(parts[0])
            except ValueError:
                return text
            unit = parts[1].rstrip("s")
            if unit == "minute":
                return self.localize("time.minutes_ago", count=count)
            if unit == "hour":
                return self.localize("time.hours_ago", count=count)
            if unit == "day":
                return self.localize("time.days_ago", count=count)
        return text

    def alert_render_log_key(self, item):
        event_type = str(item.get("event_type") or item.get("type") or "unknown").strip() or "unknown"
        return str(item.get("id") or f"{event_type}:{item.get('username','')}:{item.get('occurred_at','')}:{item.get('text','')}").strip()

    def log_rendered_alert_events(self, items, *, source="cached"):
        if source == "cached" and getattr(self, "cached_alert_render_summary_logged", False):
            return
        new_items = []
        for item in list(items or []):
            log_key = self.alert_render_log_key(item)
            if not log_key or log_key in self.rendered_alert_log_ids:
                continue
            self.rendered_alert_log_ids.add(log_key)
            new_items.append(item)
        if not new_items:
            return
        counts = {}
        for item in new_items:
            event_type = str(item.get("event_type") or item.get("type") or "unknown").strip() or "unknown"
            counts[event_type] = counts.get(event_type, 0) + 1
        summary = ", ".join(f"{count} {event_type}" for event_type, count in sorted(counts.items()))
        self.append_log(f"[Alerts] Rendered {len(new_items)} {source} events: {summary}")
        if source == "cached":
            self.cached_alert_render_summary_logged = True

    def build_alert_feed_row(self, item):
        row = QFrame()
        row.setProperty("surfaceRole", "subtle")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(14, 12, 14, 12)
        row_layout.setSpacing(12)
        time_ago = format_alert_time_ago(item.get("occurred_at")) if item.get("occurred_at") else str(item.get("time_ago", "Unknown time"))
        localized_time_ago = self.localize_time_ago(time_ago)

        row_layout.addWidget(self.build_alert_icon_badge(item), 0, Qt.AlignTop)

        content_layout = QVBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        username_label = QLabel(item.get("username", "unknown"))
        self.set_label_role(username_label, "sectionTitle")
        username_label.setStyleSheet(f"color:{self.theme.text_primary};font-size:13px;font-weight:700;")
        title_row.addWidget(username_label, 0)

        event_label = QLabel()
        self.set_localized_text(event_label, item.get("text", "Triggered an alert"))
        self.set_label_role(event_label, "mutedBody")
        event_label.setStyleSheet(f"color:{self.theme.text_secondary};font-size:13px;font-weight:600;")
        title_row.addWidget(event_label, 1)
        content_layout.addLayout(title_row)

        meta_label = QLabel()
        self.set_localized_text(
            meta_label,
            "alerts.meta",
            alert_type=self.localize(item.get("type", "Alert")),
            time_ago=localized_time_ago,
        )
        self.set_label_role(meta_label, "mutedBody")
        meta_label.setStyleSheet(f"color:{self.theme.text_muted};font-size:12px;")
        content_layout.addWidget(meta_label)

        row_layout.addLayout(content_layout, 1)

        menu_button = ActionButton("⋯", "ghost", self.theme)
        menu_button.setCursor(Qt.PointingHandCursor)
        menu_button.setFixedSize(32, 32)
        menu_button.setProperty("i18n_source_tooltip", "More actions")
        menu_button.setToolTip(self.localize("More actions"))
        row_layout.addWidget(menu_button, 0, Qt.AlignTop)

        return row

    def refresh_alert_feed(self):
        if not hasattr(self, "alert_feed_rows_layout"):
            return
        self.load_alert_feed_items()
        items = self.filtered_alert_feed_items()
        render_signature = (
            getattr(self, "alert_feed_signature", None),
            getattr(self, "alert_status_signature", None),
            getattr(self, "alert_feed_filter", DEFAULT_ALERT_FEED_FILTER),
            tuple(
                str(item.get("id") or self.alert_render_log_key(item))
                for item in items
            ),
        )
        if render_signature == getattr(self, "alert_feed_render_signature", None):
            return
        self.alert_feed_render_signature = render_signature
        self.clear_layout_widgets(self.alert_feed_rows_layout)
        if not items:
            empty_label = QLabel()
            self.set_localized_text(empty_label, self.alert_filter_empty_message())
            empty_label.setAlignment(Qt.AlignCenter)
            self.set_label_role(empty_label, "mutedBody")
            empty_label.setMinimumHeight(120)
            self.alert_feed_rows_layout.addWidget(empty_label)
        else:
            for item in items:
                self.alert_feed_rows_layout.addWidget(self.build_alert_feed_row(item))
            self.log_rendered_alert_events(items, source="cached")
        self.alert_feed_rows_layout.addStretch()
        self.update_alert_summary_label()

    def build_alerts_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        body = QWidget()
        outer = QVBoxLayout(body)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)
        title_block = QVBoxLayout()
        title_block.setSpacing(4)
        title_block.addWidget(self.make_title("Alerts"))
        hero_subtitle = QLabel("A Twitch-style activity feed for follows, raids, subscriptions, bits, and other recent channel events.")
        hero_subtitle.setWordWrap(True)
        self.set_label_role(hero_subtitle, "cardSubtitle")
        title_block.addWidget(hero_subtitle)
        header_row.addLayout(title_block, 1)

        filter_block = QVBoxLayout()
        filter_block.setSpacing(6)
        filter_label = QLabel("Filter")
        self.set_label_role(filter_label, "smallTitle")
        filter_block.addWidget(filter_label)
        self.alert_filter_selector = QComboBox()
        for alert_type in ALERT_FEED_TYPES:
            self.alert_filter_selector.addItem(alert_type, alert_type)
        self.alert_filter_selector.currentIndexChanged.connect(self.on_alert_filter_changed)
        self.alert_filter_selector.setMinimumWidth(190)
        filter_block.addWidget(self.alert_filter_selector)
        header_row.addLayout(filter_block, 0)
        outer.addLayout(header_row)

        feed_card = Card()
        feed_layout = QVBoxLayout(feed_card)
        feed_layout.setContentsMargins(18, 18, 18, 18)
        feed_layout.setSpacing(12)
        feed_top_row = QHBoxLayout()
        feed_top_row.setSpacing(10)
        self.alerts_summary_label = self.set_label_role(QLabel(""), "heroMeta")
        feed_top_row.addWidget(self.alerts_summary_label)
        feed_top_row.addStretch()
        reset_button = self.make_button("Reset Default", "muted", self.reset_alert_settings)
        reset_button.setMaximumWidth(140)
        feed_top_row.addWidget(reset_button)
        feed_layout.addLayout(feed_top_row)

        self.alerts_status_label = QLabel("")
        self.alerts_status_label.setWordWrap(True)
        self.alerts_status_label.setVisible(False)
        self.set_label_role(self.alerts_status_label, "mutedBody")
        feed_layout.addWidget(self.alerts_status_label)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet(f"color:{self.theme.card_border};background:{self.theme.card_border};min-height:1px;max-height:1px;")
        feed_layout.addWidget(divider)

        rows_container = QWidget()
        self.alert_feed_rows_layout = QVBoxLayout(rows_container)
        self.alert_feed_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.alert_feed_rows_layout.setSpacing(10)
        feed_layout.addWidget(rows_container)
        outer.addWidget(feed_card)
        outer.addStretch()

        layout.addWidget(self.make_scroll_container(body))
        return page
































    def on_theme_selector_changed(self, index):
        if index < 0 or not hasattr(self, "theme_selector"):
            return
        theme_name = self.theme_selector.itemData(index)
        if not theme_name or theme_name == self.theme_name:
            return
        self.theme_manager.set_theme(theme_name)
        self.theme_name = self.theme_manager.current_name
        self.theme = self.theme_manager.current_theme
        self.apply_theme()
        self.save_theme_preference()
        self.append_log(f"Theme switched to {self.theme.display_name}")

    def sync_log_retention_selector(self):
        selector = getattr(self, "log_retention_selector", None)
        if selector is None:
            return
        selector.blockSignals(True)
        try:
            selected_index = selector.findData(self.log_retention_minutes)
            if selected_index >= 0:
                selector.setCurrentIndex(selected_index)
        finally:
            selector.blockSignals(False)

    def on_log_retention_selector_changed(self, index):
        if index < 0 or not hasattr(self, "log_retention_selector"):
            return
        minutes = self.resolve_log_retention_minutes(self.log_retention_selector.itemData(index))
        if minutes == self.log_retention_minutes:
            return
        self.log_retention_minutes = minutes
        self.settings["log_retention_minutes"] = minutes
        save_json(SETTINGS_FILE, self.settings)
        self.flush_pending_log_lines()
        self.append_log(f"Log retention set to {self.log_retention_selector.itemText(index)}")

    def apply_badge_style(self, label, tone="neutral"):
        colors = self.theme.status_colors(tone)
        label.setStyleSheet(
            f"""
            QLabel {{
                background: {colors.background};
                color: {colors.text};
                border: 1px solid {colors.border};
                border-radius: 13px;
                padding: 5px 10px;
                font-size: 12px;
                font-weight: 700;
            }}
            """
        )

    def make_badge_label(self, text="", tone="neutral"):
        label = QLabel(self.localize(text))
        self._set_i18n_source(label, text)
        label.setAlignment(Qt.AlignCenter)
        self.apply_badge_style(label, tone)
        return label

    def make_dashboard_table(self, headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels([self.localize(header) for header in headers])
        for section, header in enumerate(headers):
            header_item = table.horizontalHeaderItem(section)
            if header_item is not None:
                header_item.setData(TRANSLATION_SOURCE_ROLE, str(header))
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(False)
        table.setShowGrid(False)
        table.setFocusPolicy(Qt.NoFocus)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        if len(headers) > 1:
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setDefaultAlignment(
            (Qt.AlignRight if self.is_rtl_language() else Qt.AlignLeft) | Qt.AlignVCenter
        )
        table.horizontalHeader().setMinimumSectionSize(80)
        self.apply_dashboard_table_style(table)
        return table

    def apply_dashboard_table_style(self, table):
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
            }}
            QTableView::item, QTableWidget::item {{
                border-bottom: 1px solid {self.theme.card_border};
                padding: 12px 6px;
            }}
            """
        )

    def populate_dashboard_table(self, table, rows, *, empty_left="No data yet", empty_right="--"):
        items = list(rows or [])
        is_empty_state = not items
        if not items:
            items = [(empty_left, empty_right)]

        table.setRowCount(len(items))
        left_alignment = Qt.AlignRight if self.is_rtl_language() else Qt.AlignLeft
        right_alignment = Qt.AlignLeft if self.is_rtl_language() else Qt.AlignRight
        for row_index, (left_text, right_text) in enumerate(items):
            left_item = QTableWidgetItem(self.localize(left_text) if is_empty_state else str(left_text))
            right_item = QTableWidgetItem(self.localize(right_text) if is_empty_state else str(right_text))
            left_item.setFlags(Qt.ItemIsEnabled)
            right_item.setFlags(Qt.ItemIsEnabled)
            left_item.setTextAlignment(left_alignment | Qt.AlignVCenter)
            right_item.setTextAlignment(right_alignment | Qt.AlignVCenter)
            table.setItem(row_index, 0, left_item)
            table.setItem(row_index, 1, right_item)

        row_height = 42
        for row_index in range(table.rowCount()):
            table.setRowHeight(row_index, row_height)

        visible_rows = min(max(table.rowCount(), 1), 5)
        header_height = table.horizontalHeader().height() or 30
        table.setMinimumHeight(header_height + (visible_rows * row_height) + 12)

    def update_dashboard_status_badge(self):
        if not hasattr(self, "dashboard_status_badge"):
            return

        connection_state = self.get_auth_connection_state()
        bot_connected = connection_state["bot_connected"]
        channel_connected = connection_state["channel_connected"]

        if self.process is not None and self.process.poll() is None:
            if bot_connected and channel_connected:
                text = "Bot online • full system enabled"
            elif bot_connected:
                text = "Bot online • limited channel access"
            else:
                text = "Bot online"
            tone = "success"
        elif bot_connected and channel_connected:
            text = "Both accounts connected"
            tone = "success"
        elif bot_connected:
            text = "Bot account connected • limited mode"
            tone = "info"
        elif channel_connected:
            text = "Channel account connected • bot missing"
            tone = "warning"
        else:
            text = "Twitch setup needed"
            tone = "warning"

        self.set_localized_text(self.dashboard_status_badge, text)
        self.apply_badge_style(self.dashboard_status_badge, tone)

    def make_button(self, text, role, callback):
        button = ActionButton(self.localize(text), role, self.theme)
        self._set_i18n_source(button, text)
        button.clicked.connect(callback)
        return button

    def make_labeled_entry(self, parent_layout, label_text):
        parent_layout.addWidget(self.make_small_title(label_text))
        entry = QLineEdit()
        self.apply_input_control_style(entry)
        parent_layout.addWidget(entry)
        return entry

    def make_scroll_container(self, body):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setAttribute(Qt.WA_StyledBackground, True)
        scroll.viewport().setAutoFillBackground(False)
        body.setAttribute(Qt.WA_StyledBackground, True)
        body.setStyleSheet("background: transparent; border: none;")
        scroll.setWidget(body)
        return scroll














    def build_bot_settings_card(self):
        settings_card = Card()
        settings_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        settings_layout = QVBoxLayout(settings_card)
        settings_layout.setContentsMargins(16, 16, 16, 16)
        settings_layout.setSpacing(12)
        settings_layout.addWidget(self.make_title("Bot Settings"))

        subtitle = QLabel("Core bot status, Twitch readiness, and quick runtime controls.")
        subtitle.setWordWrap(True)
        self.set_label_role(subtitle, "muted")
        settings_layout.addWidget(subtitle)

        status_row = QHBoxLayout()
        status_row.setSpacing(14)

        status_left = QVBoxLayout()
        status_left.addWidget(self.make_small_title("Bot Status"))
        self.bot_status_value = QLabel("OFFLINE")
        self.set_label_role(self.bot_status_value, "statusValue")
        status_left.addWidget(self.bot_status_value)

        status_middle = QVBoxLayout()
        status_middle.setSpacing(2)
        status_middle.addWidget(self.make_small_title("Alerts Status"))
        self.alerts_status_value = QLabel("Alerts: Disconnected")
        self.set_label_role(self.alerts_status_value, "statusValue")
        status_middle.addWidget(self.alerts_status_value)
        self.alerts_status_caption = QLabel("Connect Channel Account to enable live alerts")
        self.alerts_status_caption.setWordWrap(True)
        self.set_label_role(self.alerts_status_caption, "mutedBody")
        status_middle.addWidget(self.alerts_status_caption)

        status_right = QVBoxLayout()
        status_right.setSpacing(2)
        status_right.addWidget(self.make_small_title("Twitch Roles"))
        self.twitch_status_value = QLabel("NOT CONNECTED")
        self.set_label_role(self.twitch_status_value, "statusValue")
        status_right.addWidget(self.twitch_status_value)
        self.twitch_status_caption = QLabel("Connect both Twitch roles in Twitch Setup")
        self.twitch_status_caption.setWordWrap(True)
        self.set_label_role(self.twitch_status_caption, "mutedBody")
        status_right.addWidget(self.twitch_status_caption)

        status_row.addLayout(status_left)
        status_row.addStretch()
        status_row.addLayout(status_middle)
        status_row.addStretch()
        status_row.addLayout(status_right)
        settings_layout.addLayout(status_row)

        actions_grid = QGridLayout()
        actions_grid.setHorizontalSpacing(8)
        actions_grid.setVerticalSpacing(8)
        actions_grid.addWidget(self.make_button("Open Twitch Setup", "twitch", lambda: self.switch_page("Twitch")), 0, 0)
        actions_grid.addWidget(self.make_button("Start Bot", "success", self.start_bot), 0, 1)
        actions_grid.addWidget(self.make_button("Stop Bot", "danger", self.stop_bot), 1, 0)
        actions_grid.addWidget(self.make_button("Restart Bot", "warning", self.restart_bot), 1, 1)
        settings_layout.addLayout(actions_grid)

        form_row = QHBoxLayout()
        form_row.setSpacing(12)

        bot_login_col = QVBoxLayout()
        self.bot_login_entry = self.make_labeled_entry(bot_login_col, "Bot Login")
        form_row.addLayout(bot_login_col, 1)

        channel_login_col = QVBoxLayout()
        self.channel_login_entry = self.make_labeled_entry(channel_login_col, "Channel Login")
        form_row.addLayout(channel_login_col, 1)

        settings_layout.addLayout(form_row)

        settings_layout.addWidget(self.make_small_title("Trigger Words"))
        self.triggers_preview_value = QLabel("No triggers")
        self.set_label_role(self.triggers_preview_value, "mutedBody")
        self.triggers_preview_value.setWordWrap(True)
        settings_layout.addWidget(self.triggers_preview_value)
        return settings_card






    def build_theme_settings_card(self):
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        layout.addWidget(self.make_title("Appearance"))

        description = QLabel("Choose a full app theme. The new look applies instantly across the sidebar, cards, charts, inputs, and buttons.")
        description.setWordWrap(True)
        self.set_label_role(description, "mutedBody")
        layout.addWidget(description)

        layout.addWidget(self.make_small_title("Theme"))
        self.theme_selector = QComboBox()
        for theme_name, display_name in self.theme_manager.list_choices():
            self.theme_selector.addItem(display_name, theme_name)
        self.apply_combo_popup_style(self.theme_selector)
        self.theme_selector.currentIndexChanged.connect(self.on_theme_selector_changed)
        layout.addWidget(self.theme_selector)

        layout.addWidget(self.make_small_title("Language"))
        self.language_selector = QComboBox()
        self.language_selector.addItem(language_display_name("en", "en"), "en")
        self.language_selector.addItem("العربية", "ar")
        self.apply_combo_popup_style(self.language_selector)
        self.language_selector.currentIndexChanged.connect(self.on_language_selector_changed)
        layout.addWidget(self.language_selector)

        layout.addWidget(self.make_small_title("Log Retention"))
        self.log_retention_selector = QComboBox()
        for label, minutes in LOG_RETENTION_OPTIONS:
            self.log_retention_selector.addItem(self.localize(label), minutes)
            self.log_retention_selector.setItemData(
                self.log_retention_selector.count() - 1,
                self.localization_key(label),
                TRANSLATION_SOURCE_ROLE,
            )
        self.apply_combo_popup_style(self.log_retention_selector)
        self.log_retention_selector.currentIndexChanged.connect(self.on_log_retention_selector_changed)
        layout.addWidget(self.log_retention_selector)
        return card

    def build_ai_settings_card(self):
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        layout.addWidget(self.make_title("AI Settings"))

        layout.addWidget(self.make_small_title("OpenAI API Key"))
        key_row = QHBoxLayout()
        self.openai_key_entry = QLineEdit()
        self.openai_key_entry.setEchoMode(QLineEdit.Password)
        key_row.addWidget(self.openai_key_entry)
        self.btn_key_paste = self.make_button("Paste", "primary", self.paste_openai_key)
        self.btn_key_show = self.make_button("Show", "muted", self.toggle_key_visibility)
        key_row.addWidget(self.btn_key_paste)
        key_row.addWidget(self.btn_key_show)
        layout.addLayout(key_row)

        layout.addWidget(self.make_small_title("System Prompt"))
        self.prompt_box = QPlainTextEdit()
        self.prompt_box.setMinimumHeight(220)
        layout.addWidget(self.prompt_box)

        prompt_row = QHBoxLayout()
        prompt_row.addWidget(self.make_button("Paste Prompt", "primary", self.paste_prompt))
        prompt_row.addWidget(self.make_button("Reset Prompt", "muted", self.reset_prompt))
        layout.addLayout(prompt_row)
        return card

    def build_runtime_controls_card(self):
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        layout.addWidget(self.make_title("Bot Controls"))

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addWidget(self.make_button("Save Settings", "primary", self.save_all_settings))
        button_row.addWidget(self.make_button("Start Bot", "success", self.start_bot))
        button_row.addWidget(self.make_button("Stop Bot", "danger", self.stop_bot))
        button_row.addWidget(self.make_button("Restart Bot", "warning", self.restart_bot))
        layout.addLayout(button_row)

        self.auto_restart_startup_checkbox = ThemedCheckBox(self.localize("Auto Restart Bot on Startup"), self.theme)
        self._set_i18n_source(self.auto_restart_startup_checkbox, "Auto Restart Bot on Startup")
        self.auto_restart_startup_checkbox.setChecked(bool(self.auto_restart_bot_on_startup))
        self.auto_restart_startup_checkbox.toggled.connect(self.on_auto_restart_startup_toggled)
        layout.addWidget(self.auto_restart_startup_checkbox)

        layout.addWidget(self.make_small_title("Send Manual Message as Bot"))
        self.manual_message_entry = QLineEdit()
        self.manual_message_entry.setPlaceholderText("Type a message to send directly to chat")
        layout.addWidget(self.manual_message_entry)
        layout.addWidget(self.make_button("Send to Chat", "primary", self.send_manual_chat))
        return card

    def build_update_settings_card(self):
        self.update_manager = UpdateManager.from_settings(self.settings)
        self.update_config = self.update_manager.config

        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        layout.addWidget(self.make_title("Updates"))

        status_row = QHBoxLayout()
        status_row.setSpacing(10)

        version_col = QVBoxLayout()
        version_col.setSpacing(4)
        version_col.addWidget(self.make_small_title("Current Version"))
        self.update_current_version_value = QLabel()
        self.set_label_role(self.update_current_version_value, "valueLarge")
        self.set_localized_text(self.update_current_version_value, "updates.current_version_value", version=APP_VERSION_LABEL)
        version_col.addWidget(self.update_current_version_value)
        status_row.addLayout(version_col, 1)

        provider_col = QVBoxLayout()
        provider_col.setSpacing(4)
        provider_col.addWidget(self.make_small_title("Release Channel"))
        self.update_channel_value = QLabel(APP_VERSION_CHANNEL_NAME)
        self.set_label_role(self.update_channel_value, "mutedBody")
        provider_col.addWidget(self.update_channel_value)
        status_row.addLayout(provider_col, 1)
        layout.addLayout(status_row)

        self.update_status_value = QLabel()
        self.update_status_value.setWordWrap(True)
        self.set_label_role(self.update_status_value, "mutedBody")
        self.set_localized_text(self.update_status_value, "Ready to check for updates.")
        layout.addWidget(self.update_status_value)

        self.update_progress_bar = QProgressBar()
        self.update_progress_bar.setRange(0, 100)
        self.update_progress_bar.setValue(0)
        self.update_progress_bar.setVisible(False)
        layout.addWidget(self.update_progress_bar)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)
        self.check_updates_button = self.make_button("Check for Updates", "primary", self.check_for_updates)
        actions_row.addWidget(self.check_updates_button)

        self.cancel_update_button = self.make_button("Cancel Download", "danger", self.cancel_update_download)
        self.cancel_update_button.setEnabled(False)
        actions_row.addWidget(self.cancel_update_button)

        self.auto_update_checkbox = ThemedCheckBox(self.localize("Auto Update"), self.theme)
        self._set_i18n_source(self.auto_update_checkbox, "Auto Update")
        self.auto_update_checkbox.setChecked(bool(self.update_config.auto_update_enabled))
        self.auto_update_checkbox.setEnabled(True)
        self.auto_update_checkbox.toggled.connect(self.on_auto_update_toggled)
        self.auto_update_checkbox.setToolTip(self.localize("Automatically check for updates on startup."))
        self.set_localized_tooltip(
            self.auto_update_checkbox,
            "Automatically check for updates on startup.",
        )
        actions_row.addWidget(self.auto_update_checkbox)
        actions_row.addStretch()
        layout.addLayout(actions_row)

        config_note = QLabel()
        config_note.setWordWrap(True)
        self.set_label_role(config_note, "mutedBody")
        self.set_localized_text(config_note, "updates.config_summary", provider=self.update_config.update_provider, channel=self.update_config.release_channel)
        layout.addWidget(config_note)
        return card

    def build_technical_support_card(self):
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        layout.addWidget(self.make_title("Technical Support"))

        email_label = QLabel(f"Support Email: {SUPPORT_EMAIL}")
        email_label.setWordWrap(True)
        self.set_label_role(email_label, "mutedBody")
        layout.addWidget(email_label)

        description = QLabel("Support tools open your mail app or local logs folder. No emails are sent automatically.")
        description.setWordWrap(True)
        self.set_label_role(description, "mutedBody")
        layout.addWidget(description)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addWidget(self.make_button("Send Support Email", "primary", self.open_support_email))
        button_row.addWidget(self.make_button("Open Logs Folder", "muted", self.open_logs_folder))
        button_row.addWidget(self.make_button("Copy Diagnostic Info", "muted", self.copy_diagnostic_info))
        discord_button = self.make_button("Discord Support", "muted", lambda: None)
        discord_button.setEnabled(False)
        discord_button.setToolTip(self.localize("Coming Soon"))
        self.set_localized_tooltip(discord_button, "Coming Soon")
        button_row.addWidget(discord_button)
        button_row.addStretch()
        layout.addLayout(button_row)
        return card

    def on_auto_update_toggled(self, checked):
        self.update_config = UpdateManager.from_settings(self.settings).config
        update_settings = dict(self.settings.get("updates") if isinstance(self.settings.get("updates"), dict) else {})
        update_settings.update(self.update_config.to_dict())
        update_settings["auto_update_enabled"] = bool(checked)
        self.settings["updates"] = update_settings
        self.update_manager = UpdateManager.from_settings(self.settings)
        self.update_config = self.update_manager.config
        save_json(SETTINGS_FILE, self.settings)
        state_text = "enabled" if checked else "disabled"
        self.set_update_status(f"Auto Update {state_text}.")
        self.append_log(f"[Updates] Auto Update {state_text}")

    def open_mailto_url(self, url):
        if not QDesktopServices.openUrl(QUrl(url)):
            self.append_log("[Support] Failed to open default mail app")
            QMessageBox.warning(self, self.localize("Technical Support"), "Could not open the default mail app.")
            return False
        return True

    def current_support_log_attachment(self):
        report = pending_crash_report()
        if report and report.get("path"):
            crash_path = Path(report.get("path"))
            if crash_path.exists() and crash_path.is_file():
                return str(crash_path)
        return ""

    def show_manual_attachment_fallback(self):
        self.open_logs_folder()
        QMessageBox.information(
            self,
            self.localize("Technical Support"),
            "Your mail app does not support automatic attachments. Please attach the crash log manually.",
        )

    def open_support_email(self):
        attachment_path = self.current_support_log_attachment()
        if create_support_outlook_draft(attachment_path=attachment_path or None):
            if attachment_path:
                self.append_log("[Support] Support email draft opened with redacted log attachment")
            else:
                self.append_log("[Support] Support email draft opened")
            return

        if self.open_mailto_url(support_mailto_url(attachment_path or None)):
            self.append_log("[Support] Support email draft opened")
            if attachment_path:
                self.show_manual_attachment_fallback()

    def open_crash_report_email(self, crash_path):
        if create_crash_outlook_draft(crash_path):
            self.append_log("[Support] Crash report email draft opened with redacted log attachment")
            return True

        if self.open_mailto_url(crash_mailto_url(crash_path)):
            self.append_log("[Support] Crash report email draft opened")
            self.show_manual_attachment_fallback()
            return True
        return False

    def open_logs_folder(self):
        logs_dir = ensure_logs_dir()
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_dir))):
            self.append_log("[Support] Failed to open logs folder")
            QMessageBox.warning(self, self.localize("Technical Support"), f"Could not open logs folder:\n{logs_dir}")
            return
        self.append_log("[Support] Logs folder opened")

    def copy_diagnostic_info(self):
        QApplication.clipboard().setText(diagnostic_summary())
        self.append_log("[Support] Diagnostic info copied")

    def show_pending_crash_dialog(self):
        if getattr(self, "_closing", False):
            return
        report = pending_crash_report()
        if not report:
            return
        crash_path = report.get("path", "")
        dialog = QMessageBox(self)
        dialog.setWindowTitle(self.localize("Technical Support"))
        dialog.setIcon(QMessageBox.Warning)
        dialog.setText(
            "1SalemBOT detected a crash from the previous session.\n\n"
            "You can open a support email draft, open the logs folder, or dismiss this notice."
        )
        send_button = dialog.addButton(self.localize("Send Crash Report"), QMessageBox.AcceptRole)
        logs_button = dialog.addButton(self.localize("Open Logs Folder"), QMessageBox.ActionRole)
        dismiss_button = dialog.addButton(self.localize("Dismiss"), QMessageBox.RejectRole)
        dialog.exec()
        try:
            clicked = dialog.clickedButton()
        except RuntimeError:
            return
        if clicked is send_button:
            self.open_crash_report_email(crash_path)
        elif clicked is logs_button:
            self.open_logs_folder()
        elif clicked is dismiss_button:
            clear_pending_crash_report()
            self.append_log("[Support] Crash report dismissed")

    def sync_auto_restart_startup_checkbox(self):
        checkbox = getattr(self, "auto_restart_startup_checkbox", None)
        if checkbox is None:
            return
        checkbox.blockSignals(True)
        checkbox.setChecked(bool(self.auto_restart_bot_on_startup))
        checkbox.blockSignals(False)

    def on_auto_restart_startup_toggled(self, checked):
        self.auto_restart_bot_on_startup = bool(checked)
        self.settings["auto_restart_bot_on_startup"] = bool(checked)
        save_json(SETTINGS_FILE, self.settings)
        state_text = "enabled" if checked else "disabled"
        self.append_log(f"[BOOT] Auto Restart Bot on Startup {state_text}")

    def set_update_status(self, text, progress=None):
        if hasattr(self, "update_status_value"):
            self.set_dynamic_text(self.update_status_value, text)
        if progress is not None and hasattr(self, "update_progress_bar"):
            self.update_progress_bar.setVisible(True)
            self.update_progress_bar.setValue(max(0, min(100, int(progress))))
    def friendly_update_error(self, error):
        text = str(error or "").strip()
        lowered = text.lower()
        if "no internet" in lowered or "urlopen error" in lowered or "failed to reach" in lowered:
            return "No internet connection or GitHub update source unavailable. Please try again later."
        if "invalid update json" in lowered or "invalid json" in lowered:
            return "Invalid update information was received. Please try again later."
        if "checksum" in lowered:
            return "Checksum mismatch. The downloaded installer could not be verified."
        if "failed to start installer" in lowered or "downloaded installer was not found" in lowered:
            return "Installer failed to start. Please download the installer manually from GitHub Releases."
        return text or "Update failed. Please try again later."

    def sync_update_controls(self):
        checking = bool(getattr(self, "update_check_inflight", False))
        downloading = bool(getattr(self, "update_download_inflight", False))
        installing = bool(getattr(self, "update_install_inflight", False) or getattr(self, "installing_update", False))
        updates_enabled = bool(getattr(self, "update_config", None) and self.update_config.enabled)
        if hasattr(self, "check_updates_button"):
            self.check_updates_button.setEnabled(updates_enabled and not checking and not downloading and not installing)
            self.check_updates_button.setToolTip("" if updates_enabled else self.localize("Update checks are disabled"))
        if hasattr(self, "cancel_update_button"):
            self.cancel_update_button.setEnabled(downloading and not installing)
        if hasattr(self, "auto_update_checkbox"):
            self.auto_update_checkbox.setEnabled(updates_enabled and not downloading and not installing)

    def check_for_updates(self, auto=False):
        if self.update_check_inflight or self.update_download_inflight:
            self.set_update_status("Update check already running.")
            return
        self.update_manager = UpdateManager.from_settings(self.settings)
        self.update_config = self.update_manager.config
        if not self.update_config.enabled:
            self.update_check_inflight = False
            self.sync_update_controls()
            self.set_update_status("Update checks are disabled")
            if not auto:
                self.append_log("[Updates] Update checks are disabled")
            return
        self.update_check_inflight = True
        self.sync_update_controls()
        self.set_update_status("Checking for updates...", 0)
        self.append_log("[Updates] Checking GitHub for updates")

        def worker(cancel_event):
            if cancel_event.is_set():
                return None
            try:
                result = self.update_manager.check_for_updates()
                result["auto"] = bool(auto)
                return result
            except Exception as exc:
                return {"error": str(exc), "auto": bool(auto)}

        def on_result(result):
            if result is not None:
                self.bridge.update_check_result_signal.emit(result)

        task_manager = getattr(self, "task_manager", None)
        if task_manager is None:
            threading.Thread(
                target=lambda: on_result(worker(threading.Event())),
                daemon=True,
            ).start()
            return
        started = task_manager.start(
            "update_check",
            worker,
            on_success=on_result,
            on_error=lambda error_text: self.bridge.update_check_result_signal.emit({"error": error_text, "auto": bool(auto)}),
        )
        if not started:
            self.update_check_inflight = False
            self.sync_update_controls()
            self.set_update_status("Update check already running.")

    def apply_update_status_payload(self, payload):
        if isinstance(payload, dict):
            self.set_update_status(payload.get("text") or "", payload.get("progress"))
        else:
            self.set_update_status(str(payload or ""))

    def handle_update_check_result(self, payload):
        self.update_check_inflight = False
        self.sync_update_controls()
        if not isinstance(payload, dict):
            payload = {"error": "Invalid update result."}
        if payload.get("error"):
            friendly_error = self.friendly_update_error(payload.get("error"))
            self.set_update_status(f"Update check failed: {friendly_error}")
            self.append_log(f"[Updates] Check failed: {friendly_error}")
            if not payload.get("auto"):
                QMessageBox.warning(self, self.localize("Updates"), friendly_error)
            return

        release = payload.get("release")
        installer_asset = payload.get("installer_asset")
        if not payload.get("applicable"):
            self.set_update_status("No applicable update found for this release channel.")
            self.append_log("[Updates] No applicable update found")
            return
        if not payload.get("is_newer"):
            version = getattr(release, "version", APP_VERSION)
            self.set_update_status(f"Already up to date. Current version: {APP_VERSION_LABEL}. Latest version: {version}.")
            self.append_log(f"[Updates] Already up to date ({APP_VERSION_LABEL})")
            return
        if installer_asset is None:
            self.set_update_status("Update available, but no Windows installer asset was provided.")
            self.append_log("[Updates] Update available but installer asset is missing")
            QMessageBox.warning(self, self.localize("Updates"), "Update available, but no Windows installer asset was provided.")
            return

        self.pending_update_release = release
        self.pending_update_asset = installer_asset
        self.set_update_status(f"Update found: v{getattr(release, 'version', '')}", 100)
        self.append_log(f"[Updates] Update found: v{getattr(release, 'version', '')}")
        self.show_update_available_dialog(release, installer_asset, auto=bool(payload.get("auto")))

    def show_update_available_dialog(self, release, installer_asset, auto=False):
        version = getattr(release, "version", "")
        notes = "\n".join(getattr(release, "notes_lines", [])[:8])
        message = f"Version {version} is available.\n\nCurrent version: {APP_VERSION_LABEL}"
        if notes:
            message += f"\n\nRelease notes:\n{notes}"
        message += "\n\nDownload and run the installer now?"

        dialog = QMessageBox(self)
        dialog.setWindowTitle(self.localize("Update Available"))
        dialog.setIcon(QMessageBox.Information)
        dialog.setText(message)
        update_button = dialog.addButton(self.localize("Update Now"), QMessageBox.AcceptRole)
        dialog.addButton(self.localize("Cancel"), QMessageBox.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is update_button:
            silent = bool(getattr(self, "auto_update_checkbox", None) and self.auto_update_checkbox.isChecked())
            self.start_update_download(release, installer_asset, silent=silent)
        else:
            self.set_update_status("Update cancelled by user.")
            self.append_log("[Updates] Update cancelled by user")

    def start_update_download(self, release, installer_asset, silent=False):
        if self.update_download_inflight:
            return
        self.update_download_inflight = True
        self.update_install_inflight = False
        self.update_cancel_event = threading.Event()
        self.sync_update_controls()
        self.set_update_status("Downloading update... 0%", 0)
        self.append_log(f"[Updates] Downloading installer for version {getattr(release, 'version', '')}")

        def progress(downloaded, total):
            percent = 0
            if total:
                percent = int((downloaded / total) * 100)
            self.bridge.update_progress_signal.emit(
                {
                    "downloaded": downloaded,
                    "total": total,
                    "progress": percent,
                    "text": f"Downloading update... {percent}%" if total else f"Downloading update... {downloaded // 1024} KB",
                }
            )

        def worker():
            try:
                path = self.update_manager.download_installer(
                    installer_asset,
                    progress_callback=progress,
                    cancel_event=self.update_cancel_event,
                    status_callback=lambda text, progress_value=None: self.bridge.update_status_signal.emit(
                        {"text": text, "progress": progress_value}
                    ),
                )
                self.bridge.update_download_result_signal.emit(
                    {
                        "path": path,
                        "release": release,
                        "asset": installer_asset,
                        "silent": bool(silent),
                    }
                )
            except UpdateCancelled as exc:
                self.bridge.update_download_result_signal.emit({"cancelled": True, "error": str(exc)})
            except Exception as exc:
                self.bridge.update_download_result_signal.emit({"error": str(exc)})

        threading.Thread(target=worker, daemon=True).start()

    def handle_update_progress_payload(self, payload):
        if not isinstance(payload, dict):
            return
        self.set_update_status(payload.get("text") or "Downloading update...", payload.get("progress"))

    def cancel_update_download(self):
        if self.update_cancel_event is not None:
            self.update_cancel_event.set()
            self.set_update_status("Cancelling update download.")
            self.append_log("[Updates] Download cancellation requested")

    def handle_update_download_result(self, payload):
        self.update_download_inflight = False
        self.sync_update_controls()
        if not isinstance(payload, dict):
            payload = {"error": "Invalid download result."}
        if payload.get("cancelled"):
            if hasattr(self, "update_progress_bar"):
                self.update_progress_bar.setVisible(False)
                self.update_progress_bar.setValue(0)
            self.set_update_status("Update download cancelled.")
            self.append_log("[Updates] Download cancelled")
            return
        if payload.get("error"):
            if hasattr(self, "update_progress_bar"):
                self.update_progress_bar.setVisible(False)
                self.update_progress_bar.setValue(0)
            friendly_error = self.friendly_update_error(payload.get("error"))
            self.set_update_status(f"Update download failed: {friendly_error}")
            self.append_log(f"[Updates] Download failed: {friendly_error}")
            QMessageBox.warning(self, self.localize("Updates"), friendly_error)
            return
        self.set_update_status("Preparing installer...", 100)
        self.install_downloaded_update(payload)

    def install_downloaded_update(self, payload):
        installer_path = payload.get("path")
        asset = payload.get("asset")
        silent = bool(payload.get("silent"))
        self.update_install_inflight = True
        self.sync_update_controls()
        self.set_update_status("Installing update...", 100)
        try:
            args = self.update_manager.launch_installer_after_exit(
                installer_path,
                os.getpid(),
                silent=silent,
                asset=asset,
            )
        except Exception as exc:
            self.update_install_inflight = False
            self.sync_update_controls()
            friendly_error = self.friendly_update_error(f"Failed to start installer: {exc}")
            self.set_update_status(f"Failed to start installer: {friendly_error}")
            self.append_log(f"[Updates] Failed to start installer: {friendly_error}")
            QMessageBox.warning(self, self.localize("Updates"), friendly_error)
            return
        mode = "silent" if args else "interactive"
        self.installing_update = True
        self.set_update_status("Closing app to apply update...", 100)
        self.append_log(f"[Updates] Installer queued in {mode} mode. Closing app.")
        QTimer.singleShot(500, self.close)

    def sync_scroll_html(self, widget: QTextEdit, new_html: str):
        if widget.property("lastHtmlSignature") == hash(new_html):
            return
        widget.setProperty("lastHtmlSignature", hash(new_html))
        scrollbar = widget.verticalScrollBar()
        old_value = scrollbar.value()
        old_max = scrollbar.maximum()
        was_near_bottom = (old_max - old_value) < 30

        widget.blockSignals(True)
        widget.setHtml(new_html)
        widget.blockSignals(False)

        if was_near_bottom:
            scrollbar.setValue(scrollbar.maximum())
        else:
            scrollbar.setValue(min(old_value, scrollbar.maximum()))

    # =========================
    # Trigger chips
    # =========================
    def add_trigger_from_input(self):
        text = self.trigger_input.text().strip()
        if not text:
            return
        if text not in self.trigger_list:
            self.trigger_list.append(text)
            self.render_trigger_chips()
        self.trigger_input.clear()

    def remove_trigger(self, trigger_text):
        self.trigger_list = [item for item in self.trigger_list if item != trigger_text]
        self.render_trigger_chips()

    def render_trigger_chips(self):
        while self.trigger_chips_layout.count():
            item = self.trigger_chips_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for trigger in self.trigger_list:
            chip = TriggerChipWidget(trigger)
            chip.apply_theme(self.theme)
            chip.removed.connect(self.remove_trigger)
            self.trigger_chips_layout.addWidget(chip)

        self.trigger_chips_layout.addStretch()

    # =========================
    # Clipboard helpers
    # =========================
    def paste_music(self):
        self.paste_from_clipboard(self.music_entry.setText, "Pasted into music box")

    def paste_music_to_page(self):
        self.paste_from_clipboard(self.music_page_input.setText, "Pasted into music page")

    def paste_openai_key(self):
        self.paste_from_clipboard(self.openai_key_entry.setText, "Pasted OpenAI key")

    def paste_prompt(self):
        self.paste_from_clipboard(self.prompt_box.insertPlainText, "Pasted into prompt")


    def toggle_key_visibility(self):
        if self.openai_key_entry.echoMode() == QLineEdit.Password:
            self.openai_key_entry.setEchoMode(QLineEdit.Normal)
            self.set_localized_text(self.btn_key_show, "Hide")
        else:
            self.openai_key_entry.setEchoMode(QLineEdit.Password)
            self.set_localized_text(self.btn_key_show, "Show")

    def reset_prompt(self):
        self.prompt_box.setPlainText(DEFAULT_PROMPT)
        self.append_log("Prompt reset")

    def save_all_settings(self):
        self.settings = {
            **self.settings,
            "bot_login": self.settings_bot_login.text().strip() or self.bot_login_entry.text().strip(),
            "channel_login": self.settings_channel_login.text().strip() or self.channel_login_entry.text().strip(),
            "triggers": ",".join(self.trigger_list),
            "viewer_sort": getattr(self, "viewer_sort_key", "messages"),
            "relationship_sort": getattr(self, "relationship_sort_key", "newest"),
            "music_enabled": bool(self.music_enabled),
            "prevent_duplicate_tracks": bool(self.prevent_duplicate_tracks),
            "auto_restart_bot_on_startup": bool(self.auto_restart_bot_on_startup),
            "audio_volume": int(self.audio_volume),
            "audio_muted": bool(self.audio_muted),
            "openai_api_key": self.openai_key_entry.text().strip(),
            "system_prompt": self.prompt_box.toPlainText().strip(),
            "theme": self.theme_name,
            "language": self.language,
            "log_retention_minutes": int(self.log_retention_minutes),
            "updates": self.update_config.to_dict(),
        }
        self.update_manager = UpdateManager.from_settings(self.settings)
        self.update_config = self.update_manager.config
        save_json(SETTINGS_FILE, self.settings)

        self.bot_login_entry.setText(self.settings["bot_login"])
        self.channel_login_entry.setText(self.settings["channel_login"])
        if self.trigger_list:
            self.clear_i18n_binding(self.triggers_preview_value)
            self.triggers_preview_value.setText(", ".join(self.trigger_list))
        else:
            self.set_localized_text(self.triggers_preview_value, "No triggers")
        self.chat_renderer.badge_catalog_cache = {}
        self.chat_renderer.last_badge_catalog_refresh_at = 0.0
        self.append_log("Settings saved")
        self.refresh_account_widget()




    # =========================
    # Account widget
    # =========================




    # =========================
    # Bot process
    # =========================
    def set_status(self, running: bool):
        self.set_localized_text(self.bot_status_value, "ONLINE" if running else "OFFLINE")
        self.set_status_value_style(self.bot_status_value, "success" if running else "danger")
        self.update_dashboard_status_badge()





    def get_backend_python(self):
        candidates = [
            PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
            PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return sys.executable

    def get_backend_command(self):
        if getattr(sys, "frozen", False):
            return [str(sys.executable), "--run-bot"]
        return [str(self.get_backend_python()), str(PROJECT_ROOT / "main.py"), "--run-bot"]

    def get_alerts_command(self):
        if getattr(sys, "frozen", False):
            return [str(sys.executable), "--run-alerts"]
        return [str(self.get_backend_python()), str(PROJECT_ROOT / "main.py"), "--run-alerts"]

    def read_output(self):
        process = self.process
        if not process:
            return
        try:
            for line in process.stdout:
                if line:
                    self.bridge.log_signal.emit(line.strip())
        except Exception as exc:
            self.bridge.log_signal.emit(f"[ERROR] Failed to read bot output: {exc}")

    def read_alerts_output(self, process):
        if not process:
            return
        try:
            for line in process.stdout:
                if line:
                    self.bridge.log_signal.emit(line.strip())
        except Exception as exc:
            self.bridge.log_signal.emit(f"[ERROR] Failed to read alerts output: {exc}")

    def current_alerts_state(self):
        channel_token = load_token_details(CHANNEL_AUTH_ROLE).get("access_token")
        if not channel_token:
            return "disconnected", "Alerts: Disconnected", "Channel Account not connected", "danger"

        changed, signature = self.cached_file_changed("alert_status", ALERT_STATUS_FILE)
        if changed or not hasattr(self, "alert_status_cache"):
            self.alert_status_cache = load_alert_status(ALERT_STATUS_FILE)
            self.alert_status_signature = signature
        status = getattr(self, "alert_status_cache", {})
        listener = status.get("listener", {})
        listener_state = str(listener.get("state") or "").strip()
        message = str(listener.get("message") or "").strip()
        issues = self.alert_subscription_issues("All")
        has_missing_permissions = any(entry.get("status") == "missing_scope" for _, entry in issues)
        runtime_state = get_active_alert_runtime_state()
        running = bool((self.alerts_process is not None and self.alerts_process.poll() is None) or runtime_state.get("pid"))

        if has_missing_permissions or listener_state == "missing_permissions":
            return "missing_permissions", "Alerts: Missing permissions", message or "Some Twitch alert permissions are missing", "warning"
        if running and listener_state == "connected":
            return "connected", "Alerts: Connected", message or "Listening for Twitch alert events", "success"
        if running or listener_state in {"connecting", "reconnecting"}:
            return "connecting", "Alerts: Connecting", message or "Connecting to Twitch alert events", "info"
        return "disconnected", "Alerts: Disconnected", message or "Alerts listener is not running", "danger"

    def update_alerts_status_ui(self):
        _, text, message, tone = self.current_alerts_state()
        if hasattr(self, "alerts_status_value"):
            self.set_localized_text(self.alerts_status_value, text)
            self.set_status_value_style(self.alerts_status_value, tone)
        if hasattr(self, "alerts_status_caption"):
            self.set_localized_text(self.alerts_status_caption, message)
        if hasattr(self, "alerts_status_label"):
            status_text = self.alert_subscription_status_text() or f"{text}. {message}"
            self.set_localized_text(self.alerts_status_label, status_text)
            self.alerts_status_label.setVisible(bool(status_text))

    def ensure_alerts_listener(self, force=False):
        channel_token_details = load_token_details(CHANNEL_AUTH_ROLE)
        if not channel_token_details.get("access_token"):
            self.update_alerts_status_ui()
            return
        if force:
            self.alerts_autostart_attempted = False

        if self.alerts_process is not None and self.alerts_process.poll() is None:
            if force:
                self.stop_alerts_listener()
            else:
                self.update_alerts_status_ui()
                return

        runtime_state = get_active_alert_runtime_state()
        if runtime_state.get("pid") and not force:
            self.external_alert_runtime_active = True
            self.update_alerts_status_ui()
            self.update_runtime_timer_policy()
            return

        if self.alerts_autostart_attempted and not force:
            self.update_alerts_status_ui()
            return

        if runtime_state.get("pid") and force:
            terminate_bot_process(runtime_state.get("pid"))
            clear_alert_runtime_state(runtime_state.get("pid"))

        try:
            self.alerts_autostart_attempted = True
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "utf-8"
            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            command = self.get_alerts_command()
            self.alerts_process = subprocess.Popen(
                command,
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=creation_flags,
            )
            write_alert_runtime_state(self.alerts_process.pid, " ".join(command))
            self.external_alert_runtime_active = False
            self.append_log(f"[ALERTS] Alerts listener started (PID {self.alerts_process.pid})")
            threading.Thread(target=self.read_alerts_output, args=(self.alerts_process,), daemon=True).start()
        except Exception as exc:
            self.alerts_process = None
            self.external_alert_runtime_active = False
            clear_alert_runtime_state()
            self.append_log(f"[ERROR] Failed to start alerts listener: {exc}")
        self.update_alerts_status_ui()
        self.update_runtime_timer_policy()

    def stop_alerts_listener(self):
        running_process = self.alerts_process if self.alerts_process is not None and self.alerts_process.poll() is None else None
        runtime_state = get_active_alert_runtime_state()
        if running_process is None and not runtime_state.get("pid"):
            clear_alert_runtime_state()
            self.update_alerts_status_ui()
            return
        try:
            if running_process is not None:
                if self.stop_process_with_timeout(running_process):
                    clear_alert_runtime_state(running_process.pid)
                    self.append_log("[ALERTS] Alerts listener stopped")
                else:
                    self.append_log("[ERROR] Failed to stop alerts listener")
            else:
                pid = runtime_state.get("pid")
                if terminate_bot_process(pid):
                    self.append_log(f"[ALERTS] Stopped existing alerts listener (PID {pid})")
                else:
                    self.append_log(f"[ERROR] Failed to stop existing alerts listener (PID {pid})")
                clear_alert_runtime_state(pid)
        finally:
            self.alerts_process = None
            self.external_alert_runtime_active = False
            self.update_alerts_status_ui()
            self.update_runtime_timer_policy()

    def poll_alerts_process(self):
        if self.alerts_process is not None:
            return_code = self.alerts_process.poll()
            if return_code is None:
                self.update_alerts_status_ui()
                return
            clear_alert_runtime_state(self.alerts_process.pid)
            self.append_log(f"[ALERTS] Alerts listener exited with code {return_code}")
            self.alerts_process = None
            self.external_alert_runtime_active = False
            self.update_alerts_status_ui()
            self.update_runtime_timer_policy()
            return

        channel_health = getattr(self, "auth_health_state", {}).get(CHANNEL_AUTH_ROLE, {})
        if load_token_details(CHANNEL_AUTH_ROLE).get("access_token") and channel_health.get("state") == "connected":
            runtime_state = get_active_alert_runtime_state()
            if runtime_state.get("pid"):
                self.external_alert_runtime_active = True
                self.update_alerts_status_ui()
            else:
                self.ensure_alerts_listener()
        else:
            self.update_alerts_status_ui()
            self.update_runtime_timer_policy()

    def start_bot(self):
        self.append_log("[BOT] Start requested")
        bot_token_details = load_token_details(BOT_AUTH_ROLE)
        bot_token = bot_token_details.get("access_token")
        if not bot_token:
            self.append_log("[ERROR] Bot token not found. Connect Bot Account first.")
            return False

        channel_token_details = load_token_details(CHANNEL_AUTH_ROLE)
        channel_token = channel_token_details.get("access_token")

        bot_login = self.settings_bot_login.text().strip() or self.bot_login_entry.text().strip()
        channel_login = self.settings_channel_login.text().strip() or self.channel_login_entry.text().strip()
        if not bot_login or not channel_login:
            self.append_log("[ERROR] Set both Bot Login and Channel Login before starting the bot")
            return False

        self.save_all_settings()
        openai_key = load_json(SETTINGS_FILE, {}).get("openai_api_key", "").strip()
        if not openai_key:
            self.append_log("[ERROR] OpenAI API key is missing")
            return False

        if self.process is not None and self.process.poll() is None:
            self.append_log(f"[BOT] Bot already running (PID {self.process.pid})")
            return False

        runtime_state = get_active_bot_runtime_state()
        if runtime_state.get("pid"):
            self.append_log(
                f"[BOT] Another bot process is already running (PID {runtime_state.get('pid')}). Stop it before starting a new one."
            )
            return False

        try:
            self.append_log("[TWITCH] Connecting to Twitch...")
            env = dict(os.environ)
            env["OPENAI_API_KEY"] = openai_key
            env["PYTHONIOENCODING"] = "utf-8"

            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self.process = subprocess.Popen(
                self.get_backend_command(),
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=creation_flags,
            )
            write_bot_runtime_state(self.process.pid, " ".join(self.get_backend_command()))
            self.external_bot_runtime_active = False
            self.set_status(True)
            self.append_log(f"[BOT] Bot started (PID {self.process.pid})")
            self.append_log(
                f"[TWITCH] Bot account authenticated as {bot_token_details.get('login') or bot_login}"
            )
            if channel_token:
                self.append_log(
                    f"[TWITCH] Channel account authenticated as {channel_token_details.get('login') or channel_login}. Full broadcaster features enabled."
                )
            else:
                self.append_log(
                    "[TWITCH] Channel account not connected. Starting in limited mode."
            )
            threading.Thread(target=self.read_output, daemon=True).start()
            self.update_runtime_timer_policy()
            return True
        except Exception as exc:
            self.append_log(f"[ERROR] Failed to start bot: {exc}")
            self.process = None
            clear_bot_runtime_state()
            self.set_status(False)
            self.update_runtime_timer_policy()
            return False

    def stop_bot(self):
        running_process = self.process if self.process is not None and self.process.poll() is None else None
        runtime_state = get_active_bot_runtime_state()

        if running_process is None and not runtime_state.get("pid"):
            self.append_log("[BOT] Bot is not running")
            return

        try:
            if running_process is not None:
                if self.stop_process_with_timeout(running_process):
                    clear_bot_runtime_state(running_process.pid)
                    self.append_log("[BOT] Bot stopped")
                else:
                    self.append_log("[ERROR] Failed to stop bot")
            else:
                pid = runtime_state.get("pid")
                if terminate_bot_process(pid):
                    clear_bot_runtime_state(pid)
                    self.append_log(f"[BOT] Stopped existing bot process (PID {pid})")
                else:
                    self.append_log(f"[ERROR] Failed to stop existing bot process (PID {pid})")
        except Exception as exc:
            self.append_log(f"[ERROR] Failed to stop bot: {exc}")
        finally:
            self.process = None
            self.external_bot_runtime_active = False
            self.set_status(False)
            self.update_runtime_timer_policy()

    def restart_bot(self):
        self.request_bot_restart(source="manual")

    def startup_auto_restart_skip_reason(self):
        if getattr(self, "_closing", False):
            return "app closing"
        if not bool(getattr(self, "auto_restart_bot_on_startup", True)):
            return "disabled"
        if self.restart_in_progress:
            return "another restart is already running"

        bot_token_details = load_token_details(BOT_AUTH_ROLE)
        if not bot_token_details.get("access_token"):
            return "Bot Account not connected"

        bot_login = self.current_bot_login()
        channel_login = self.current_channel_login()
        if not bot_login or not channel_login:
            return "Bot Login or Channel Login missing"

        openai_key = ""
        openai_entry = getattr(self, "openai_key_entry", None)
        if openai_entry is not None:
            openai_key = openai_entry.text().strip()
        if not openai_key:
            openai_key = str((self.settings or {}).get("openai_api_key") or "").strip()
        if not openai_key:
            return "OpenAI API key missing"

        return ""

    def request_bot_restart(self, source="manual"):
        if self.restart_in_progress:
            if source == "startup":
                self.append_log("[BOOT] Startup auto restart skipped: another restart is already running.")
            elif source == "health":
                return False
            else:
                self.append_log("[BOT] Manual restart ignored because another restart is already running.")
            return False

        self.restart_in_progress = True
        if source == "startup":
            self.append_log("[BOOT] Startup auto restart starting bot.")
        elif source == "health":
            self.append_log("[BOT] Bot connection stale, reconnecting")
        else:
            self.append_log("[BOT] Manual restart requested.")

        self.stop_bot()
        self.schedule_restart_start(source)
        return True

    def schedule_restart_start(self, source):
        QTimer.singleShot(700, lambda: self.complete_bot_restart(source))

    def complete_bot_restart(self, source):
        started = False
        try:
            started = bool(self.start_bot())
        finally:
            self.restart_in_progress = False
            if source == "startup":
                if started:
                    self.append_log("[BOOT] Startup auto restart completed.")
                else:
                    self.append_log("[BOOT] Startup auto restart failed: bot did not start.")
            elif source == "health":
                if started:
                    self.bot_health_reconnect_attempts = 0
                    self.bot_health_next_reconnect_at = 0.0
                    self.append_log("[BOT] Bot reconnected")
                else:
                    attempts = int(getattr(self, "bot_health_reconnect_attempts", 0) or 0) + 1
                    self.bot_health_reconnect_attempts = attempts
                    delays = BOT_HEALTH_RECONNECT_DELAYS_SECONDS
                    delay = delays[min(attempts - 1, len(delays) - 1)]
                    self.bot_health_next_reconnect_at = time.monotonic() + delay
                    self.append_log("[BOT] Bot reconnect failed: bot did not start")
            else:
                self.append_log("[BOT] Manual restart completed.")

    def schedule_startup_auto_restart(self):
        if not bool(getattr(self, "auto_restart_bot_on_startup", True)):
            self.append_log("[BOOT] Startup auto restart skipped: disabled.")
            return
        if self.startup_auto_restart_scheduled or self.startup_auto_restart_ran:
            return
        self.startup_auto_restart_scheduled = True
        self.append_log("[BOOT] Startup auto restart scheduled.")
        self.schedule_startup_auto_restart_timer()

    def schedule_startup_auto_restart_timer(self):
        QTimer.singleShot(STARTUP_AUTO_RESTART_DELAY_MS, self.run_startup_auto_restart)

    def run_startup_auto_restart(self):
        if self.startup_auto_restart_ran:
            return False
        self.startup_auto_restart_ran = True
        skip_reason = DashboardApp.startup_auto_restart_skip_reason(self)
        if skip_reason:
            self.append_log(f"[BOOT] Startup auto restart skipped: {skip_reason}.")
            return False
        self.request_bot_restart(source="startup")
        return True

    def runtime_heartbeat_age_seconds(self, runtime_state):
        heartbeat = str((runtime_state or {}).get("heartbeat_at") or "").strip()
        if not heartbeat:
            return None
        try:
            heartbeat_at = datetime.fromisoformat(heartbeat)
        except Exception:
            return None
        return max(0.0, (datetime.now() - heartbeat_at).total_seconds())

    def bot_runtime_stale_reason(self, runtime_state):
        if not runtime_state or not runtime_state.get("pid"):
            return ""
        status = str(runtime_state.get("status") or "").strip().lower()
        if status in {"stale", "error", "disconnected", "closed"}:
            return status
        heartbeat_age = DashboardApp.runtime_heartbeat_age_seconds(self, runtime_state)
        if heartbeat_age is not None and heartbeat_age >= BOT_RUNTIME_HEARTBEAT_STALE_SECONDS:
            return f"heartbeat stale ({int(heartbeat_age)}s)"
        return ""

    def maybe_reconnect_stale_bot_runtime(self, runtime_state):
        reason = DashboardApp.bot_runtime_stale_reason(self, runtime_state)
        if not reason:
            if getattr(self, "bot_health_reconnect_attempts", 0):
                self.bot_health_reconnect_attempts = 0
                self.bot_health_next_reconnect_at = 0.0
            return False
        if getattr(self, "_closing", False):
            return False
        if self.restart_in_progress:
            return False
        now = time.monotonic()
        if now < float(getattr(self, "bot_health_next_reconnect_at", 0.0) or 0.0):
            return False
        self.bot_health_last_reason = reason
        return self.request_bot_restart(source="health")

    def poll_bot_process(self):
        if self.process is not None:
            return_code = self.process.poll()
            if return_code is None:
                runtime_state = get_active_bot_runtime_state()
                self.maybe_reconnect_stale_bot_runtime(runtime_state)
                return
            should_reconnect = not getattr(self, "_closing", False) and not self.restart_in_progress
            clear_bot_runtime_state(self.process.pid)
            self.append_log(f"[BOT] Bot process exited with code {return_code}")
            self.process = None
            self.external_bot_runtime_active = False
            self.set_status(False)
            self.update_runtime_timer_policy()
            if should_reconnect:
                self.request_bot_restart(source="health")
            return

        if getattr(self, "external_bot_runtime_active", False):
            runtime_state = get_active_bot_runtime_state()
            if runtime_state.get("pid"):
                self.set_status(True)
                self.maybe_reconnect_stale_bot_runtime(runtime_state)
            else:
                self.external_bot_runtime_active = False
                self.set_status(False)
                self.update_runtime_timer_policy()

    # =========================
    # Manual chat
    # =========================
    def send_manual_chat(self):
        token_details = load_token_details(BOT_AUTH_ROLE)
        token = token_details.get("access_token")
        if not token:
            self.append_log("Connect Bot Account first.")
            return

        bot_login = self.settings_bot_login.text().strip() or self.bot_login_entry.text().strip()
        channel_login = self.settings_channel_login.text().strip() or self.channel_login_entry.text().strip()
        message = self.manual_message_entry.text().strip()

        if not bot_login or not channel_login or not message:
            self.append_log("Fill bot login, channel login, and message first")
            return

        try:
            bot_user = get_user_by_login(CLIENT_ID, token, bot_login)
            channel_user = get_user_by_login(CLIENT_ID, token, channel_login)
            if not bot_user:
                self.append_log("Bot account not found")
                return
            if not channel_user:
                self.append_log("Channel account not found")
                return

            send_chat_message(CLIENT_ID, token, channel_user["id"], bot_user["id"], message)
            self.append_log(f"Sent message to #{channel_login}")
            self.manual_message_entry.clear()
        except Exception as exc:
            self.append_log(f"Failed to send message: {exc}")

    # =========================
    # Music UI sync
    # =========================



    # =========================
    # Music logic
    # =========================





























    # =========================
    # Dashboard data
    # =========================
    def set_label_text_if_changed(self, label, text):
        value = str(text)
        if label.text() == value:
            return False
        label.setText(value)
        return True

    def refresh_dashboard_stats(self, *, force=False):
        messages_today = int(self.dashboard_state.get("messages_today", 0) or 0)
        commands_used = int(self.dashboard_state.get("commands_used", 0) or 0)
        timeouts_today = int(self.dashboard_state.get("timeouts_today", 0) or 0)
        current_hour = time.localtime().tm_hour
        channel_name = self.current_channel_login() or "your channel"
        signature = (
            messages_today,
            commands_used,
            timeouts_today,
            self.dashboard_state.get("last_updated", ""),
            current_hour,
            channel_name,
        )
        if not force and signature == self.dashboard_ui_signatures.get("stats"):
            return False
        self.dashboard_ui_signatures["stats"] = signature

        self.set_label_text_if_changed(self.messages_today_value, messages_today)
        self.set_label_text_if_changed(self.commands_value, commands_used)
        self.set_label_text_if_changed(self.timeouts_value, timeouts_today)

        if current_hour < 12:
            greeting = "Good morning"
        elif current_hour < 18:
            greeting = "Good afternoon"
        else:
            greeting = "Good evening"
        if hasattr(self, "dashboard_heading_label"):
            self.set_localized_text(
                self.dashboard_heading_label,
                "dashboard.greeting",
                greeting=self.localize(greeting),
                channel=channel_name if channel_name != "your channel" else self.localize("your channel"),
            )
        if hasattr(self, "dashboard_subtitle_label"):
            self.set_localized_text(
                self.dashboard_subtitle_label,
                "Here is a cleaner 7-day overview of messages, commands, timeouts, and live activity.",
            )
        if hasattr(self, "dashboard_last_updated_label"):
            last_updated = self.dashboard_state.get("last_updated", "")
            if last_updated:
                self.set_localized_text(self.dashboard_last_updated_label, "dashboard.updated", time=last_updated)
            else:
                self.set_localized_text(self.dashboard_last_updated_label, "Waiting for your first activity pulse")
        return True

    def refresh_dashboard_chart(self, *, force=False):
        history = self.dashboard_state.get("analytics_history", [])[-7:]
        signature = tuple(
            (
                str(bucket.get("date", "")),
                int(bucket.get("messages", 0) or 0),
                int(bucket.get("commands", 0) or 0),
                int(bucket.get("timeouts", 0) or 0),
            )
            for bucket in history
        )
        if not force and signature == self.dashboard_ui_signatures.get("chart"):
            return False
        self.dashboard_ui_signatures["chart"] = signature

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

        if hasattr(self, "dashboard_chart"):
            self.dashboard_chart.set_series_data(
                labels,
                {
                    "Messages": messages_series,
                    "Commands": commands_series,
                    "Timeouts": timeouts_series,
                },
                tooltip_labels=tooltip_labels,
            )

        if hasattr(self, "messages_today_hint_value"):
            self.set_localized_text(self.messages_today_hint_value, "dashboard.seven_day_total", total=sum(messages_series))
        if hasattr(self, "commands_hint_value"):
            self.set_localized_text(self.commands_hint_value, "dashboard.seven_day_total", total=sum(commands_series))
        if hasattr(self, "timeouts_hint_value"):
            self.set_localized_text(self.timeouts_hint_value, "dashboard.seven_day_total", total=sum(timeouts_series))
        return True

    def refresh_dashboard_top_chatters(self, *, force=False):
        sorted_chatters = sorted(
            self.dashboard_state.get("top_chatters", {}).items(),
            key=lambda item: item[1],
            reverse=True,
        )[:5]
        signature = tuple((str(name), int(count or 0)) for name, count in sorted_chatters)
        if not force and signature == self.dashboard_ui_signatures.get("top_chatters"):
            return False
        self.dashboard_ui_signatures["top_chatters"] = signature
        self.populate_dashboard_table(
            self.top_chatters_table,
            sorted_chatters,
            empty_left="No chatters yet",
            empty_right="0",
        )
        return True

    def refresh_dashboard_chat_preview(self, *, force=False):
        entries = self.dashboard_state.get("recent_chat", [])[-50:]
        signature = (
            self.current_channel_login().strip().lower(),
            tuple(
                (
                    str(entry.get("username", "")),
                    str(entry.get("text", "")),
                    str(entry.get("timestamp", "")),
                    str(entry.get("platform", "")),
                )
                for entry in entries
            ),
        )
        if not force and signature == self.dashboard_ui_signatures.get("chat_preview"):
            return False
        self.dashboard_ui_signatures["chat_preview"] = signature

        html_text = self.chat_renderer.build_chat_html(
            entries,
            self.current_channel_login(),
            fetch_remote_assets=False,
        )
        self.sync_scroll_html(self.chat_live, html_text)
        self.sync_scroll_html(self.chat_page_text, html_text)
        self.request_chat_asset_warmup(entries)
        return True

    def refresh_dashboard_alert_card(self, *, force=False):
        if not hasattr(self, "dashboard_alert_rows_layout"):
            return False
        self.load_alert_feed_items(force=force)
        alerts = self.get_latest_alert_feed_items(3)
        signature = tuple(str(item.get("id") or self.alert_render_log_key(item)) for item in alerts)
        if not force and signature == self.dashboard_ui_signatures.get("alerts_card"):
            return False
        self.dashboard_ui_signatures["alerts_card"] = signature
        self.refresh_dashboard_alerts()
        return True

    def refresh_active_page_if_needed(self, changes, *, force=False):
        page_name = getattr(self, "current_page_name", "Dashboard")
        if page_name == "Viewers" and (force or changes.get("dashboard") or changes.get("users")):
            self.refresh_viewers_dashboard()
        elif page_name == "Alerts":
            alerts_changed = bool(changes.get("alerts"))
            status_changed = bool(changes.get("alert_status"))
            if force or alerts_changed or status_changed:
                self.request_viewer_relationships_sync(force=False)
                self.refresh_alert_feed()

    def refresh_dashboard(self, *, force=False):
        changes = self.refresh_cached_runtime_state(force=force)
        dashboard_changed = bool(changes.get("dashboard"))
        users_changed = bool(changes.get("users"))
        alert_status_changed, _ = self.cached_file_changed("alert_status", ALERT_STATUS_FILE, force=force)
        alerts_changed, _ = self.cached_file_changed("alerts", ALERTS_FILE, force=force)
        if alert_status_changed:
            self.alert_status_cache = load_alert_status(ALERT_STATUS_FILE)
            self.alert_status_signature = self.file_signature_cache.get("alert_status")
        if alerts_changed:
            self.alert_feed_loaded = False

        self.refresh_dashboard_stats(force=force or dashboard_changed)
        if force or dashboard_changed:
            self.refresh_dashboard_chart(force=force)
            self.refresh_dashboard_top_chatters(force=force)
            self.refresh_dashboard_chat_preview(force=force)

        if force or alerts_changed:
            self.refresh_dashboard_alert_card(force=force or alerts_changed)

        status_signature = (
            self.process.pid if self.process is not None and self.process.poll() is None else 0,
            self.alerts_process.pid if self.alerts_process is not None and self.alerts_process.poll() is None else 0,
            alert_status_changed,
        )
        if force or status_signature != self.dashboard_ui_signatures.get("status"):
            self.dashboard_ui_signatures["status"] = status_signature
            self.update_dashboard_status_badge()
            self.update_alerts_status_ui()

        self.refresh_active_page_if_needed(
            {
                "dashboard": dashboard_changed,
                "users": users_changed,
                "alerts": alerts_changed,
                "alert_status": alert_status_changed,
            },
            force=force,
        )

    # =========================
    # Page builders
    # =========================
    def build_stat_card(self, title, value_ref_name, subtitle_ref_name=None, accent_key="messages"):
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        title_label = self.set_label_role(QLabel(title), "statTitle")
        value_label = QLabel("0")
        self.set_label_role(value_label, "statValue")
        accent_bar = QFrame()
        accent_bar.setFixedHeight(3)
        if not hasattr(self, "stat_accent_bars"):
            self.stat_accent_bars = {}
        self.stat_accent_bars[accent_key] = accent_bar

        setattr(self, value_ref_name, value_label)
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addWidget(accent_bar)

        if subtitle_ref_name:
            subtitle_label = self.set_label_role(QLabel(""), "statSubtitle")
            setattr(self, subtitle_ref_name, subtitle_label)
            layout.addWidget(subtitle_label)

        layout.addStretch()
        return card

    def build_dashboard_table_card(self, title, subtitle, headers, table_ref_name):
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title_label = self.set_label_role(QLabel(title), "cardTitle")
        layout.addWidget(title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setWordWrap(True)
            self.set_label_role(subtitle_label, "cardSubtitle")
            layout.addWidget(subtitle_label)

        table = self.make_dashboard_table(headers)
        table.setMinimumHeight(150)
        setattr(self, table_ref_name, table)
        layout.addWidget(table)
        return card

    def get_latest_alert_feed_items(self, limit=3):
        self.load_alert_feed_items()
        return sorted(
            list(self.alert_feed_items or []),
            key=lambda item: (
                parse_alert_datetime(item.get("occurred_at")).timestamp()
                if parse_alert_datetime(item.get("occurred_at"))
                else 0
            ),
            reverse=True,
        )[:limit]

    def refresh_dashboard_alerts(self):
        if not hasattr(self, "dashboard_alert_rows_layout"):
            return
        self.clear_layout_widgets(self.dashboard_alert_rows_layout)
        alerts = self.get_latest_alert_feed_items(3)
        if not alerts:
            empty_label = QLabel()
            self.set_localized_text(empty_label, "No recent Twitch alerts captured yet")
            empty_label.setAlignment(Qt.AlignCenter)
            empty_label.setMinimumHeight(120)
            self.set_label_role(empty_label, "mutedBody")
            self.dashboard_alert_rows_layout.addWidget(empty_label)
        else:
            for item in alerts:
                self.dashboard_alert_rows_layout.addWidget(self.build_alert_feed_row(item))
            self.log_rendered_alert_events(alerts, source="cached")
        self.dashboard_alert_rows_layout.addStretch()

    def build_dashboard_alerts_card(self):
        card = Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        header_row.addWidget(self.set_label_role(QLabel("Alerts"), "cardTitle"), 1)
        view_all_button = self.make_button("View All", "ghost", lambda: self.switch_page("Alerts"))
        view_all_button.setMaximumWidth(90)
        header_row.addWidget(view_all_button)
        layout.addLayout(header_row)

        subtitle = QLabel("Latest Twitch activity feed events.")
        subtitle.setWordWrap(True)
        self.set_label_role(subtitle, "cardSubtitle")
        layout.addWidget(subtitle)

        rows_body = QWidget()
        self.dashboard_alert_rows_layout = QVBoxLayout(rows_body)
        self.dashboard_alert_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.dashboard_alert_rows_layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(rows_body)
        scroll.setMinimumHeight(150)
        scroll.setMaximumHeight(178)
        layout.addWidget(scroll)
        self.refresh_dashboard_alerts()
        return card

    def build_dashboard_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        body = QWidget()
        outer = QVBoxLayout(body)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(16)

        hero_row = QHBoxLayout()
        hero_row.setSpacing(12)

        hero_text = QVBoxLayout()
        hero_text.setSpacing(2)
        self.dashboard_heading_label = self.set_label_role(QLabel("Channel overview"), "heroTitle")
        hero_text.addWidget(self.dashboard_heading_label)

        self.dashboard_subtitle_label = QLabel(
            "A cleaner live snapshot of messages, commands, timeouts, and playback activity."
        )
        self.set_label_role(self.dashboard_subtitle_label, "heroSubtitle")
        self.dashboard_subtitle_label.setWordWrap(True)
        hero_text.addWidget(self.dashboard_subtitle_label)
        hero_row.addLayout(hero_text, 1)

        hero_side = QVBoxLayout()
        hero_side.setSpacing(8)
        self.dashboard_status_badge = self.make_badge_label("Ready to start", "info")
        hero_side.addWidget(self.dashboard_status_badge, 0, Qt.AlignRight)
        self.dashboard_last_updated_label = self.set_label_role(QLabel("Waiting for activity"), "heroMeta")
        hero_side.addWidget(self.dashboard_last_updated_label, 0, Qt.AlignRight)
        hero_row.addLayout(hero_side)
        outer.addLayout(hero_row)

        overview_card = Card()
        overview_layout = QVBoxLayout(overview_card)
        overview_layout.setContentsMargins(18, 18, 18, 18)
        overview_layout.setSpacing(14)

        metric_row = QHBoxLayout()
        metric_row.setSpacing(12)
        metric_row.addWidget(
            self.build_stat_card(
                "Messages Today",
                "messages_today_value",
                "messages_today_hint_value",
                accent_key="messages",
            )
        )
        metric_row.addWidget(
            self.build_stat_card(
                "Commands",
                "commands_value",
                "commands_hint_value",
                accent_key="commands",
            )
        )
        metric_row.addWidget(
            self.build_stat_card(
                "Timeouts",
                "timeouts_value",
                "timeouts_hint_value",
                accent_key="timeouts",
            )
        )
        overview_layout.addLayout(metric_row)

        self.dashboard_chart = AnalyticsChartWidget()
        overview_layout.addWidget(self.dashboard_chart)
        outer.addWidget(overview_card)

        insight_row = QHBoxLayout()
        insight_row.setSpacing(16)
        alerts_card = self.build_dashboard_alerts_card()
        top_chatters_card = self.build_dashboard_table_card(
            "Top Chatters",
            "Most active chatters in the current dashboard snapshot.",
            ("Chatter", "Messages"),
            "top_chatters_table",
        )
        alerts_card.setMinimumHeight(240)
        alerts_card.setMaximumHeight(280)
        top_chatters_card.setMinimumHeight(240)
        top_chatters_card.setMaximumHeight(280)
        insight_row.addWidget(alerts_card, 1)
        insight_row.addWidget(top_chatters_card, 1)
        outer.addLayout(insight_row)

        operations_row = QHBoxLayout()
        operations_row.setSpacing(16)

        live_chat_card = Card()
        live_chat_layout = QVBoxLayout(live_chat_card)
        live_chat_layout.setContentsMargins(18, 18, 18, 18)
        live_chat_layout.setSpacing(12)
        live_chat_layout.addWidget(self.make_title("Twitch Chat Live"))

        live_chat_subtitle = self.set_label_role(
            QLabel("Recent chat activity rendered with badges, emotes, and mentions."),
            "cardSubtitle",
        )
        live_chat_subtitle.setWordWrap(True)
        live_chat_layout.addWidget(live_chat_subtitle)

        self.chat_live = QTextEdit()
        self.chat_live.setReadOnly(True)
        self.chat_live.setMinimumHeight(350)
        live_chat_layout.addWidget(self.chat_live)
        live_chat_card.setMinimumHeight(420)
        live_chat_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        operations_row.addWidget(live_chat_card, 1)

        (
            music_card,
            self.thumbnail_label,
            self.now_playing_value,
            self.music_entry,
            self.queue_listbox,
            self.dashboard_music_toggle,
        ) = self.make_now_playing_card(
            "Now Playing",
            (160, 220),
            MUSIC_INPUT_PLACEHOLDER,
            self.paste_music,
            self.play_youtube_audio,
            queue_min_height=110,
            compact=True,
        )
        self.setup_queue_widget(self.queue_listbox)
        music_card.setMinimumHeight(420)
        music_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        operations_row.addWidget(music_card, 1)
        outer.addLayout(operations_row)

        utility_row = QHBoxLayout()
        utility_row.setSpacing(16)

        log_card = Card()
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(18, 18, 18, 18)
        log_layout.setSpacing(12)
        log_layout.addWidget(self.make_title("Live Log"))

        log_subtitle = self.set_label_role(
            QLabel("Backend activity, command flow, and playback events appear here in real time."),
            "cardSubtitle",
        )
        log_subtitle.setWordWrap(True)
        log_layout.addWidget(log_subtitle)

        self.live_log = QPlainTextEdit()
        self.live_log.setReadOnly(True)
        self.live_log.setMaximumBlockCount(MAX_LIVE_LOG_LINES)
        self.live_log.setMinimumHeight(220)
        log_layout.addWidget(self.live_log)
        self.flush_pending_log_lines()
        utility_row.addWidget(log_card, 1)

        bot_settings_card = self.build_bot_settings_card()
        utility_row.addWidget(bot_settings_card, 1)

        outer.addLayout(utility_row)

        layout.addWidget(self.make_scroll_container(body))
        return page

    def build_chat_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        card = Card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.addWidget(self.make_title("Chat"))

        self.chat_page_text = QTextEdit()
        self.chat_page_text.setReadOnly(True)
        card_layout.addWidget(self.chat_page_text)

        layout.addWidget(card)
        return page




    def build_settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(14)

        body_layout.addWidget(self.build_theme_settings_card())

        account_card = Card()
        account_layout = QVBoxLayout(account_card)
        account_layout.setContentsMargins(14, 14, 14, 14)
        account_layout.setSpacing(12)
        account_layout.addWidget(self.make_title("Bot Setup"))

        self.settings_bot_login = self.make_labeled_entry(account_layout, "Bot Login")
        self.settings_bot_login.setReadOnly(True)
        self.settings_bot_login.setProperty("readOnlyDisplay", "true")
        self.settings_bot_login.setPlaceholderText("Bot account not connected")
        self.apply_input_control_style(self.settings_bot_login)

        self.settings_channel_login = self.make_labeled_entry(account_layout, "Channel Login")
        self.settings_channel_login.setReadOnly(True)
        self.settings_channel_login.setProperty("readOnlyDisplay", "true")
        self.settings_channel_login.setPlaceholderText("Channel account not connected")
        self.apply_input_control_style(self.settings_channel_login)

        account_layout.addWidget(self.make_small_title("Trigger Input"))
        self.trigger_input = QLineEdit()
        self.trigger_input.setPlaceholderText("Type a trigger and press Enter")
        self.apply_input_control_style(self.trigger_input)
        self.trigger_input.returnPressed.connect(self.add_trigger_from_input)
        account_layout.addWidget(self.trigger_input)

        self.trigger_chips_frame = QFrame()
        self.trigger_chips_frame.setProperty("surfaceRole", "subtle")
        self.trigger_chips_layout = QHBoxLayout(self.trigger_chips_frame)
        self.trigger_chips_layout.setContentsMargins(8, 8, 8, 8)
        self.trigger_chips_layout.setSpacing(8)
        account_layout.addWidget(self.trigger_chips_frame)

        body_layout.addWidget(account_card)
        body_layout.addWidget(self.build_ai_settings_card())
        body_layout.addWidget(self.build_runtime_controls_card())
        body_layout.addWidget(self.build_update_settings_card())
        body_layout.addWidget(self.build_technical_support_card())
        body_layout.addStretch()
        layout.addWidget(self.make_scroll_container(body))
        return page

    def build_ui(self):
        central = QWidget()
        central.setObjectName("appRoot")
        central.setAttribute(Qt.WA_StyledBackground, True)
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setProperty("surfaceRole", "sidebar")
        self.sidebar.setFixedWidth(260)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(14, 18, 14, 16)
        sidebar_layout.setSpacing(12)

        self.brand_card = QFrame()
        self.brand_card.setProperty("surfaceRole", "brand")
        brand_layout = QHBoxLayout(self.brand_card)
        brand_layout.setContentsMargins(12, 12, 12, 12)
        brand_layout.setSpacing(10)

        self.brand_logo_label = QLabel()
        self.brand_logo_label.setFixedSize(36, 36)
        self.brand_logo_label.setAlignment(Qt.AlignCenter)
        brand_logo = self.get_brand_logo_pixmap(36)
        if not brand_logo.isNull():
            self.brand_logo_label.setPixmap(brand_logo)
        brand_layout.addWidget(self.brand_logo_label, 0, Qt.AlignVCenter)

        brand_text_layout = QVBoxLayout()
        brand_text_layout.setContentsMargins(0, 0, 0, 0)
        brand_text_layout.setSpacing(2)

        self.brand_title_label = self.set_label_role(QLabel(APP_NAME), "brandTitle")
        self.brand_title_label.setMinimumWidth(130)
        self.brand_title_label.setWordWrap(False)
        self.brand_subtitle_label = self.set_label_role(QLabel("Live bot control center"), "brandSubtitle")
        self.brand_subtitle_label.setWordWrap(False)
        brand_text_layout.addWidget(self.brand_title_label)
        brand_text_layout.addWidget(self.brand_subtitle_label)
        brand_layout.addLayout(brand_text_layout, 1)
        sidebar_layout.addWidget(self.brand_card)

        self.nav_label = self.set_label_role(QLabel("Navigation"), "navLabel")
        sidebar_layout.addWidget(self.nav_label)

        self.nav_buttons = {}
        for name in NAVIGATION_ITEMS:
            button = SidebarButton(name)
            button.clicked.connect(lambda checked=False, page_name=name: self.switch_page(page_name))
            sidebar_layout.addWidget(button)
            self.nav_buttons[name] = button
        sidebar_layout.addStretch()

        self.sidebar_accounts_card = QFrame()
        self.sidebar_accounts_card.setProperty("surfaceRole", "subtle")
        self.sidebar_accounts_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        accounts_layout = QVBoxLayout(self.sidebar_accounts_card)
        accounts_layout.setContentsMargins(8, 8, 8, 8)
        accounts_layout.setSpacing(6)

        self.bot_account_card = SidebarAccountCard("Bot")
        self.bot_account_card.set_account_state(
            username=self.settings.get("bot_login", "").strip() or "Not connected",
            avatar=self.build_avatar_pixmap(fallback_text="B", size=32),
        )
        accounts_layout.addWidget(self.bot_account_card)

        self.channel_account_card = SidebarAccountCard("Channel")
        self.channel_account_card.set_account_state(
            username=self.settings.get("channel_login", "").strip() or "Not connected",
            avatar=self.build_avatar_pixmap(fallback_text="C", size=32),
        )
        accounts_layout.addWidget(self.channel_account_card)

        sidebar_layout.addWidget(self.sidebar_accounts_card)

        self.main_area = QFrame()
        self.main_area.setProperty("surfaceRole", "main")
        main_layout = QVBoxLayout(self.main_area)
        main_layout.setContentsMargins(22, 20, 22, 20)
        main_layout.setSpacing(16)

        self.stack = QStackedWidget()
        self.stack.setObjectName("mainStack")
        self.stack.setAttribute(Qt.WA_StyledBackground, True)
        pages = [
            self.build_dashboard_page(),
            self.build_chat_page(),
            self.build_music_page(),
            self.build_viewers_page(),
            self.build_alerts_page(),
            self.build_twitch_page(),
            self.build_settings_page(),
        ]
        (
            self.dashboard_page,
            self.chat_page,
            self.music_page,
            self.viewers_page,
            self.alerts_page,
            self.twitch_page,
            self.settings_page,
        ) = pages
        for page in pages:
            self.stack.addWidget(page)

        main_layout.addWidget(self.stack)
        root.addWidget(self.sidebar)
        root.addWidget(self.main_area)

        self.switch_page("Dashboard")
        self.register_static_localized_widgets()
        self.apply_theme(refresh_content=False)
        self.apply_language(refresh_content=False)

    def apply_theme(self, refresh_content=True):
        self.chat_renderer.apply_theme(self.theme)
        self.setStyleSheet(self.build_localized_app_stylesheet())

        for widget in self.findChildren(SidebarButton):
            widget.apply_theme(self.theme)
        for widget in self.findChildren(ActionButton):
            widget.apply_theme(self.theme)
        for widget in self.findChildren(Card):
            widget.apply_theme(self.theme)
        for widget in self.findChildren(ThumbnailWidget):
            widget.apply_theme(self.theme)
        for widget in self.findChildren(AnalyticsChartWidget):
            widget.apply_theme(self.theme)
        for widget in self.findChildren(SidebarAccountCard):
            widget.apply_theme(self.theme)
        for widget in self.findChildren(StatusDot):
            widget.apply_theme(self.theme)
        for widget in self.findChildren(ThemedCheckBox):
            widget.apply_theme(self.theme)
        for widget in self.findChildren(TriggerChipWidget):
            widget.apply_theme(self.theme)
        for widget in [getattr(self, "queue_listbox", None), getattr(self, "music_page_queue", None)]:
            self.apply_queue_widget_style(widget)
        for widget in self.findChildren(QComboBox):
            self.apply_combo_popup_style(widget)
        for widget_class in (QLineEdit, QPlainTextEdit):
            for widget in self.findChildren(widget_class):
                self.apply_input_control_style(widget)
        for widget in [
            getattr(self, "sidebar", None),
            getattr(self, "brand_card", None),
            getattr(self, "main_area", None),
            getattr(self, "stack", None),
            getattr(self, "trigger_chips_frame", None),
            getattr(self, "sidebar_accounts_card", None),
        ]:
            self.polish_widget(widget)

        accent_map = {
            "messages": self.theme.chart_messages,
            "commands": self.theme.chart_commands,
            "timeouts": self.theme.chart_timeouts,
        }
        for accent_key, widget in getattr(self, "stat_accent_bars", {}).items():
            color = accent_map.get(accent_key, self.theme.accent)
            widget.setStyleSheet(f"background:{color};border:none;border-radius:2px;")

        for table_name in ("top_commands_table", "top_chatters_table", "viewer_top_chatters_table", "viewer_relationships_table"):
            table = getattr(self, table_name, None)
            if table is not None:
                self.apply_dashboard_table_style(table)
        if hasattr(self, "viewer_table"):
            self.apply_viewer_table_style(self.viewer_table)
        self.sync_viewer_filter_buttons()

        if hasattr(self, "theme_selector"):
            index = self.theme_selector.findData(self.theme_name)
            if index >= 0 and self.theme_selector.currentIndex() != index:
                self.theme_selector.blockSignals(True)
                self.theme_selector.setCurrentIndex(index)
                self.theme_selector.blockSignals(False)
        self.log_retention_minutes = self.resolve_log_retention_minutes(
            self.settings.get("log_retention_minutes", self.log_retention_minutes)
        )
        self.sync_log_retention_selector()

        self.refresh_token_status()
        self.set_status(self.process is not None and self.process.poll() is None)
        self.sync_music_toggle_buttons()
        self.update_dashboard_status_badge()
        if refresh_content:
            self.refresh_dashboard()

    def switch_page(self, name):
        page_indexes = {page_name: index for index, page_name in enumerate(NAVIGATION_ITEMS)}
        self.stack.setCurrentIndex(page_indexes[name])
        self.current_page_name = name
        for key, button in self.nav_buttons.items():
            button.setChecked(key == name)
        self.update_runtime_timer_policy()
        if name == "Viewers":
            self.refresh_viewers_dashboard()
        elif name == "Alerts":
            self.refresh_alert_feed()
        elif name == "Twitch":
            self.refresh_account_widget(force=self.is_bot_process_running())

    # =========================
    # Initialization
    # =========================
    def load_initial_values(self):
        self.bot_login_entry.setText(self.settings.get("bot_login", ""))
        self.channel_login_entry.setText(self.settings.get("channel_login", ""))
        self.settings_bot_login.setText(self.settings.get("bot_login", ""))
        self.settings_channel_login.setText(self.settings.get("channel_login", ""))

        triggers_raw = self.settings.get("triggers", "")
        self.trigger_list = [item.strip() for item in triggers_raw.split(",") if item.strip()]
        self.render_trigger_chips()
        if self.trigger_list:
            self.clear_i18n_binding(self.triggers_preview_value)
            self.triggers_preview_value.setText(", ".join(self.trigger_list))
        else:
            self.set_localized_text(self.triggers_preview_value, "No triggers")

        self.openai_key_entry.setText(self.settings.get("openai_api_key", ""))
        self.prompt_box.setPlainText(self.settings.get("system_prompt", DEFAULT_PROMPT))
        if hasattr(self, "theme_selector"):
            selector_index = self.theme_selector.findData(self.theme_name)
            if selector_index >= 0:
                self.theme_selector.blockSignals(True)
                self.theme_selector.setCurrentIndex(selector_index)
                self.theme_selector.blockSignals(False)
        self.sync_language_selector()

        self.music_enabled = bool(self.settings.get("music_enabled", True))
        self.prevent_duplicate_tracks = bool(self.settings.get("prevent_duplicate_tracks", True))
        self.auto_restart_bot_on_startup = bool(self.settings.get("auto_restart_bot_on_startup", True))
        self.viewer_sort_key = str(self.settings.get("viewer_sort", "messages") or "messages")
        self.relationship_sort_key = str(self.settings.get("relationship_sort", "newest") or "newest")
        self.alert_feed_filter = str(self.settings.get("alert_feed_filter", DEFAULT_ALERT_FEED_FILTER) or DEFAULT_ALERT_FEED_FILTER)
        self.log_retention_minutes = self.resolve_log_retention_minutes(
            self.settings.get("log_retention_minutes", self.log_retention_minutes)
        )
        self.audio_volume = max(0, min(100, int(self.settings.get("audio_volume", self.audio_volume))))
        self.audio_muted = bool(self.settings.get("audio_muted", self.audio_muted))
        self.sync_music_toggle_buttons()
        self.sync_prevent_duplicate_checkboxes()
        self.sync_auto_restart_startup_checkbox()
        self.sync_volume_controls()
        if hasattr(self, "viewer_sort_selector"):
            selector_index = self.viewer_sort_selector.findData(self.viewer_sort_key)
            if selector_index >= 0:
                self.viewer_sort_selector.blockSignals(True)
                self.viewer_sort_selector.setCurrentIndex(selector_index)
                self.viewer_sort_selector.blockSignals(False)
        if hasattr(self, "relationship_sort_selector"):
            selector_index = self.relationship_sort_selector.findData(self.relationship_sort_key)
            if selector_index >= 0:
                self.relationship_sort_selector.blockSignals(True)
                self.relationship_sort_selector.setCurrentIndex(selector_index)
                self.relationship_sort_selector.blockSignals(False)
        if hasattr(self, "alert_filter_selector"):
            selector_index = self.alert_filter_selector.findData(self.alert_feed_filter)
            if selector_index >= 0:
                self.alert_filter_selector.blockSignals(True)
                self.alert_filter_selector.setCurrentIndex(selector_index)
                self.alert_filter_selector.blockSignals(False)
        self.sync_log_retention_selector()
        self.refresh_alert_feed()
        self.reset_music_session_state()
        self.append_log("[APP] App started")
        self.append_log("[APP] Idle startup complete. Alerts start automatically when Channel Account is connected.")
        self.append_log("[APP] Music command bridge ready")
        existing_runtime = get_active_bot_runtime_state()
        self.external_bot_runtime_active = bool(existing_runtime.get("pid"))
        if existing_runtime.get("pid"):
            self.append_log(
                f"[BOT] Existing bot process detected (PID {existing_runtime.get('pid')}). Use Stop Bot before starting another one."
            )
            self.set_status(True)
        existing_alert_runtime = get_active_alert_runtime_state()
        self.external_alert_runtime_active = bool(existing_alert_runtime.get("pid"))
        if existing_alert_runtime.get("pid"):
            self.append_log(f"[ALERTS] Existing alerts listener detected (PID {existing_alert_runtime.get('pid')})")
        QTimer.singleShot(100, self.refresh_dashboard)
        QTimer.singleShot(250, self.refresh_token_status)
        QTimer.singleShot(450, self.refresh_account_widget)
        QTimer.singleShot(650, lambda: self.request_auth_health_check(force=True))
        QTimer.singleShot(1500, self.show_pending_crash_dialog)
        if self.update_config.auto_update_enabled:
            QTimer.singleShot(4200, lambda: self.check_for_updates(auto=True))

    def start_timers(self):
        self.timer_dashboard = QTimer(self)
        self.timer_dashboard.timeout.connect(self.refresh_dashboard)
        self.timer_dashboard.start(5000)

        self.timer_music = QTimer(self)
        self.timer_music.timeout.connect(self.process_music_command)
        self.timer_music.setInterval(1500)

        self.timer_player = QTimer(self)
        self.timer_player.timeout.connect(self.monitor_music_state)
        self.timer_player.setInterval(1500)

        self.timer_audio = QTimer(self)
        self.timer_audio.timeout.connect(self.poll_audio_state)
        self.timer_audio.setInterval(1500)

        self.timer_process = QTimer(self)
        self.timer_process.timeout.connect(self.poll_bot_process)
        self.timer_process.setInterval(2000)

        self.timer_alerts = QTimer(self)
        self.timer_alerts.timeout.connect(self.poll_alerts_process)
        self.timer_alerts.setInterval(5000)

        self.timer_live_log_retention = QTimer(self)
        self.timer_live_log_retention.timeout.connect(self.flush_pending_log_lines)
        self.timer_live_log_retention.start(60000)

        self.timer_auth_health = QTimer(self)
        self.timer_auth_health.timeout.connect(self.request_auth_health_check)
        self.timer_auth_health.start(60000)
        self.update_runtime_timer_policy()

    def set_timer_policy_state(self, timer, *, active, interval=None):
        if timer is None:
            return
        if interval is not None and timer.interval() != int(interval):
            timer.setInterval(int(interval))
        if active:
            if not timer.isActive():
                timer.start()
        elif timer.isActive():
            timer.stop()

    def music_runtime_active(self):
        player = getattr(self, "music_player", None)
        player_playing = False
        if player is not None:
            try:
                player_playing = bool(player.is_playing())
            except Exception:
                player_playing = False
        return bool(
            getattr(self, "music_loading", False)
            or getattr(self, "current_track_active", False)
            or player_playing
        )

    def update_runtime_timer_policy(self):
        page_name = getattr(self, "current_page_name", "Dashboard")
        self.set_timer_policy_state(
            getattr(self, "timer_dashboard", None),
            active=True,
            interval=5000 if page_name == "Dashboard" else 10000,
        )

        bot_process_active = bool(self.process is not None and self.process.poll() is None)
        alerts_process_active = bool(self.alerts_process is not None and self.alerts_process.poll() is None)
        bot_runtime_active = bool(bot_process_active or getattr(self, "external_bot_runtime_active", False))
        alerts_runtime_active = bool(alerts_process_active or getattr(self, "external_alert_runtime_active", False))
        music_active = self.music_runtime_active()
        channel_health = getattr(self, "auth_health_state", {}).get(CHANNEL_AUTH_ROLE, {})
        channel_connected = channel_health.get("state") == "connected"

        self.set_timer_policy_state(
            getattr(self, "timer_music", None),
            active=bool(bot_runtime_active or music_active or page_name == "Music"),
            interval=1500 if bot_runtime_active else 4000,
        )
        self.set_timer_policy_state(
            getattr(self, "timer_player", None),
            active=music_active,
            interval=1500,
        )
        self.set_timer_policy_state(
            getattr(self, "timer_audio", None),
            active=bool(music_active or getattr(self, "audio_session_attached", False)),
            interval=1500,
        )
        self.set_timer_policy_state(
            getattr(self, "timer_process", None),
            active=bot_runtime_active,
            interval=2000,
        )
        self.set_timer_policy_state(
            getattr(self, "timer_alerts", None),
            active=bool(alerts_runtime_active or channel_connected),
            interval=5000,
        )

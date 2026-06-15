import ctypes
import os
import sys
import traceback

from core.app_paths import WINDOW_ICON_ICO, WINDOW_ICON_JPEG, WINDOW_ICON_JPG, WINDOW_ICON_PNG
from core.runtime_env import configure_qt_plugin_env, configure_ssl_cert_env
from core.support import install_crash_hooks, write_crash_report
from core.ui.constants import APP_ID, APP_NAME

RUN_BOT_FLAG = "--run-bot"
RUN_ALERTS_FLAG = "--run-alerts"


def log_console(message):
    try:
        print(message, flush=True)
    except Exception:
        pass


def configure_windows_identity():
    if os.name != "nt":
        return

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def get_application_icon():
    from PySide6.QtGui import QIcon

    for path in [WINDOW_ICON_ICO, WINDOW_ICON_PNG, WINDOW_ICON_JPG, WINDOW_ICON_JPEG]:
        if path.exists():
            return QIcon(str(path))
    return None


def launch_desktop_app():
    configure_ssl_cert_env()
    qt_plugin_path = configure_qt_plugin_env()
    configure_windows_identity()
    install_crash_hooks()

    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)

    icon = get_application_icon()
    if icon is not None:
        app.setWindowIcon(icon)

    log_console("[APP] App started")
    log_console(f"[QT] Plugin path: {qt_plugin_path or 'not found'}")
    try:
        from core.app_paths import (
            ALERTS_FILE,
            CHAT_LOG_FILE,
            DASHBOARD_STATE_FILE,
            MUSIC_COMMAND_FILE,
            SETTINGS_FILE,
            USERS_FILE,
            VIEWER_RELATIONSHIPS_FILE,
        )
        from core.app_state import ensure_app_files, load_json
        from core.legal import legal_acceptance_current

        ensure_app_files(
            SETTINGS_FILE,
            USERS_FILE,
            DASHBOARD_STATE_FILE,
            MUSIC_COMMAND_FILE,
            CHAT_LOG_FILE,
            VIEWER_RELATIONSHIPS_FILE,
            ALERTS_FILE,
        )
        settings = load_json(SETTINGS_FILE, {})
        if not legal_acceptance_current(settings):
            from core.ui.legal_dialog import request_legal_acceptance

            if not request_legal_acceptance(SETTINGS_FILE):
                log_console("[APP] Terms and privacy acceptance declined")
                return 0

        from core.ui.window import DashboardApp

        window = DashboardApp()
        window.show()
        return app.exec()
    except Exception as exc:
        write_crash_report(type(exc), exc, exc.__traceback__, source="startup")
        traceback.print_exc()
        QMessageBox.critical(
            None,
            APP_NAME,
            f"App failed to start.\n\n{exc}",
        )
        return 1


def main():
    if RUN_ALERTS_FLAG in sys.argv:
        configure_ssl_cert_env()
        configure_qt_plugin_env()
        log_console("[ALERTS] Startup requested")
        try:
            from core.alert_listener import main as run_alert_listener

            return run_alert_listener()
        except Exception as exc:
            traceback.print_exc()
            log_console(f"[ERROR] Alerts failed to start: {exc}")
            return 1

    if RUN_BOT_FLAG in sys.argv:
        configure_ssl_cert_env()
        configure_qt_plugin_env()
        log_console("[BOT] Startup requested")
        try:
            from core.eventsub_bot import main as run_eventsub_bot

            run_eventsub_bot()
            return 0
        except Exception as exc:
            traceback.print_exc()
            log_console(f"[ERROR] Bot failed to start: {exc}")
            return 1

    return launch_desktop_app()


if __name__ == "__main__":
    sys.exit(main())

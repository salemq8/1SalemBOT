import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CORE_DIR = PROJECT_ROOT / "core"
DATA_DIR = PROJECT_ROOT / "data"
ASSETS_DIR = PROJECT_ROOT / "assets"
ALERT_ICONS_DIR = ASSETS_DIR / "icons" / "alerts"
TWITCH_STYLE_ALERT_ICONS_DIR = ASSETS_DIR / "icons" / "twitch_style_alerts"
TWITCH_GLITCH_LOGO_SVG = ASSETS_DIR / "icons" / "twitch" / "twitch_glitch_purple.svg"
APP_NAME = "1SalemBOT"
LEGACY_APP_NAME = "1SalemGPT"
APPDATA_ROOT = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
APP_STORAGE_OVERRIDE = (
    os.environ.get("SALEMBOT_DATA_DIR", "").strip()
    or os.environ.get("SALEMGPT_DATA_DIR", "").strip()
)
LEGACY_APP_STORAGE_DIR = APPDATA_ROOT / LEGACY_APP_NAME
APP_STORAGE_DIR = Path(APP_STORAGE_OVERRIDE).expanduser() if APP_STORAGE_OVERRIDE else APPDATA_ROOT / APP_NAME

# Runtime files live under %APPDATA%; data/ stays only as a legacy migration source.
SETTINGS_FILE = APP_STORAGE_DIR / "settings.json"
USERS_FILE = APP_STORAGE_DIR / "users.json"
DASHBOARD_STATE_FILE = APP_STORAGE_DIR / "dashboard_state.json"
MUSIC_COMMAND_FILE = APP_STORAGE_DIR / "music_command.json"
CHAT_LOG_FILE = APP_STORAGE_DIR / "chat_log.txt"
VIEWER_RELATIONSHIPS_FILE = APP_STORAGE_DIR / "viewer_relationships.json"
ALERTS_FILE = APP_STORAGE_DIR / "alerts.json"
ALERT_STATUS_FILE = APP_STORAGE_DIR / "alert_status.json"
BOT_RUNTIME_FILE = APP_STORAGE_DIR / "bot_runtime.json"
ALERT_RUNTIME_FILE = APP_STORAGE_DIR / "alert_runtime.json"
BOT_TOKEN_FILE = APP_STORAGE_DIR / "twitch_bot_auth.json"
CHANNEL_TOKEN_FILE = APP_STORAGE_DIR / "twitch_channel_auth.json"
TOKEN_FILE = BOT_TOKEN_FILE
LEGACY_TOKEN_FILE = CORE_DIR / "twitch_auth.json"
LEGACY_APPDATA_BOT_TOKEN_FILE = LEGACY_APP_STORAGE_DIR / "twitch_bot_auth.json"
LEGACY_APPDATA_CHANNEL_TOKEN_FILE = LEGACY_APP_STORAGE_DIR / "twitch_channel_auth.json"
LEGACY_SETTINGS_FILE = DATA_DIR / "settings.json"
LEGACY_USERS_FILE = DATA_DIR / "users.json"
LEGACY_DASHBOARD_STATE_FILE = DATA_DIR / "dashboard_state.json"
LEGACY_MUSIC_COMMAND_FILE = DATA_DIR / "music_command.json"
LEGACY_CHAT_LOG_FILE = DATA_DIR / "chat_log.txt"
LEGACY_VIEWER_RELATIONSHIPS_FILE = DATA_DIR / "viewer_relationships.json"
LEGACY_ALERTS_FILE = DATA_DIR / "alerts.json"
LEGACY_APPDATA_SETTINGS_FILE = LEGACY_APP_STORAGE_DIR / "settings.json"
LEGACY_APPDATA_USERS_FILE = LEGACY_APP_STORAGE_DIR / "users.json"
LEGACY_APPDATA_DASHBOARD_STATE_FILE = LEGACY_APP_STORAGE_DIR / "dashboard_state.json"
LEGACY_APPDATA_MUSIC_COMMAND_FILE = LEGACY_APP_STORAGE_DIR / "music_command.json"
LEGACY_APPDATA_CHAT_LOG_FILE = LEGACY_APP_STORAGE_DIR / "chat_log.txt"
LEGACY_APPDATA_VIEWER_RELATIONSHIPS_FILE = LEGACY_APP_STORAGE_DIR / "viewer_relationships.json"
LEGACY_APPDATA_ALERTS_FILE = LEGACY_APP_STORAGE_DIR / "alerts.json"

WINDOW_ICON_ICO = ASSETS_DIR / "bot_icon.ico"
WINDOW_ICON_PNG = ASSETS_DIR / "bot_logo.png"
WINDOW_ICON_JPG = ASSETS_DIR / "bot_logo.jpg"
WINDOW_ICON_JPEG = ASSETS_DIR / "bot_logo.jpeg"


def get_runtime_base_dir():
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return PROJECT_ROOT

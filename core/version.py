import re
import sys
from pathlib import Path


DEFAULT_APP_VERSION = "0.0.0"
DEFAULT_VERSION_CHANNEL = "stable"
VERSION_FILE_NAME = "VERSION"
VERSION_CHANNEL_FILE_NAME = "VERSION_CHANNEL"
CHANNEL_STABLE = "stable"
CHANNEL_BETA = "beta"


def _candidate_version_files():
    env_path = str(sys.argv[0] or "").strip()
    if env_path:
        executable_dir = Path(env_path).resolve().parent
        yield executable_dir / VERSION_FILE_NAME
        yield executable_dir / "_internal" / VERSION_FILE_NAME

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        yield Path(meipass) / VERSION_FILE_NAME

    yield Path(__file__).resolve().parent.parent / VERSION_FILE_NAME


def _candidate_channel_files():
    env_path = str(sys.argv[0] or "").strip()
    if env_path:
        executable_dir = Path(env_path).resolve().parent
        yield executable_dir / VERSION_CHANNEL_FILE_NAME
        yield executable_dir / "_internal" / VERSION_CHANNEL_FILE_NAME

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        yield Path(meipass) / VERSION_CHANNEL_FILE_NAME

    yield Path(__file__).resolve().parent.parent / VERSION_CHANNEL_FILE_NAME


def read_app_version(default=DEFAULT_APP_VERSION):
    for path in _candidate_version_files():
        try:
            if path.exists():
                version = path.read_text(encoding="utf-8").strip()
                if version:
                    return version
        except OSError:
            continue
    return default


def normalize_version_channel(value, default=DEFAULT_VERSION_CHANNEL):
    raw = str(value or "").strip().lower()
    if raw in {"beta", "development", "dev", "local", "testing"}:
        return CHANNEL_BETA
    if raw in {"stable", "release", "public", "production"}:
        return CHANNEL_STABLE
    return default


def read_version_channel(default=DEFAULT_VERSION_CHANNEL):
    for path in _candidate_channel_files():
        try:
            if path.exists():
                channel = normalize_version_channel(path.read_text(encoding="utf-8").strip(), default="")
                if channel:
                    return channel
        except OSError:
            continue
    return normalize_version_channel(default)


def parse_version(value):
    raw = str(value or "").strip().lstrip("vV")
    core = raw.split("+", 1)[0].split("-", 1)[0]
    parts = []
    for piece in core.split("."):
        match = re.match(r"^(\d+)", piece)
        parts.append(int(match.group(1)) if match else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def windows_version_info(value):
    parts = list(parse_version(value))
    while len(parts) < 4:
        parts.append(0)
    return ".".join(str(part) for part in parts[:4])


def version_label(version, channel):
    version = str(version or DEFAULT_APP_VERSION).strip()
    channel = normalize_version_channel(channel)
    if channel == CHANNEL_BETA:
        return f"{version} Beta"
    return version


def artifact_version_tag(version, channel):
    version = str(version or DEFAULT_APP_VERSION).strip()
    channel = normalize_version_channel(channel)
    if channel == CHANNEL_BETA:
        return f"{version}_Beta"
    return version


def source_version_tag(version, channel):
    version = str(version or DEFAULT_APP_VERSION).strip()
    channel = normalize_version_channel(channel)
    if channel == CHANNEL_BETA:
        return f"{version}-Beta"
    return version


APP_VERSION = read_app_version()
APP_VERSION_CHANNEL = read_version_channel()
APP_VERSION_CHANNEL_NAME = "Beta" if APP_VERSION_CHANNEL == CHANNEL_BETA else "Stable"
APP_VERSION_LABEL = version_label(APP_VERSION, APP_VERSION_CHANNEL)
APP_ARTIFACT_VERSION_TAG = artifact_version_tag(APP_VERSION, APP_VERSION_CHANNEL)
APP_SOURCE_VERSION_TAG = source_version_tag(APP_VERSION, APP_VERSION_CHANNEL)
APP_VERSION_INFO = windows_version_info(APP_VERSION)

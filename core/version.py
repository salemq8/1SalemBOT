import re
import sys
from pathlib import Path


DEFAULT_APP_VERSION = "0.0.0"
VERSION_FILE_NAME = "VERSION"


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


APP_VERSION = read_app_version()
APP_VERSION_INFO = windows_version_info(APP_VERSION)

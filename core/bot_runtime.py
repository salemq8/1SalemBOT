import os
import subprocess
from datetime import datetime

from .app_paths import ALERT_RUNTIME_FILE, BOT_RUNTIME_FILE
from .app_state import load_json, save_json


def _normalize_runtime_state(data):
    if not isinstance(data, dict):
        data = {}
    pid = data.get("pid")
    try:
        pid = int(pid)
    except Exception:
        pid = 0
    return {
        "pid": pid,
        "started_at": str(data.get("started_at", "") or ""),
        "command": str(data.get("command", "") or ""),
        "entrypoint": str(data.get("entrypoint", "") or ""),
    }


def read_runtime_state(runtime_file):
    return _normalize_runtime_state(load_json(runtime_file, {}))


def read_bot_runtime_state():
    return read_runtime_state(BOT_RUNTIME_FILE)


def read_alert_runtime_state():
    return read_runtime_state(ALERT_RUNTIME_FILE)


def is_process_running(pid):
    try:
        pid = int(pid)
    except Exception:
        return False
    if pid <= 0:
        return False

    if os.name == "nt":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False

    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def get_active_runtime_state(runtime_file, clear_callback):
    state = read_runtime_state(runtime_file)
    if state["pid"] and is_process_running(state["pid"]):
        return state
    clear_callback()
    return _normalize_runtime_state({})


def get_active_bot_runtime_state():
    return get_active_runtime_state(BOT_RUNTIME_FILE, clear_bot_runtime_state)


def get_active_alert_runtime_state():
    return get_active_runtime_state(ALERT_RUNTIME_FILE, clear_alert_runtime_state)


def write_runtime_state(runtime_file, pid, command="", entrypoint="main.py"):
    save_json(
        runtime_file,
        {
            "pid": int(pid),
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "command": str(command or ""),
            "entrypoint": str(entrypoint or "main.py"),
        },
    )


def write_bot_runtime_state(pid, command="", entrypoint="main.py"):
    write_runtime_state(BOT_RUNTIME_FILE, pid, command, entrypoint)


def write_alert_runtime_state(pid, command="", entrypoint="main.py"):
    write_runtime_state(ALERT_RUNTIME_FILE, pid, command, entrypoint)


def clear_runtime_state(runtime_file, read_callback, pid=None):
    if not runtime_file.exists():
        return

    if pid is not None:
        state = read_callback()
        if state["pid"] and int(state["pid"]) != int(pid):
            return

    try:
        runtime_file.unlink()
    except Exception:
        pass


def clear_bot_runtime_state(pid=None):
    clear_runtime_state(BOT_RUNTIME_FILE, read_bot_runtime_state, pid)


def clear_alert_runtime_state(pid=None):
    clear_runtime_state(ALERT_RUNTIME_FILE, read_alert_runtime_state, pid)


def terminate_bot_process(pid):
    try:
        pid = int(pid)
    except Exception:
        return False
    if pid <= 0:
        return False

    try:
        if os.name == "nt":
            completed = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return completed.returncode == 0

        os.kill(pid, 15)
        return True
    except Exception:
        return False

from datetime import datetime

from .app_state import save_json


PLAY_PREFIXES = (
    "!play ",
    "play ",
    "شغل ",
    "شغّل ",
)
SKIP_COMMANDS = {
    "!skip",
    "skip",
    "تخطي",
    "تخطى",
    "سكب",
}
STOP_COMMANDS = {
    "!stop",
    "stop",
    "stop music",
    "وقف",
    "وقف الموسيقى",
    "وقف الاغاني",
    "وقف الأغاني",
}


def parse_music_command(text):
    stripped = (text or "").strip()
    lowered = stripped.lower()

    for prefix in PLAY_PREFIXES:
        if lowered.startswith(prefix):
            return "play", stripped[len(prefix) :].strip()

    if lowered in SKIP_COMMANDS:
        return "skip", ""

    if lowered in STOP_COMMANDS:
        return "stop", ""

    return None, ""


def write_music_command(path, action, query="", source="chat", requested_by="", raw_text=""):
    save_json(
        path,
        {
            "action": action,
            "query": query,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "source": source,
            "requested_by": requested_by,
            "raw_text": raw_text,
        },
    )

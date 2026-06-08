import re
from datetime import datetime

from .app_state import save_json


PLAY_COMMANDS = (
    "!play",
    "!songrequest",
    "!sr",
    "!request",
    "!music",
    "!شغل",
    "!شغّل",
    "!اغنية",
    "!أغنية",
)
SKIP_COMMANDS = {
    "!skip",
    "!next",
    "!تخطي",
    "!تخطى",
    "!سكب",
}
STOP_COMMANDS = {
    "!stop",
    "!stopmusic",
    "!stop music",
    "!وقف",
    "!وقف الموسيقى",
    "!وقف الاغاني",
    "!وقف الأغاني",
}
LEGACY_IMPLICIT_PLAY_PREFIXES = (
    "play ",
    "شغل ",
    "شغّل ",
)
LEGACY_IMPLICIT_COMMANDS = {
    "skip",
    "stop",
    "stop music",
    "تخطي",
    "تخطى",
    "سكب",
    "وقف",
    "وقف الموسيقى",
    "وقف الاغاني",
    "وقف الأغاني",
}
ARABIC_NATURAL_PLAY_WORDS = (
    "شغل",
    "شغّل",
)
ARABIC_SONG_NOUNS = (
    "اغنية",
    "أغنية",
    "اغنيه",
    "أغنيه",
)


def _normalize_command_alias(value):
    alias = str(value or "").strip().lower()
    if not alias:
        return ""
    if not alias.startswith("!"):
        alias = f"!{alias}"
    return " ".join(alias.split())


def _normalized_exact_commands(commands):
    return {_normalize_command_alias(command) for command in commands if _normalize_command_alias(command)}


def _play_aliases(extra_play_commands=None):
    aliases = []
    seen = set()
    for command in [*PLAY_COMMANDS, *(extra_play_commands or ())]:
        alias = _normalize_command_alias(command)
        if alias and alias not in seen:
            seen.add(alias)
            aliases.append(alias)
    return sorted(aliases, key=len, reverse=True)


def _match_command_with_query(text, aliases):
    for alias in aliases:
        match = re.match(rf"^{re.escape(alias)}(?:\s+(.*))?$", text, flags=re.IGNORECASE)
        if match:
            return (match.group(1) or "").strip()
    return None


def looks_like_implicit_music_text(text):
    stripped = (text or "").strip()
    lowered = stripped.lower()
    compact = " ".join(lowered.split())

    if any(lowered.startswith(prefix) for prefix in LEGACY_IMPLICIT_PLAY_PREFIXES):
        return True
    return compact in LEGACY_IMPLICIT_COMMANDS


def parse_music_command(text, extra_play_commands=None):
    stripped = (text or "").strip()
    if not stripped:
        return None, ""

    play_query = _match_command_with_query(stripped, _play_aliases(extra_play_commands))
    if play_query is not None:
        return "play", play_query

    normalized_text = " ".join(stripped.lower().split())
    if normalized_text in _normalized_exact_commands(SKIP_COMMANDS):
        return "skip", ""

    if normalized_text in _normalized_exact_commands(STOP_COMMANDS):
        return "stop", ""

    return None, ""


def parse_bot_addressed_music_request(text):
    stripped = (text or "").strip()
    lowered = stripped.lower()

    for verb in ARABIC_NATURAL_PLAY_WORDS:
        if lowered == verb:
            return "play", ""
        if not lowered.startswith(f"{verb} "):
            continue

        query = stripped[len(verb) :].strip()
        query_lowered = query.lower()
        for noun in sorted(ARABIC_SONG_NOUNS, key=len, reverse=True):
            if query_lowered == noun:
                return "play", ""
            if query_lowered.startswith(f"{noun} "):
                query = query[len(noun) :].strip()
                break

        if query:
            return "play", query
        return "play", ""

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

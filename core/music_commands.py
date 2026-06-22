import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from .app_state import save_json

DEFAULT_VOLUME_STEP = 10

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


@dataclass(frozen=True)
class MusicCommandIntent:
    action: str = "none"
    value: object = None
    raw_text: str = ""
    is_natural_language: bool = False
    requires_permission: bool = False
    confidence: float = 0.0

    def to_music_command(self):
        if self.action == "queue":
            return "queue", ""
        if self.action == "skip":
            return "skip", ""
        if self.action == "stop":
            return "stop", ""
        if self.action == "remove":
            return "remove", str(self.value or "")
        if self.action == "volume_set":
            return "volume", str(self.value or "")
        if self.action == "volume_up":
            step = int(self.value or DEFAULT_VOLUME_STEP)
            return "volume", f"+{step}"
        if self.action == "volume_down":
            step = int(self.value or DEFAULT_VOLUME_STEP)
            return "volume", f"-{step}"
        if self.action == "play":
            return "play", str(self.value or "")
        return None, ""


def _requires_permission(action):
    return action in {"skip", "stop", "volume_set", "volume_up", "volume_down", "remove"}


def _normalize_command_alias(value):
    alias = str(value or "").strip().lower()
    if not alias:
        return ""
    if not alias.startswith("!"):
        alias = f"!{alias}"
    return " ".join(alias.split())


def _normalized_exact_commands(commands):
    return {_normalize_command_alias(command) for command in commands if _normalize_command_alias(command)}


def _mojibake_alias(value):
    try:
        return str(value).encode("utf-8").decode("latin-1")
    except Exception:
        return str(value)


def _aliases(*values):
    aliases = []
    seen = set()
    for value in values:
        for alias in (str(value or ""), _mojibake_alias(value)):
            normalized = _normalize_command_alias(alias)
            if normalized and normalized not in seen:
                seen.add(normalized)
                aliases.append(normalized)
    return tuple(aliases)


_ARABIC_DIGIT_TRANSLATION = str.maketrans(
    {
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
    }
)

_ARABIC_LETTER_TRANSLATION = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ئ": "ي",
        "ؤ": "و",
        "ة": "ه",
        "ـ": "",
    }
)


def _normalize_number_text(value):
    return str(value or "").translate(_ARABIC_DIGIT_TRANSLATION).strip()


def _strip_diacritics(value):
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _normalize_natural_text(value):
    normalized = _normalize_number_text(value).lower()
    normalized = _strip_diacritics(normalized).translate(_ARABIC_LETTER_TRANSLATION)
    normalized = re.sub(r"[^\w\s+\-@]", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def _natural_aliases(*values):
    aliases = set()
    for value in values:
        for alias in (str(value or ""), _mojibake_alias(value)):
            normalized = _normalize_natural_text(alias)
            if normalized:
                aliases.add(normalized)
    return aliases


def _contains_phrase(text, phrases):
    padded = f" {text} "
    for phrase in phrases:
        if not phrase:
            continue
        if text == phrase or padded.find(f" {phrase} ") >= 0 or phrase in text:
            return True
    return False


def _starts_with_phrase(text, phrases):
    return any(text == phrase or text.startswith(f"{phrase} ") for phrase in phrases if phrase)


def _extract_int(value):
    normalized = _normalize_number_text(value)
    match = re.search(r"([+-])?\s*(\d{1,3})", normalized)
    if not match:
        return None, ""
    sign = match.group(1) or ""
    number = int(match.group(2))
    return number, sign


def _make_intent(action, raw_text, value=None, *, natural=False, confidence=1.0):
    return MusicCommandIntent(
        action=action,
        value=value,
        raw_text=str(raw_text or ""),
        is_natural_language=natural,
        requires_permission=_requires_permission(action),
        confidence=confidence,
    )


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


SKIP_COMMANDS.update(_aliases("!سكيب", "!تخطي"))
QUEUE_COMMANDS = {
    "!queue",
    "!q",
    "!playlist",
    *_aliases("!القائمة", "!الطابور"),
}
VOLUME_COMMANDS = {
    "!volume",
    "!vol",
    *_aliases("!صوت", "!الصوت"),
}
VOLUME_UP_COMMANDS = {
    *_aliases("!رفع الصوت"),
}
VOLUME_DOWN_COMMANDS = {
    *_aliases("!خفض الصوت"),
}
REMOVE_COMMANDS = {
    "!remove",
    "!rm",
    *_aliases("!حذف", "!شيل"),
}

NATURAL_SKIP_WORDS = _natural_aliases("skip", "next", "skip song", "سكيب", "سكب", "تخطي", "تخطى", "طوف")
NATURAL_QUEUE_WORDS = _natural_aliases(
    "queue",
    "list",
    "playlist",
    "قائمة",
    "القائمة",
    "بالقائمة",
    "طابور",
    "الطابور",
    "بالطابور",
    "ليستة",
    "اللستة",
    "بالليستة",
    "باللستة",
    "باقي",
    "اغاني",
    "الأغاني",
    "بالأغاني",
)
NATURAL_QUEUE_CUES = _natural_aliases("شنو", "وش", "عرض", "show", "what", "queue")
NATURAL_VOLUME_WORDS = _natural_aliases("volume", "vol", "sound", "صوت", "الصوت")
NATURAL_VOLUME_SET_WORDS = _natural_aliases("خلي", "خل", "حط", "حطلي", "set", "make")
NATURAL_VOLUME_UP_WORDS = _natural_aliases("علي", "علّي", "اعلي", "ارفع", "رفع", "زيد", "زود", "ولع", "up", "raise", "increase", "louder")
NATURAL_VOLUME_DOWN_WORDS = _natural_aliases("قصر", "قصّر", "خفض", "نزل", "وطي", "وطّي", "وطى", "down", "lower", "decrease", "quieter")
NATURAL_REMOVE_WORDS = _natural_aliases("remove", "rm", "delete", "شيل", "حذف", "امسح", "مسح")


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
    if normalized_text in _normalized_exact_commands(QUEUE_COMMANDS):
        return "queue", ""

    volume_query = _match_command_with_query(stripped, _normalized_exact_commands(VOLUME_COMMANDS))
    if volume_query is not None:
        return "volume", volume_query

    if normalized_text in _normalized_exact_commands(VOLUME_UP_COMMANDS):
        return "volume", "+10"

    if normalized_text in _normalized_exact_commands(VOLUME_DOWN_COMMANDS):
        return "volume", "-10"

    remove_query = _match_command_with_query(stripped, _normalized_exact_commands(REMOVE_COMMANDS))
    if remove_query is not None:
        return "remove", remove_query

    if normalized_text in _normalized_exact_commands(SKIP_COMMANDS):
        return "skip", ""

    if normalized_text in _normalized_exact_commands(STOP_COMMANDS):
        return "stop", ""

    return None, ""


def parse_music_intent(text, extra_play_commands=None):
    action, query = parse_music_command(text, extra_play_commands=extra_play_commands)
    if not action:
        return _make_intent("none", text, confidence=0.0)

    normalized_query = _normalize_number_text(query)
    if action == "volume":
        number, sign = _extract_int(normalized_query)
        if number is None:
            return _make_intent("volume_set", text, value=None, confidence=0.5)
        if sign == "+":
            return _make_intent("volume_up", text, value=number)
        if sign == "-":
            return _make_intent("volume_down", text, value=number)
        return _make_intent("volume_set", text, value=number)

    if action == "remove":
        number, _ = _extract_int(normalized_query)
        return _make_intent("remove", text, value=number)

    if action == "play":
        return _make_intent("play", text, value=query)

    return _make_intent(action, text)


def parse_natural_music_command(text):
    raw_text = str(text or "")
    normalized = _normalize_natural_text(raw_text)
    if not normalized:
        return _make_intent("none", raw_text, natural=True, confidence=0.0)

    has_volume_word = _contains_phrase(normalized, NATURAL_VOLUME_WORDS)
    number, sign = _extract_int(normalized)

    if _starts_with_phrase(normalized, _natural_aliases("volume", "vol")) and number is not None:
        if sign == "+":
            return _make_intent("volume_up", raw_text, value=number, natural=True)
        if sign == "-":
            return _make_intent("volume_down", raw_text, value=number, natural=True)
        return _make_intent("volume_set", raw_text, value=number, natural=True)

    if has_volume_word and _contains_phrase(normalized, NATURAL_VOLUME_UP_WORDS):
        return _make_intent("volume_up", raw_text, value=number or DEFAULT_VOLUME_STEP, natural=True)

    if has_volume_word and _contains_phrase(normalized, NATURAL_VOLUME_DOWN_WORDS):
        return _make_intent("volume_down", raw_text, value=number or DEFAULT_VOLUME_STEP, natural=True)

    if has_volume_word and number is not None:
        starts_with_volume = _starts_with_phrase(normalized, NATURAL_VOLUME_WORDS)
        has_set_word = _contains_phrase(normalized, NATURAL_VOLUME_SET_WORDS)
        if starts_with_volume or has_set_word:
            return _make_intent("volume_set", raw_text, value=number, natural=True)

    if _contains_phrase(normalized, NATURAL_REMOVE_WORDS) and number is not None:
        return _make_intent("remove", raw_text, value=number, natural=True)

    if _contains_phrase(normalized, NATURAL_QUEUE_WORDS):
        if _contains_phrase(normalized, NATURAL_QUEUE_CUES) or _starts_with_phrase(normalized, _natural_aliases("queue", "list", "playlist")):
            return _make_intent("queue", raw_text, natural=True)

    if _contains_phrase(normalized, NATURAL_SKIP_WORDS):
        return _make_intent("skip", raw_text, natural=True)

    return _make_intent("none", raw_text, natural=True, confidence=0.0)


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


def write_music_command(path, action, query="", source="chat", requested_by="", raw_text="", metadata=None):
    save_json(
        path,
        {
            "action": action,
            "query": query,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "source": source,
            "requested_by": requested_by,
            "raw_text": raw_text,
            "metadata": metadata or {},
        },
    )

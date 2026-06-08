import re


HEBREW_TEXT_PATTERN = re.compile(r"[\u0590-\u05ff]")
BLOCKED_MUSIC_KEYWORDS = (
    "israel",
    "israeli",
    "hebrew",
    "עברית",
    "ישראל",
    "שיר",
    "מוזיקה",
)


def _metadata_text(*values):
    return " ".join(str(value or "") for value in values).strip()


def has_blocked_music_text(*values):
    text = _metadata_text(*values)
    if not text:
        return False
    if HEBREW_TEXT_PATTERN.search(text):
        return True

    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in BLOCKED_MUSIC_KEYWORDS)


def is_track_blocked_by_policy(title="", channel="", playlist_title=""):
    return has_blocked_music_text(title, channel, playlist_title)


def music_policy_block_message():
    return "Track blocked by content policy."

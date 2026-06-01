import re


MENTION_REPLY = "هلا والله"
AI_ERROR_REPLY = "المعذرة، صار عندي لخبطة بسيطة الحين"

MUSIC_DISABLED_REPLY = "المعذرة، حاليًا صاحب البث ما يبي أغاني تشتغل"
MUSIC_QUEUED_REPLY = "تم، أضفت طلبك وشغال عليه"
MUSIC_NEEDS_QUERY_REPLY = "اكتب اسم الأغنية أو أرسل الرابط"
MUSIC_SKIPPED_REPLY = "تم، سحبت الأغنية الحالية"
MUSIC_STOPPED_REPLY = "تم، وقفت الموسيقى"


def mention_user(username: str, message: str) -> str:
    clean_username = str(username or "").strip().lstrip("@")
    clean_message = re.sub(r"\s+", " ", str(message or "").strip())
    if not clean_username:
        return clean_message

    mention = f"@{clean_username}"
    clean_message = re.sub(
        rf"^(?:{re.escape(mention)}\s+)+",
        "",
        clean_message,
        flags=re.IGNORECASE,
    ).strip()
    return f"{mention} {clean_message}".strip()

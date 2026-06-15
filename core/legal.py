from datetime import datetime, timezone

from .app_paths import PRIVACY_FILE, SETTINGS_FILE, TERMS_FILE
from .app_state import load_json, save_json


TERMS_VERSION = "1.0"
PRIVACY_VERSION = "1.0"

ACCEPTANCE_FIELDS = {
    "terms_version",
    "privacy_version",
    "accepted_terms",
    "accepted_privacy",
    "accepted_at",
}


def utc_timestamp():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def legal_acceptance_current(settings, *, terms_version=TERMS_VERSION, privacy_version=PRIVACY_VERSION):
    safe_settings = settings if isinstance(settings, dict) else {}
    return (
        bool(safe_settings.get("accepted_terms"))
        and bool(safe_settings.get("accepted_privacy"))
        and str(safe_settings.get("terms_version") or "") == str(terms_version)
        and str(safe_settings.get("privacy_version") or "") == str(privacy_version)
    )


def build_acceptance_record(*, accepted_at=None, terms_version=TERMS_VERSION, privacy_version=PRIVACY_VERSION):
    return {
        "terms_version": str(terms_version),
        "privacy_version": str(privacy_version),
        "accepted_terms": True,
        "accepted_privacy": True,
        "accepted_at": accepted_at or utc_timestamp(),
    }


def save_legal_acceptance(settings_file=SETTINGS_FILE, *, accepted_at=None):
    settings = load_json(settings_file, {})
    if not isinstance(settings, dict):
        settings = {}
    settings.update(build_acceptance_record(accepted_at=accepted_at))
    save_json(settings_file, settings)
    return settings


def read_legal_document(path, fallback_text=""):
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")
    except Exception:
        pass
    return fallback_text


def read_terms_text():
    return read_legal_document(TERMS_FILE, "1SalemBOT Terms of Use\n\nVersion: 1.0")


def read_privacy_text():
    return read_legal_document(PRIVACY_FILE, "1SalemBOT Privacy Policy\n\nVersion: 1.0")

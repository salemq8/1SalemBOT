from dataclasses import dataclass, field
from datetime import datetime

from .version import APP_VERSION, parse_version


DEFAULT_UPDATE_PROVIDER = "github"
DEFAULT_RELEASE_CHANNEL = "stable"
DEFAULT_UPDATE_URL = ""


@dataclass(frozen=True)
class UpdateAsset:
    name: str = ""
    download_url: str = ""
    size: int = 0
    content_type: str = ""

    @classmethod
    def from_json(cls, data):
        if not isinstance(data, dict):
            return cls()
        return cls(
            name=str(data.get("name") or "").strip(),
            download_url=str(data.get("browser_download_url") or data.get("download_url") or "").strip(),
            size=int(data.get("size") or 0),
            content_type=str(data.get("content_type") or "").strip(),
        )


@dataclass(frozen=True)
class UpdateRelease:
    version: str = ""
    title: str = ""
    notes: str = ""
    published_at: str = ""
    release_url: str = ""
    prerelease: bool = False
    draft: bool = False
    assets: tuple = field(default_factory=tuple)

    @property
    def installer_asset(self):
        return find_asset(self.assets, ("setup", "installer"), ".exe")

    @property
    def portable_asset(self):
        return find_asset(self.assets, ("portable",), ".zip")

    @property
    def notes_lines(self):
        return parse_release_notes(self.notes)


@dataclass(frozen=True)
class UpdateConfig:
    update_provider: str = DEFAULT_UPDATE_PROVIDER
    current_version: str = APP_VERSION
    release_channel: str = DEFAULT_RELEASE_CHANNEL
    update_url: str = DEFAULT_UPDATE_URL
    enabled: bool = False
    auto_update_enabled: bool = False

    def to_dict(self):
        return {
            "update_provider": self.update_provider,
            "current_version": self.current_version,
            "release_channel": self.release_channel,
            "update_url": self.update_url,
            "enabled": self.enabled,
            "auto_update_enabled": self.auto_update_enabled,
        }


def default_update_config():
    return UpdateConfig()


def build_update_config(settings=None):
    settings = settings or {}
    update_settings = settings.get("updates") if isinstance(settings.get("updates"), dict) else {}
    return UpdateConfig(
        update_provider=str(update_settings.get("update_provider") or DEFAULT_UPDATE_PROVIDER).strip() or DEFAULT_UPDATE_PROVIDER,
        current_version=APP_VERSION,
        release_channel=str(update_settings.get("release_channel") or DEFAULT_RELEASE_CHANNEL).strip() or DEFAULT_RELEASE_CHANNEL,
        update_url=str(update_settings.get("update_url") or DEFAULT_UPDATE_URL).strip(),
        enabled=bool(update_settings.get("enabled", False)),
        auto_update_enabled=bool(update_settings.get("auto_update_enabled", False)),
    )


def compare_versions(current_version, candidate_version):
    current = parse_version(current_version)
    candidate = parse_version(candidate_version)
    if candidate > current:
        return 1
    if candidate < current:
        return -1
    return 0


def is_newer_version(current_version, candidate_version):
    return compare_versions(current_version, candidate_version) > 0


def normalize_release_version(value):
    version = str(value or "").strip()
    if version.lower().startswith("release "):
        version = version[8:].strip()
    return version.lstrip("vV").strip()


def parse_release_notes(notes):
    lines = []
    for line in str(notes or "").splitlines():
        cleaned = line.strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def parse_release_datetime(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def find_asset(assets, keywords=(), extension=""):
    extension = str(extension or "").lower()
    lowered_keywords = tuple(str(keyword).lower() for keyword in keywords)
    for asset in assets or ():
        if not isinstance(asset, UpdateAsset):
            continue
        name = asset.name.lower()
        if extension and not name.endswith(extension):
            continue
        if lowered_keywords and not any(keyword in name for keyword in lowered_keywords):
            continue
        return asset
    return None


def parse_github_release_json(payload):
    if not isinstance(payload, dict):
        return UpdateRelease()
    assets = tuple(
        asset
        for asset in (UpdateAsset.from_json(item) for item in payload.get("assets") or [])
        if asset.name
    )
    return UpdateRelease(
        version=normalize_release_version(payload.get("tag_name") or payload.get("name")),
        title=str(payload.get("name") or payload.get("tag_name") or "").strip(),
        notes=str(payload.get("body") or "").strip(),
        published_at=str(payload.get("published_at") or "").strip(),
        release_url=str(payload.get("html_url") or "").strip(),
        prerelease=bool(payload.get("prerelease", False)),
        draft=bool(payload.get("draft", False)),
        assets=assets,
    )


class UpdateManager:
    def __init__(self, config=None):
        self.config = config or default_update_config()

    @classmethod
    def from_settings(cls, settings=None):
        return cls(build_update_config(settings))

    def parse_release(self, payload):
        if self.config.update_provider == "github":
            return parse_github_release_json(payload)
        return UpdateRelease()

    def release_is_applicable(self, release):
        if not isinstance(release, UpdateRelease):
            return False
        if release.draft:
            return False
        if release.prerelease and self.config.release_channel != "preview":
            return False
        return bool(release.version)

    def evaluate_release(self, payload):
        release = self.parse_release(payload)
        return {
            "release": release,
            "applicable": self.release_is_applicable(release),
            "is_newer": is_newer_version(self.config.current_version, release.version),
            "installer_asset": release.installer_asset,
            "portable_asset": release.portable_asset,
            "notes": release.notes_lines,
        }

    def check_for_updates(self):
        return {
            "enabled": False,
            "reason": "Update checks are prepared but not enabled yet.",
            "config": self.config.to_dict(),
        }

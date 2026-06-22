import hashlib
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .version import APP_VERSION, APP_VERSION_CHANNEL, CHANNEL_BETA, CHANNEL_STABLE, parse_version


DEFAULT_UPDATE_PROVIDER = "github"
CHANNEL_PREVIEW = "preview"
DEFAULT_RELEASE_CHANNEL = CHANNEL_PREVIEW if APP_VERSION_CHANNEL == CHANNEL_BETA else CHANNEL_STABLE
DEFAULT_UPDATE_URL = "https://github.com/salemq8/1SalemBOT/releases/latest/download/version.json"
LEGACY_UPDATE_URLS = {
    "https://github.com/1SalemQ8/1SalemBOT/releases/latest/download/version.json",
}
DEFAULT_REQUEST_TIMEOUT = 20
DEFAULT_CHUNK_SIZE = 1024 * 128
DEFAULT_INSTALLER_SILENT_ARGS = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")


class UpdateError(Exception):
    pass


class UpdateCancelled(UpdateError):
    pass


@dataclass(frozen=True)
class UpdateAsset:
    name: str = ""
    download_url: str = ""
    size: int = 0
    content_type: str = ""
    sha256: str = ""
    silent_args: tuple = field(default_factory=tuple)
    supports_silent: bool = True

    @classmethod
    def from_json(cls, data):
        if not isinstance(data, dict):
            return cls()
        silent_args = data.get("silent_args") or data.get("installer_args") or data.get("args") or ()
        if isinstance(silent_args, str):
            silent_args = tuple(part for part in silent_args.split(" ") if part)
        elif isinstance(silent_args, (list, tuple)):
            silent_args = tuple(str(part).strip() for part in silent_args if str(part).strip())
        else:
            silent_args = ()

        download_url = str(
            data.get("browser_download_url")
            or data.get("download_url")
            or data.get("url")
            or ""
        ).strip()
        name = str(data.get("name") or Path(urllib.parse.urlparse(download_url).path).name or "").strip()
        return cls(
            name=name,
            download_url=download_url,
            size=int(data.get("size") or 0),
            content_type=str(data.get("content_type") or "").strip(),
            sha256=str(data.get("sha256") or data.get("checksum_sha256") or "").strip().lower(),
            silent_args=silent_args,
            supports_silent=bool(data.get("supports_silent", data.get("silent", True))),
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
    channel: str = CHANNEL_STABLE
    assets: tuple = field(default_factory=tuple)

    @property
    def installer_asset(self):
        explicit = find_asset(self.assets, ("installer", "setup"), ".exe")
        if explicit:
            return explicit
        return find_asset(self.assets, (), ".exe")

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
    enabled: bool = True
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


def normalize_update_channel(value, default=None):
    default_channel = DEFAULT_RELEASE_CHANNEL if default is None else default
    channel = str(value or default_channel).strip().lower()
    if channel in {"beta", "preview", "prerelease"}:
        return CHANNEL_PREVIEW
    if channel in {"stable", "release", "public"}:
        return CHANNEL_STABLE
    return default_channel


def build_update_config(settings=None):
    settings = settings or {}
    update_settings = settings.get("updates") if isinstance(settings.get("updates"), dict) else {}
    configured_update_url = str(update_settings.get("update_url") or "").strip()
    if not configured_update_url or configured_update_url in LEGACY_UPDATE_URLS:
        configured_update_url = DEFAULT_UPDATE_URL
    return UpdateConfig(
        update_provider=str(update_settings.get("update_provider") or DEFAULT_UPDATE_PROVIDER).strip() or DEFAULT_UPDATE_PROVIDER,
        current_version=APP_VERSION,
        release_channel=normalize_update_channel(update_settings.get("release_channel")),
        update_url=configured_update_url,
        enabled=bool(update_settings.get("enabled", True)),
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
    if isinstance(notes, (list, tuple)):
        return [str(line).strip() for line in notes if str(line).strip()]
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


def _notes_to_text(value):
    if isinstance(value, (list, tuple)):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _asset_from_url(url, *, name="", sha256="", size=0, silent_args=(), supports_silent=True):
    url = str(url or "").strip()
    if not url:
        return None
    return UpdateAsset(
        name=str(name or Path(urllib.parse.urlparse(url).path).name or "1SalemBOT_Setup.exe").strip(),
        download_url=url,
        size=int(size or 0),
        sha256=str(sha256 or "").strip().lower(),
        silent_args=tuple(silent_args or ()),
        supports_silent=bool(supports_silent),
    )


def parse_version_json(payload):
    if not isinstance(payload, dict):
        return UpdateRelease()

    raw_assets = []
    for key in ("assets", "files"):
        if isinstance(payload.get(key), list):
            raw_assets.extend(payload.get(key))

    installer_data = (
        payload.get("installer")
        or payload.get("windows_installer")
        or payload.get("windows")
        or {}
    )
    if isinstance(installer_data, str):
        installer_data = {"url": installer_data}
    if isinstance(installer_data, dict):
        installer_asset = UpdateAsset.from_json(installer_data)
        if installer_asset.download_url:
            raw_assets.append(installer_data)

    silent_args = payload.get("silent_args") or payload.get("installer_args") or ()
    if isinstance(silent_args, str):
        silent_args = tuple(part for part in silent_args.split(" ") if part)
    elif isinstance(silent_args, (list, tuple)):
        silent_args = tuple(str(part).strip() for part in silent_args if str(part).strip())
    else:
        silent_args = ()

    installer_url = (
        payload.get("installer_url")
        or payload.get("windows_installer_url")
        or payload.get("download_url")
    )
    direct_installer = _asset_from_url(
        installer_url,
        name=payload.get("installer_name") or payload.get("asset_name"),
        sha256=payload.get("installer_sha256") or payload.get("sha256"),
        size=payload.get("installer_size") or payload.get("size") or 0,
        silent_args=silent_args,
        supports_silent=payload.get("supports_silent", payload.get("silent", True)),
    )
    if direct_installer:
        raw_assets.append(direct_installer.__dict__)

    portable_data = payload.get("portable") or {}
    if isinstance(portable_data, str):
        portable_data = {"url": portable_data}
    if isinstance(portable_data, dict) and portable_data.get("url"):
        raw_assets.append(portable_data)

    portable_url = payload.get("portable_url")
    direct_portable = _asset_from_url(
        portable_url,
        name=payload.get("portable_name"),
        sha256=payload.get("portable_sha256"),
        size=payload.get("portable_size") or 0,
        supports_silent=False,
    )
    if direct_portable:
        raw_assets.append(direct_portable.__dict__)

    assets = tuple(
        asset
        for asset in (UpdateAsset.from_json(item) for item in raw_assets)
        if asset.name and asset.download_url
    )
    notes = payload.get("notes") or payload.get("release_notes") or payload.get("body")
    return UpdateRelease(
        version=normalize_release_version(payload.get("version") or payload.get("tag_name") or payload.get("name")),
        title=str(payload.get("title") or payload.get("name") or "").strip(),
        notes=_notes_to_text(notes),
        published_at=str(payload.get("published_at") or payload.get("date") or "").strip(),
        release_url=str(payload.get("release_url") or payload.get("html_url") or "").strip(),
        prerelease=bool(payload.get("prerelease", False)),
        draft=bool(payload.get("draft", False)),
        channel=str(payload.get("channel") or CHANNEL_STABLE).strip() or CHANNEL_STABLE,
        assets=assets,
    )


def parse_github_release_json(payload):
    if not isinstance(payload, dict):
        return UpdateRelease()
    if payload.get("version") or payload.get("installer_url") or payload.get("windows_installer"):
        return parse_version_json(payload)
    assets = tuple(
        asset
        for asset in (UpdateAsset.from_json(item) for item in payload.get("assets") or [])
        if asset.name and asset.download_url
    )
    return UpdateRelease(
        version=normalize_release_version(payload.get("tag_name") or payload.get("name")),
        title=str(payload.get("name") or payload.get("tag_name") or "").strip(),
        notes=str(payload.get("body") or "").strip(),
        published_at=str(payload.get("published_at") or "").strip(),
        release_url=str(payload.get("html_url") or "").strip(),
        prerelease=bool(payload.get("prerelease", False)),
        draft=bool(payload.get("draft", False)),
        channel=DEFAULT_RELEASE_CHANNEL,
        assets=assets,
    )


def _request(url, timeout=DEFAULT_REQUEST_TIMEOUT):
    return urllib.request.Request(
        url,
        headers={
            "Accept": "application/json, application/octet-stream",
            "User-Agent": f"1SalemBOT/{APP_VERSION}",
        },
    )


def _powershell_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


class UpdateManager:
    def __init__(self, config=None):
        self.config = config or default_update_config()

    @classmethod
    def from_settings(cls, settings=None):
        return cls(build_update_config(settings))

    def fetch_remote_version_json(self):
        if not self.config.enabled:
            raise UpdateError("Update checks are disabled.")
        if not self.config.update_url:
            raise UpdateError("Update URL is not configured.")
        try:
            with urllib.request.urlopen(_request(self.config.update_url), timeout=DEFAULT_REQUEST_TIMEOUT) as response:
                raw = response.read()
        except urllib.error.URLError as exc:
            raise UpdateError(f"No internet or GitHub update source unavailable: {exc}") from exc
        except OSError as exc:
            raise UpdateError(f"Failed to reach update source: {exc}") from exc

        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpdateError("Invalid update JSON received from GitHub.") from exc
        if not isinstance(payload, dict):
            raise UpdateError("Invalid update JSON: expected an object.")
        return payload

    def parse_release(self, payload):
        if self.config.update_provider == "github":
            return parse_github_release_json(payload)
        return parse_version_json(payload)

    def release_is_applicable(self, release):
        if not isinstance(release, UpdateRelease):
            return False
        if release.draft:
            return False
        configured_channel = normalize_update_channel(self.config.release_channel)
        release_channel = normalize_update_channel(release.channel or CHANNEL_STABLE, default=CHANNEL_STABLE)
        if configured_channel == CHANNEL_STABLE:
            if release.prerelease:
                return False
            if release_channel != CHANNEL_STABLE:
                return False
        elif configured_channel == CHANNEL_PREVIEW:
            if release_channel not in {CHANNEL_STABLE, CHANNEL_PREVIEW}:
                return False
        else:
            return False
        return bool(release.version)

    def evaluate_release(self, payload):
        release = self.parse_release(payload)
        applicable = self.release_is_applicable(release)
        return {
            "release": release,
            "applicable": applicable,
            "is_newer": applicable and is_newer_version(self.config.current_version, release.version),
            "installer_asset": release.installer_asset,
            "portable_asset": release.portable_asset,
            "notes": release.notes_lines,
        }

    def check_for_updates(self):
        payload = self.fetch_remote_version_json()
        return self.evaluate_release(payload)

    def installer_args(self, asset, *, silent=False):
        if not silent:
            return []
        if asset and asset.supports_silent and asset.silent_args:
            return list(asset.silent_args)
        if asset and asset.supports_silent:
            return list(DEFAULT_INSTALLER_SILENT_ARGS)
        return []

    def download_installer(self, asset, progress_callback=None, cancel_event=None, status_callback=None):
        if not isinstance(asset, UpdateAsset) or not asset.download_url:
            raise UpdateError("No Windows installer asset is available for this update.")
        if not str(asset.sha256 or "").strip():
            raise UpdateError("Installer checksum is required before installing official updates.")
        temp_dir = Path(tempfile.mkdtemp(prefix="1SalemBOT-update-"))
        target_name = asset.name or "1SalemBOT_Setup_Update.exe"
        target_path = temp_dir / target_name
        temp_path = target_dir_safe(temp_dir, target_name + ".download")
        expected_size = int(asset.size or 0)

        try:
            with urllib.request.urlopen(_request(asset.download_url), timeout=DEFAULT_REQUEST_TIMEOUT) as response:
                total = int(response.headers.get("Content-Length") or expected_size or 0)
                downloaded = 0
                sha = hashlib.sha256()
                with open(temp_path, "wb") as output:
                    while True:
                        if cancel_event is not None and cancel_event.is_set():
                            raise UpdateCancelled("Update download cancelled.")
                        chunk = response.read(DEFAULT_CHUNK_SIZE)
                        if not chunk:
                            break
                        output.write(chunk)
                        sha.update(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total)

            if status_callback:
                status_callback("Verifying download...", 100)
            if sha.hexdigest().lower() != asset.sha256:
                raise UpdateError("Downloaded installer checksum did not match version.json.")
            os.replace(temp_path, target_path)
            return str(target_path)
        except UpdateCancelled:
            cleanup_download(temp_path)
            cleanup_download(target_path)
            raise
        except UpdateError:
            cleanup_download(temp_path)
            cleanup_download(target_path)
            raise
        except urllib.error.URLError as exc:
            cleanup_download(temp_path)
            raise UpdateError(f"Installer download failed: {exc}") from exc
        except OSError as exc:
            cleanup_download(temp_path)
            raise UpdateError(f"Installer download failed: {exc}") from exc

    def launch_installer_after_exit(self, installer_path, current_pid, *, silent=False, asset=None):
        installer_path = str(installer_path or "").strip()
        if not installer_path or not Path(installer_path).exists():
            raise UpdateError("Downloaded installer was not found.")
        args = self.installer_args(asset, silent=silent)
        args_literal = "@(" + ",".join(_powershell_quote(arg) for arg in args) + ")"
        script = (
            f"$pidToWait = {int(current_pid)}; "
            f"$installer = {_powershell_quote(installer_path)}; "
            f"$argsList = {args_literal}; "
            "try { Wait-Process -Id $pidToWait -Timeout 90 -ErrorAction SilentlyContinue } catch {}; "
            "Start-Process -FilePath $installer -ArgumentList $argsList"
        )
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-Command",
                script,
            ],
            close_fds=True,
            creationflags=creationflags,
        )
        return args


def target_dir_safe(directory, filename):
    directory = Path(directory).resolve()
    target = (directory / filename).resolve()
    if not str(target).startswith(str(directory)):
        raise UpdateError("Unsafe update download path.")
    return target


def cleanup_download(path):
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass

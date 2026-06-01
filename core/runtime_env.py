import os
import sys
from pathlib import Path

from .app_paths import get_runtime_base_dir


def _certifi_candidates():
    candidates = []

    try:
        import certifi

        certifi_path = certifi.where()
        if certifi_path:
            candidates.append(Path(certifi_path))
    except Exception:
        pass

    runtime_base = get_runtime_base_dir()
    candidates.extend(
        [
            runtime_base / "certifi" / "cacert.pem",
            runtime_base / "_internal" / "certifi" / "cacert.pem",
            Path(sys.executable).resolve().parent / "_internal" / "certifi" / "cacert.pem",
            Path(sys.executable).resolve().parent / "certifi" / "cacert.pem",
        ]
    )

    return candidates


def configure_ssl_cert_env():
    for cert_path in _certifi_candidates():
        if cert_path and cert_path.exists():
            resolved = str(cert_path.resolve())
            os.environ["SSL_CERT_FILE"] = resolved
            os.environ["REQUESTS_CA_BUNDLE"] = resolved
            os.environ["CURL_CA_BUNDLE"] = resolved
            return resolved
    return None


def _qt_plugin_candidates():
    runtime_base = get_runtime_base_dir()
    executable_dir = Path(sys.executable).resolve().parent

    candidates = [
        runtime_base / "_internal" / "PySide6" / "plugins",
        runtime_base / "PySide6" / "plugins",
        executable_dir / "_internal" / "PySide6" / "plugins",
        executable_dir / "PySide6" / "plugins",
    ]

    try:
        import PySide6

        pyside_dir = Path(PySide6.__file__).resolve().parent
        candidates.extend(
            [
                pyside_dir / "plugins",
                pyside_dir / "Qt" / "plugins",
            ]
        )
    except Exception:
        pass

    return candidates


def configure_qt_plugin_env():
    for plugin_root in _qt_plugin_candidates():
        if not plugin_root.exists():
            continue

        os.environ["QT_PLUGIN_PATH"] = str(plugin_root)
        platform_dir = plugin_root / "platforms"
        if platform_dir.exists():
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(platform_dir)
        return str(plugin_root)

    return None

import ctypes
import errno
import json
import os
import shutil
import threading
import time
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path

from .runtime_logging import write_diagnostics_line


CRYPTPROTECT_UI_FORBIDDEN = 0x01
DEFAULT_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)
DEFAULT_LOCK_TIMEOUT_SECONDS = 3.0
STALE_LOCK_SECONDS = 30.0
DIAGNOSTIC_RATE_LIMIT_SECONDS = 30.0

_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS = {}
_DIAGNOSTIC_GUARD = threading.Lock()
_LAST_DIAGNOSTIC_AT = {}


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _blob_from_bytes(data):
    buffer = ctypes.create_string_buffer(data)
    blob = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


def _bytes_from_blob(blob):
    if not blob.pbData or not blob.cbData:
        return b""
    return ctypes.string_at(blob.pbData, blob.cbData)


def _require_windows():
    if os.name != "nt":
        raise RuntimeError("Windows DPAPI secure storage is only available on Windows.")


def dpapi_protect(data: bytes, *, description="1SalemBOT Twitch token") -> bytes:
    _require_windows()
    crypt32 = ctypes.windll.crypt32
    source_blob, source_buffer = _blob_from_bytes(bytes(data or b""))
    protected_blob = DATA_BLOB()
    if not crypt32.CryptProtectData(
        ctypes.byref(source_blob),
        description,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(protected_blob),
    ):
        raise ctypes.WinError()
    try:
        return _bytes_from_blob(protected_blob)
    finally:
        ctypes.windll.kernel32.LocalFree(protected_blob.pbData)
        source_buffer.raw


def dpapi_unprotect(data: bytes) -> bytes:
    _require_windows()
    crypt32 = ctypes.windll.crypt32
    source_blob, source_buffer = _blob_from_bytes(bytes(data or b""))
    unprotected_blob = DATA_BLOB()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(unprotected_blob),
    ):
        raise ctypes.WinError()
    try:
        return _bytes_from_blob(unprotected_blob)
    finally:
        ctypes.windll.kernel32.LocalFree(unprotected_blob.pbData)
        source_buffer.raw


def _path_key(path):
    try:
        resolved = Path(path).expanduser().resolve(strict=False)
    except Exception:
        resolved = Path(path).expanduser().absolute()
    key = str(resolved)
    return key.lower() if os.name == "nt" else key


def _thread_lock_for(path):
    key = _path_key(path)
    with _LOCKS_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[key] = lock
        return lock


def _diagnostic(path, message, *, key=None, force=False):
    filename = Path(path).name
    event_key = key or f"{filename}:{message}"
    now = time.monotonic()
    with _DIAGNOSTIC_GUARD:
        last_at = float(_LAST_DIAGNOSTIC_AT.get(event_key, 0.0) or 0.0)
        if not force and now - last_at < DIAGNOSTIC_RATE_LIMIT_SECONDS:
            return
        _LAST_DIAGNOSTIC_AT[event_key] = now
    write_diagnostics_line(f"[SECURE_STORAGE] {filename} {message}")


def _is_transient_write_error(exc):
    if isinstance(exc, PermissionError):
        return True
    winerror = getattr(exc, "winerror", None)
    if winerror == 5:
        return True
    return getattr(exc, "errno", None) in {errno.EACCES, errno.EPERM}


def _backup_last_valid(path):
    target = Path(path)
    if not target.exists():
        return None
    backup_path = target.with_name(f"{target.name}.last-good.bak")
    try:
        shutil.copy2(target, backup_path)
        return backup_path
    except Exception:
        return None


def _cleanup_stale_lock(lock_path):
    try:
        age = time.time() - Path(lock_path).stat().st_mtime
    except OSError:
        return False
    if age < STALE_LOCK_SECONDS:
        return False
    try:
        Path(lock_path).unlink(missing_ok=True)
        return True
    except OSError:
        return False


@contextmanager
def _process_file_lock(path, timeout=DEFAULT_LOCK_TIMEOUT_SECONDS):
    target = Path(path)
    lock_path = target.with_name(f".{target.name}.lock")
    deadline = time.monotonic() + float(timeout or DEFAULT_LOCK_TIMEOUT_SECONDS)
    fd = None
    delayed = False

    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {time.time():.6f}\n".encode("ascii", errors="ignore"))
            break
        except FileExistsError:
            if _cleanup_stale_lock(lock_path):
                _diagnostic(target, "write removed stale writer lock", key=f"{target.name}:stale-lock")
                continue
            if time.monotonic() >= deadline:
                _diagnostic(target, "write failed waiting for writer lock", key=f"{target.name}:lock-timeout", force=True)
                raise PermissionError(f"Timed out waiting for secure writer lock: {target.name}")
            if not delayed:
                delayed = True
                _diagnostic(target, "write delayed by file lock", key=f"{target.name}:lock-delayed")
            time.sleep(0.05)
        except PermissionError:
            if time.monotonic() >= deadline:
                _diagnostic(target, "write failed opening writer lock", key=f"{target.name}:lock-permission", force=True)
                raise
            if not delayed:
                delayed = True
                _diagnostic(target, "write delayed by file lock", key=f"{target.name}:lock-permission-delayed")
            time.sleep(0.05)

    try:
        yield
    finally:
        try:
            if fd is not None:
                os.close(fd)
        finally:
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass


def _replace_with_retry(temp_path, target_path, retry_delays):
    attempted_retry = False
    delays = list(retry_delays if retry_delays is not None else DEFAULT_RETRY_DELAYS)
    attempts = [0.0] + delays
    last_exc = None

    for index, delay in enumerate(attempts):
        if delay:
            time.sleep(delay)
        try:
            os.replace(temp_path, target_path)
            if attempted_retry:
                _diagnostic(target_path, "write succeeded after retry", key=f"{Path(target_path).name}:retry-success", force=True)
            return True
        except OSError as exc:
            last_exc = exc
            if not _is_transient_write_error(exc) or index >= len(attempts) - 1:
                break
            attempted_retry = True
            _diagnostic(target_path, "write retried after file lock", key=f"{Path(target_path).name}:replace-retry")

    _backup_last_valid(target_path)
    _diagnostic(target_path, "write failed after retries", key=f"{Path(target_path).name}:replace-failed", force=True)
    raise last_exc


def atomic_write_bytes(path: Path, data: bytes, *, retry_delays=DEFAULT_RETRY_DELAYS, lock_timeout=DEFAULT_LOCK_TIMEOUT_SECONDS):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = bytes(data or b"")

    thread_lock = _thread_lock_for(target)
    with thread_lock:
        with _process_file_lock(target, timeout=lock_timeout):
            try:
                if target.exists() and target.read_bytes() == payload:
                    return False
            except Exception:
                pass

            temp_path = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp")
            try:
                with temp_path.open("wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                _replace_with_retry(temp_path, target, retry_delays)
                return True
            finally:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass


def save_encrypted_json(path: Path, payload: dict):
    raw = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return atomic_write_bytes(path, dpapi_protect(raw))


def load_encrypted_json(path: Path):
    source = Path(path)
    if not source.exists():
        return {}
    raw = dpapi_unprotect(source.read_bytes())
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("Encrypted token payload is invalid.") from exc
    return data if isinstance(data, dict) else {}

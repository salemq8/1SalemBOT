import copy
import threading
import time
from contextlib import contextmanager, nullcontext

from .chat_storage import save_dashboard_state, save_user_profiles
from .runtime_logging import write_diagnostics_line


FILE_LABELS = {
    "users": "users.json",
    "dashboard": "dashboard_state.json",
}


class ChatPersistenceManager:
    def __init__(
        self,
        user_profiles,
        dashboard_state,
        *,
        save_users_func=save_user_profiles,
        save_dashboard_func=save_dashboard_state,
        debounce_seconds=1.5,
        max_flush_seconds=5.0,
        poll_seconds=0.25,
        autostart=True,
    ):
        self.user_profiles = user_profiles
        self.dashboard_state = dashboard_state
        self.save_users_func = save_users_func
        self.save_dashboard_func = save_dashboard_func
        self.debounce_seconds = max(0.1, float(debounce_seconds))
        self.max_flush_seconds = max(self.debounce_seconds, float(max_flush_seconds))
        self.poll_seconds = max(0.05, float(poll_seconds))
        self.write_counts = {"users": 0, "dashboard": 0}
        self.write_failures = {"users": 0, "dashboard": 0}
        self.max_save_latency = 0.0

        self._lock = threading.RLock()
        self._dirty = {"users": False, "dashboard": False}
        self._versions = {"users": 0, "dashboard": 0}
        self._first_dirty_at = {"users": 0.0, "dashboard": 0.0}
        self._last_dirty_at = {"users": 0.0, "dashboard": 0.0}
        self._retry_after = {"users": 0.0, "dashboard": 0.0}
        self._stop_event = threading.Event()
        self._thread = None

        if autostart:
            self.start()

    @contextmanager
    def update_lock(self):
        with self._lock:
            yield

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="ChatPersistenceFlush", daemon=True)
        self._thread.start()

    def mark_users_dirty(self):
        self._mark_dirty("users")

    def mark_dashboard_dirty(self):
        self._mark_dirty("dashboard")

    def _mark_dirty(self, name):
        now = time.monotonic()
        with self._lock:
            if not self._dirty[name]:
                self._first_dirty_at[name] = now
            self._dirty[name] = True
            self._last_dirty_at[name] = now
            self._versions[name] += 1

    def _is_due_locked(self, name, now, *, force=False):
        if not self._dirty[name]:
            return False
        if force:
            return True
        if now < self._retry_after[name]:
            return False
        first_dirty_at = self._first_dirty_at[name] or now
        last_dirty_at = self._last_dirty_at[name] or now
        return (now - last_dirty_at) >= self.debounce_seconds or (now - first_dirty_at) >= self.max_flush_seconds

    def _snapshot_due(self, *, force=False):
        now = time.monotonic()
        snapshots = []
        with self._lock:
            if self._is_due_locked("users", now, force=force):
                snapshots.append(("users", self._versions["users"], copy.deepcopy(self.user_profiles)))
            if self._is_due_locked("dashboard", now, force=force):
                snapshots.append(("dashboard", self._versions["dashboard"], copy.deepcopy(self.dashboard_state)))
        return snapshots

    def flush_due(self, *, force=False):
        flushed = {"users": False, "dashboard": False}
        for name, version, snapshot in self._snapshot_due(force=force):
            started_at = time.monotonic()
            try:
                if name == "users":
                    changed = self.save_users_func(snapshot)
                else:
                    changed = self.save_dashboard_func(snapshot)
                elapsed = time.monotonic() - started_at
                self.max_save_latency = max(self.max_save_latency, elapsed)
                if changed is not False:
                    self.write_counts[name] += 1
                with self._lock:
                    if self._versions[name] == version:
                        self._dirty[name] = False
                        self._first_dirty_at[name] = 0.0
                        self._last_dirty_at[name] = 0.0
                        self._retry_after[name] = 0.0
                flushed[name] = True
            except Exception as exc:
                self.write_failures[name] += 1
                with self._lock:
                    self._retry_after[name] = time.monotonic() + 2.0
                write_diagnostics_line(
                    f"[PERSISTENCE] {FILE_LABELS.get(name, name)} save failed after retries: {exc.__class__.__name__}"
                )
        return flushed

    def flush_now(self):
        return self.flush_due(force=True)

    def shutdown(self, timeout=3.0):
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, float(timeout)))
        return self.flush_now()

    def _run(self):
        while not self._stop_event.wait(self.poll_seconds):
            self.flush_due(force=False)


def persistence_update_lock(persistence):
    if persistence is not None and hasattr(persistence, "update_lock"):
        return persistence.update_lock()
    return nullcontext()

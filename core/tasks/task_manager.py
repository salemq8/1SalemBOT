import threading
import traceback
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _TaskSignals(QObject):
    completed = Signal(str, int, object)
    failed = Signal(str, int, str)


@dataclass
class _TaskState:
    generation: int
    cancel_event: threading.Event
    cancelled: bool = False


class _FunctionTask(QRunnable):
    def __init__(self, *, name, generation, fn, cancel_event, signals):
        super().__init__()
        self.name = name
        self.generation = generation
        self.fn = fn
        self.cancel_event = cancel_event
        self.signals = signals
        self.setAutoDelete(True)

    def _emit_completed(self, result):
        try:
            self.signals.completed.emit(self.name, self.generation, result)
            return True
        except RuntimeError as exc:
            if "deleted" in str(exc).lower() or "signal source" in str(exc).lower():
                return False
            raise

    def _emit_failed(self, error_text):
        try:
            self.signals.failed.emit(self.name, self.generation, error_text)
            return True
        except RuntimeError as exc:
            if "deleted" in str(exc).lower() or "signal source" in str(exc).lower():
                return False
            raise

    def run(self):
        if self.cancel_event.is_set():
            self._emit_completed(None)
            return
        try:
            result = self.fn(self.cancel_event)
            self._emit_completed(result)
        except Exception:
            self._emit_failed(traceback.format_exc())


class BackgroundTaskManager(QObject):
    """Small Qt-aware task runner with duplicate prevention and stale-result guards."""

    def __init__(self, parent=None, *, max_thread_count=None):
        super().__init__(parent)
        self.pool = QThreadPool.globalInstance()
        if max_thread_count:
            self.pool.setMaxThreadCount(int(max_thread_count))
        self._signals = _TaskSignals()
        self._signals.completed.connect(self._on_completed)
        self._signals.failed.connect(self._on_failed)
        self._lock = threading.Lock()
        self._tasks = {}
        self._callbacks = {}
        self._generations = {}
        self._shutdown = False

    def start(self, name, fn, *, on_success=None, on_error=None, allow_duplicate=False):
        task_name = str(name or "").strip()
        if not task_name:
            raise ValueError("Task name is required.")
        if not callable(fn):
            raise ValueError("Task function is required.")

        with self._lock:
            if self._shutdown:
                return False
            current = self._tasks.get(task_name)
            if current is not None and not current.cancelled and not allow_duplicate:
                return False
            generation = int(self._generations.get(task_name, 0)) + 1
            self._generations[task_name] = generation
            cancel_event = threading.Event()
            self._tasks[task_name] = _TaskState(generation=generation, cancel_event=cancel_event)
            self._callbacks[task_name] = (on_success, on_error)

        runnable = _FunctionTask(
            name=task_name,
            generation=generation,
            fn=fn,
            cancel_event=cancel_event,
            signals=self._signals,
        )
        self.pool.start(runnable)
        return True

    def is_running(self, name):
        task_name = str(name or "").strip()
        with self._lock:
            state = self._tasks.get(task_name)
            return bool(state is not None and not state.cancelled)

    def cancel(self, name):
        task_name = str(name or "").strip()
        with self._lock:
            state = self._tasks.get(task_name)
            if state is None:
                return False
            state.cancelled = True
            state.cancel_event.set()
            return True

    def cancel_all(self):
        with self._lock:
            names = list(self._tasks.keys())
        for name in names:
            self.cancel(name)

    def shutdown(self):
        with self._lock:
            self._shutdown = True
            names = list(self._tasks.keys())
            self._callbacks.clear()
        for name in names:
            self.cancel(name)

    def _consume(self, name, generation):
        with self._lock:
            state = self._tasks.get(name)
            if state is None or state.generation != generation:
                return None, None, True
            callbacks = self._callbacks.get(name, (None, None))
            cancelled = self._shutdown or state.cancelled or state.cancel_event.is_set()
            self._tasks.pop(name, None)
            self._callbacks.pop(name, None)
            return callbacks[0], callbacks[1], cancelled

    def _on_completed(self, name, generation, result):
        on_success, _on_error, cancelled = self._consume(name, generation)
        if cancelled or not callable(on_success):
            return
        try:
            on_success(result)
        except Exception:
            traceback.print_exc()

    def _on_failed(self, name, generation, error_text):
        _on_success, on_error, cancelled = self._consume(name, generation)
        if cancelled or not callable(on_error):
            return
        try:
            on_error(error_text)
        except Exception:
            traceback.print_exc()

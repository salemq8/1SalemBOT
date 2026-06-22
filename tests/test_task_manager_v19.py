import threading
import time
import unittest

from PySide6.QtWidgets import QApplication

from core.tasks import BackgroundTaskManager
from core.tasks.task_manager import _FunctionTask


def qt_app():
    return QApplication.instance() or QApplication([])


def process_until(predicate, timeout=2.0):
    app = qt_app()
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class BackgroundTaskManagerTests(unittest.TestCase):
    def test_duplicate_task_is_rejected_until_first_finishes(self):
        qt_app()
        manager = BackgroundTaskManager()
        release = threading.Event()
        results = []

        self.assertTrue(manager.start("sync", lambda _cancel: (release.wait(1.0), "done")[1], on_success=results.append))
        self.assertFalse(manager.start("sync", lambda _cancel: "second"))
        release.set()

        self.assertTrue(process_until(lambda: not manager.is_running("sync")))
        self.assertEqual(results, ["done"])

    def test_cancelled_task_does_not_apply_late_result(self):
        qt_app()
        manager = BackgroundTaskManager()
        release = threading.Event()
        results = []

        self.assertTrue(manager.start("refresh", lambda _cancel: (release.wait(1.0), "late")[1], on_success=results.append))
        self.assertTrue(manager.cancel("refresh"))
        release.set()

        self.assertTrue(process_until(lambda: not manager.is_running("refresh")))
        self.assertEqual(results, [])

    def test_shutdown_rejects_new_tasks_and_ignores_late_callbacks(self):
        qt_app()
        manager = BackgroundTaskManager()
        release = threading.Event()
        results = []

        self.assertTrue(manager.start("telemetry", lambda _cancel: (release.wait(1.0), "late")[1], on_success=results.append))
        manager.shutdown()
        self.assertFalse(manager.start("other", lambda _cancel: "new", on_success=results.append))
        release.set()

        self.assertTrue(process_until(lambda: not manager.is_running("telemetry")))
        self.assertEqual(results, [])

    def test_deleted_signal_source_does_not_raise_from_worker(self):
        class BrokenSignal:
            def emit(self, *_args):
                raise RuntimeError("Signal source has been deleted")

        class BrokenSignals:
            completed = BrokenSignal()
            failed = BrokenSignal()

        task = _FunctionTask(
            name="late",
            generation=1,
            fn=lambda _cancel: "done",
            cancel_event=threading.Event(),
            signals=BrokenSignals(),
        )

        task.run()


if __name__ == "__main__":
    unittest.main()

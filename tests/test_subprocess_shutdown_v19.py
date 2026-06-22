import subprocess
import unittest
from unittest.mock import patch

from core.ui.window import DashboardApp


class FakeProcess:
    def __init__(self, *, pid=1234, exit_on_terminate=True, exit_on_kill=True):
        self.pid = pid
        self.exit_on_terminate = exit_on_terminate
        self.exit_on_kill = exit_on_kill
        self.running = True
        self.terminate_called = False
        self.kill_called = False
        self.wait_calls = 0

    def poll(self):
        return None if self.running else 0

    def terminate(self):
        self.terminate_called = True
        if self.exit_on_terminate:
            self.running = False

    def kill(self):
        self.kill_called = True
        if self.exit_on_kill:
            self.running = False

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.running:
            raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout)
        return 0


class ShutdownHarness:
    def __init__(self, bot_process=None, alerts_process=None):
        self.process = bot_process
        self.alerts_process = alerts_process

    def stop_process_with_timeout(self, process, **kwargs):
        return DashboardApp.stop_process_with_timeout(self, process, **kwargs)


class SubprocessShutdownV19Tests(unittest.TestCase):
    def test_stop_process_returns_after_graceful_exit(self):
        process = FakeProcess(exit_on_terminate=True)

        result = DashboardApp.stop_process_with_timeout(object(), process, terminate_timeout=0.01, kill_timeout=0.01)

        self.assertTrue(result)
        self.assertTrue(process.terminate_called)
        self.assertFalse(process.kill_called)
        self.assertEqual(process.poll(), 0)

    def test_stop_process_kills_after_timeout(self):
        process = FakeProcess(exit_on_terminate=False, exit_on_kill=True)

        with patch("core.ui.window.terminate_bot_process", return_value=False) as force_stop:
            result = DashboardApp.stop_process_with_timeout(object(), process, terminate_timeout=0.01, kill_timeout=0.01)

        self.assertTrue(result)
        self.assertTrue(process.terminate_called)
        self.assertTrue(process.kill_called)
        force_stop.assert_called_once_with(process.pid)
        self.assertEqual(process.poll(), 0)

    def test_close_shutdown_clears_runtime_state_only_after_stop(self):
        harness = ShutdownHarness(
            bot_process=FakeProcess(pid=111, exit_on_terminate=True),
            alerts_process=FakeProcess(pid=222, exit_on_terminate=True),
        )

        with patch("core.ui.window.clear_bot_runtime_state") as clear_bot, patch(
            "core.ui.window.clear_alert_runtime_state"
        ) as clear_alert:
            DashboardApp.shutdown_child_processes(harness)

        self.assertIsNone(harness.process)
        self.assertIsNone(harness.alerts_process)
        clear_bot.assert_called_once_with(111)
        clear_alert.assert_called_once_with(222)

    def test_close_shutdown_keeps_runtime_state_when_process_survives(self):
        harness = ShutdownHarness(bot_process=FakeProcess(pid=333, exit_on_terminate=False, exit_on_kill=False))

        with patch("core.ui.window.terminate_bot_process", return_value=False), patch(
            "core.ui.window.clear_bot_runtime_state"
        ) as clear_bot:
            DashboardApp.shutdown_child_processes(harness)

        self.assertIsNotNone(harness.process)
        self.assertTrue(harness.process.terminate_called)
        self.assertTrue(harness.process.kill_called)
        clear_bot.assert_not_called()


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations
import queue
import threading
import unittest
from unittest.mock import MagicMock, patch

from job_control import remaining_seconds, format_duration
from fast_comment_gui import FastCommentGUI


class ProgressAndCancellationTests(unittest.TestCase):
    def test_remaining_time_uses_measured_ffmpeg_speed(self):
        self.assertEqual(remaining_seconds(100.0, 40.0, "6.0x"), 10)
        self.assertEqual(remaining_seconds(100.0, 80.0, "0.5x"), 40)
        self.assertEqual(remaining_seconds(100.0, 100.0, "2.0x"), 0)
        self.assertIsNone(remaining_seconds(None, 20, "3.0x"))
        self.assertIsNone(remaining_seconds(100.0, 0, "N/A"))
        self.assertIsNone(remaining_seconds(100.0, 0, "0x"))
        self.assertEqual(format_duration(61), "01:01")
        self.assertEqual(format_duration(3661), "1:01:01")

    def test_gui_displays_eta_only_when_measured(self):
        gui = object.__new__(FastCommentGUI)
        gui.status = MagicMock()
        gui.progressbar = MagicMock()
        gui._total_seconds = 30.0
        gui._processed_seconds = 0.0
        gui._last_speed = ""
        gui._read_progress("progress=continue")
        self.assertIn("計測中", gui.status.set.call_args.args[0])
        gui._read_progress("out_time=00:00:10.000")
        gui._read_progress("speed=5.0x")
        gui._read_progress("progress=continue")
        self.assertIn("残り約 00:04", gui.status.set.call_args.args[0])
        self.assertEqual(gui.progressbar.configure.call_args.kwargs["value"], 100 / 3)

    def test_cancel_before_process_start_does_not_spawn_it(self):
        gui = object.__new__(FastCommentGUI)
        gui.events = queue.Queue()
        gui._cancel_event = threading.Event()
        gui._cancel_event.set()
        gui.worker_process = None
        with patch("fast_comment_gui.subprocess.Popen") as popen:
            gui._run_worker(["FakeWorker.exe"])
            popen.assert_not_called()
        self.assertEqual(gui.events.get_nowait()[0], "cancelled")

    def test_cancel_during_spawn_terminates_worker_and_reports_cancelled(self):
        gui = object.__new__(FastCommentGUI)
        gui.events = queue.Queue()
        gui._cancel_event = threading.Event()
        gui.worker_process = None
        gui._terminate_worker = MagicMock()
        process = MagicMock()
        process.stdout = iter(["エンコード方式: NVIDIA NVENC\n"])
        process.wait.return_value = 1

        def start(*args, **kwargs):
            gui._cancel_event.set()
            return process

        with patch("fast_comment_gui.subprocess.Popen", side_effect=start):
            gui._run_worker(["FakeWorker.exe"])
        gui._terminate_worker.assert_called_once_with(process)
        self.assertEqual(gui.events.get_nowait()[0], "log")
        self.assertEqual(gui.events.get_nowait()[0], "cancelled")
        self.assertIsNone(gui.worker_process)


if __name__ == "__main__":
    unittest.main()

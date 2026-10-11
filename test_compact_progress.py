from __future__ import annotations

import contextlib
import io
import unittest
from unittest.mock import patch

import fast_comment as core


class StubFFmpeg:
    def __init__(self, lines, returncode=0):
        self.stdout = iter(lines)
        self.returncode = returncode

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def wait(self):
        return self.returncode


class CompactFFmpegOutputTests(unittest.TestCase):
    def test_progress_key_lines_compacted_into_one_gui_message(self):
        output = io.StringIO()
        process = StubFFmpeg([
            "frame=10\n", "fps=24.0\n", "out_time=00:00:10.000\n",
            "speed=2.5x\n", "progress=continue\n",
            "frame=20\n", "out_time=00:00:20.000\n",
            "speed=3.0x\n", "progress=continue\n",
            "[h264_nvenc] Warning: a test diagnostic\n",
            "progress=end\n"
        ])
        with patch.object(core.subprocess, "Popen", return_value=process) as mocked, \
             patch.object(core.time, "monotonic", side_effect=[100.0, 101.0, 103.0]), \
             contextlib.redirect_stdout(output):
            result = core.execute(["ffmpeg", "-progress", "pipe:1", "-y", "out.mp4"])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(mocked.call_count, 1)
        text = output.getvalue()
        self.assertEqual(text.count("FC_PROGRESS|"), 2)
        self.assertIn("FC_FINALIZING", text)
        self.assertIn("FC_PROGRESS|00:00:10.000|2.5x", text)
        self.assertIn("FC_PROGRESS|00:00:20.000|3.0x", text)
        self.assertIn("Warning: a test diagnostic", text)
        self.assertNotIn("frame=20", text)
        self.assertNotIn("out_time=00:00:10.000\n", text)

    def test_failures_retain_ffmpeg_diagnostics_without_losing_error(self):
        output = io.StringIO()
        process = StubFFmpeg(["metadata line\n", "Error while encoding\n"], returncode=1)
        with patch.object(core.subprocess, "Popen", return_value=process), \
             contextlib.redirect_stdout(output):
            with self.assertRaises(core.subprocess.CalledProcessError):
                core.execute(["ffmpeg", "-progress", "pipe:1", "-y", "out.mp4"])
        text = output.getvalue()
        self.assertIn("Error while encoding", text)
        self.assertIn("metadata line", text)
        self.assertIn("直近の診断ログ", text)

    def test_quiet_metadata_command_uses_existing_behavior(self):
        with patch.object(core.subprocess, "run") as mocked:
            mocked.return_value.stdout = "ok"
            core.execute(["ffprobe", "-v", "error"], quiet=True)
        mocked.assert_called_once()


if __name__ == "__main__":
    unittest.main()

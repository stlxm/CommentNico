from __future__ import annotations

import queue
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import app_paths
import fast_comment as core
import fast_comment_gui as gui


class AccurateMovingSampleTests(unittest.TestCase):
    def test_ffmpeg_sample_video_uses_real_ass_at_export_resolution(self):
        captured = {}
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)

            def ffmpeg_run(command, **kwargs):
                cwd = Path(kwargs["cwd"])
                captured["command"] = command
                captured["ass"] = (cwd / "comments.ass").read_text(encoding="utf-8-sig")
                (cwd / "frame_0001.png").write_bytes(b"png1")
                (cwd / "frame_0002.png").write_bytes(b"png2")
                (cwd / "frame_0003.png").write_bytes(b"png3")
                return CompletedProcess(command, 0, stdout="", stderr="")

            settings = core.CommentSettings(
                font_size=40, speed_percent=160, color_mode="single",
                single_color="#33AA55", row_gap=2.0)
            with patch.object(core, "tool", return_value="ffmpeg"), \
                 patch("fast_comment.subprocess.run", side_effect=ffmpeg_run), \
                 patch.object(app_paths, "DATA_DIR", base / "data"):
                frames, fps, count = core.render_sample_video_preview(
                    gui.SAMPLE_ENTRIES, settings, "nico")
        self.assertEqual(frames, [b"png1", b"png2", b"png3"])
        self.assertEqual(fps, 12)
        self.assertGreater(count, 0)
        self.assertIn("Style: Default,Meiryo,40,", captured["ass"])
        self.assertIn(r"\c&H0055AA33", captured["ass"])
        self.assertIn(r"\move(", captured["ass"])
        self.assertIn("testsrc2=size=1280x720:rate=12:duration=8", captured["command"])
        self.assertEqual(captured["command"][captured["command"].index("-vf")+1],
                         "setpts=PTS-STARTPTS,ass=comments.ass,scale=640:360,format=rgb24")
        self.assertEqual(captured["command"][captured["command"].index("-frames:v")+1], "96")

    def test_invalid_video_preview_rate_rejected(self):
        with self.assertRaises(ValueError):
            core.render_sample_video_preview([], core.CommentSettings(), "nico", fps=100)

    def test_old_render_result_is_discarded_by_generation(self):
        instance = object.__new__(gui.FastCommentGUI)
        instance.events = queue.Queue()
        instance._sample_preview_generation = 4
        instance._sample_preview_frames = []
        instance._sample_preview_pending = True
        instance._sample_preview_active = False
        instance.preview_note = MagicMock()
        instance.canvas = MagicMock()
        instance._redraw_background = MagicMock()
        instance._reset_preview_clock = MagicMock()
        instance._exact_preview_active = False
        # Poll should ignore a stale response before it can affect the GUI.
        instance.events.put(("sample_preview_loaded", (3, [b"stale"], 12, 5)))
        instance.events.put(("sample_preview_error", (3, "outdated")))
        instance.root = MagicMock()
        instance.poll()
        self.assertEqual(instance._sample_preview_frames, [])
        self.assertTrue(instance._sample_preview_pending)
        self.assertFalse(instance._sample_preview_active)


if __name__ == "__main__":
    unittest.main()

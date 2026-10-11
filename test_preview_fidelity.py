from __future__ import annotations

import inspect
import tempfile
import time
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import app_paths
import fast_comment as core
import fast_comment_gui as gui_module


class PreviewFidelityTests(unittest.TestCase):
    def test_exact_frame_uses_real_ass_at_selected_video_time(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            video = directory / "vod.mp4"
            chat = directory / "chat.json"
            dest = directory / "frame.png"
            video.write_bytes(b"placeholder")

            captured = []

            def fake_convert(path, ass, w, h, options):
                self.assertEqual((w, h), (1920, 1080))
                self.assertEqual(options.start_seconds, 10.0)
                self.assertEqual(options.settings.font_size, 32)
                self.assertEqual(options.style, "nico")
                ass.write_text("mock ass", encoding="utf-8")
                return 9, 2

            def fake_execute(args, **kwargs):
                captured.append(args)
                Path(args[-1]).write_bytes(b"png placeholder")
                return CompletedProcess(args, 0, stdout="", stderr="")

            with patch.object(app_paths, "DATA_DIR", directory / "cache"), \
                 patch.object(core, "tool", side_effect=lambda name: name), \
                 patch.object(core, "video_metadata", return_value=(1920, 1080, 100.0)), \
                 patch.object(core, "convert_chat_to_ass", side_effect=fake_convert), \
                 patch.object(core, "execute", side_effect=fake_execute):
                actual = core.render_exact_preview_frame(
                    video, chat, dest, settings=core.CommentSettings(font_size=32),
                    style="nico", start_seconds=10.0, frame_seconds=5.0)

            self.assertEqual(actual, (9, 2, 5.0))
            cmd = captured[0]
            self.assertEqual(cmd[cmd.index("-ss") + 1], "10.0")
            self.assertIn("ass=comments.ass", cmd[cmd.index("-vf") + 1])
            self.assertIn("select='gte(t,5)'", cmd[cmd.index("-vf") + 1])
            self.assertIn("scale=640:360", cmd[cmd.index("-vf") + 1])
            self.assertEqual(dest.read_bytes(), b"png placeholder")

    def test_real_frame_rejects_time_beyond_vod_duration(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            with patch.object(core, "tool", side_effect=lambda name: name), \
                 patch.object(core, "video_metadata", return_value=(1280, 720, 3.0)):
                with self.assertRaises(ValueError):
                    core.render_exact_preview_frame(
                        directory / "v.mp4", directory / "c.json", directory / "frame.png",
                        settings=core.CommentSettings(), style="nico", start_seconds=10.0)

    def test_live_tk_font_size_is_pixels_not_points(self):
        gui = object.__new__(gui_module.FastCommentGUI)
        gui.canvas = MagicMock()
        gui.canvas.winfo_exists.return_value = True
        gui.canvas.winfo_width.return_value = 640
        gui.canvas.winfo_height.return_value = 360
        gui.root = MagicMock()
        gui._exact_preview_active = False
        gui._preview_started = time.monotonic() - 2
        gui._preview_paused_at = None
        gui._preview_span = 14
        gui._preview_events = [
            core.CommentEvent(at=0.0, end=8.0, text="test", color="#FFFFFF",
                              lane=0, y=100, x_start=1000, x_end=-300,
                              font_size=22, moving=True)
        ]
        gui._animate_preview()
        calls = gui.canvas.create_text.call_args_list
        self.assertGreaterEqual(len(calls), 2)
        for call in calls:
            font = call.kwargs["font"]
            self.assertEqual(font[0], "Meiryo")
            self.assertLess(font[1], 0)
        self.assertEqual(calls[-1].kwargs["font"][1], -11)


if __name__ == "__main__":
    unittest.main()

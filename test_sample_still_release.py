from __future__ import annotations

import json
import queue
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import app_paths
import fast_comment as core
import fast_comment_gui as gui


class FinalSamplePreviewTests(unittest.TestCase):
    def test_sample_preview_uses_same_ass_generator_as_normal_export(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            target = directory / "sample.png"
            got = {}

            def run_ffmpeg(command, **kwargs):
                got["command"] = command
                got["working"] = Path(kwargs["cwd"])
                ass = got["working"] / "comments.ass"
                got["ass"] = ass.read_text(encoding="utf-8-sig")
                (got["working"] / "sample.png").write_bytes(b"fake valid rendered PNG")
                return CompletedProcess(command, 0, stdout="", stderr="")

            settings = core.CommentSettings(font_size=44, speed_percent=175,
                                            color_mode="single", single_color="#33AA55")
            with patch.object(core, "tool", return_value="ffmpeg"), \
                 patch("fast_comment.subprocess.run", side_effect=run_ffmpeg), \
                 patch.object(app_paths, "DATA_DIR", directory / "scratch"):
                n = core.render_sample_comment_preview(
                    gui.SAMPLE_ENTRIES, settings, "nico", target)
            self.assertGreater(n, 0)
            self.assertEqual(target.read_bytes(), b"fake valid rendered PNG")
            self.assertIn("Style: Default,Meiryo,44,", got["ass"])
            self.assertIn(r"\c&H0055AA33", got["ass"])
            self.assertIn(r"\move(", got["ass"])
            self.assertIn("ass=comments.ass", got["command"][got["command"].index("-vf") + 1])
            self.assertIn("select='gte(t,5)'", got["command"][got["command"].index("-vf") + 1])
            self.assertIn("scale=640:360", got["command"][got["command"].index("-vf") + 1])

    def test_preview_reacts_to_settings_with_debounce(self):
        instance = object.__new__(gui.FastCommentGUI)
        instance._settings_job = None
        instance._sample_preview_job = None
        instance._sample_preview_generation = 0
        instance._sample_preview_pending = False
        instance._sample_preview_active = True
        instance.root = MagicMock()
        instance.root.after.side_effect = [42, 43]
        instance.preview_note = MagicMock()
        instance.settings_changed()
        self.assertEqual(instance._sample_preview_generation, 1)
        self.assertTrue(instance._sample_preview_pending)
        self.assertFalse(instance._sample_preview_active)
        self.assertEqual(instance.root.after.call_args_list[0].args[0], 200)
        self.assertEqual(instance.root.after.call_args_list[1].args[0], 700)

    def test_stale_sample_results_are_discarded(self):
        # Generation counters ensure an older settings render cannot replace the latest.
        instance = object.__new__(gui.FastCommentGUI)
        instance._sample_preview_generation = 2
        instance._sample_preview_job = None
        instance._sample_preview_active = False
        instance._sample_preview_pending = True
        instance.style = MagicMock()
        instance.style.get.return_value = "nico"
        instance.current_settings = MagicMock(return_value=core.CommentSettings())
        instance.preview_note = MagicMock()
        instance.events = queue.Queue()
        class ImmediateThread:
            def __init__(self, target, daemon):
                self.target = target
            def start(self):
                self.target()
        def fake_render(entries, settings, style):
            return [b"png0", b"png1"], 12, 10
        with patch("fast_comment_gui.threading.Thread", ImmediateThread), \
             patch.object(core, "render_sample_video_preview", side_effect=fake_render):
            instance.render_sample_preview()
        event, payload = instance.events.get_nowait()
        self.assertEqual(event, "sample_preview_loaded")
        self.assertEqual(payload[0], 3)
        self.assertEqual(payload[1], [b"png0", b"png1"])
        self.assertEqual(payload[2], 12)
        self.assertEqual(payload[3], 10)

    def test_storage_preferences_roundtrip_and_scratch_on_output_disk(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            preferences_file = directory / "prefs.json"
            cache_path = directory / "元動画"
            app_paths.save_storage_preferences(
                app_paths.StoragePreferences(str(cache_path)), preferences_file)
            self.assertEqual(
                app_paths.load_storage_preferences(preferences_file).cache_directory,
                str(cache_path.resolve()))
            self.assertFalse(cache_path.exists())
            dest = directory / "Output"
            self.assertEqual(app_paths.work_directory_for_output(dest),
                             (dest / ".FastComment-work").resolve())

    def test_cli_cache_and_work_paths_are_forwarded(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            cache = directory / "cache"
            work = directory / "working"
            with patch.object(core, "process", return_value=directory / "complete.mp4") as fake:
                self.assertEqual(core.main([
                    "--vod", "2896810049", "--cache-dir", str(cache),
                    "--work-dir", str(work)]), 0)
            self.assertEqual(fake.call_args.kwargs["cache_dir"], cache)
            self.assertEqual(fake.call_args.kwargs["work_dir"], work)


if __name__ == "__main__":
    unittest.main()

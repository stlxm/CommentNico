from __future__ import annotations
import json
import tempfile
import queue
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import app_paths
import fast_comment as fc
import fast_comment_gui as gui_module


class OutputDirectoryTests(unittest.TestCase):
    def test_preferences_round_trip_and_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = root / "settings" / "output_preferences.json"
            self.assertEqual(app_paths.load_output_preferences(config).directory, str(app_paths.OUTPUT_DIR))
            chosen = root / "配信の完成動画"
            original = app_paths.OutputPreferences(directory=str(chosen), open_on_complete=False)
            app_paths.save_output_preferences(original, config)
            restored = app_paths.load_output_preferences(config)
            self.assertEqual(restored.directory, str(chosen.resolve()))
            self.assertFalse(restored.open_on_complete)
            self.assertFalse(chosen.exists(), "Saving preferences must not create or alter user content")

    def test_preferences_reject_bad_input(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config = root / "output_preferences.json"
            config.write_text(json.dumps({"directory": str(root), "open_on_complete": "yes"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                app_paths.load_output_preferences(config)
            with self.assertRaises(ValueError):
                app_paths.resolve_output_directory(" ")
            target_file = root / "not_a_directory"
            target_file.write_text("keep", encoding="utf-8")
            with self.assertRaises(ValueError):
                app_paths.resolve_output_directory(str(target_file))
            self.assertEqual(target_file.read_text(encoding="utf-8"), "keep")

    def test_output_path_uses_selected_root_and_keeps_streamer_grouping(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            chat = root / "chat.json"
            chat.write_text(json.dumps({
                "streamer": {"name": "streamer"},
                "video": {"created_at": "2026-10-11", "title": "test"},
                "comments": []
            }), encoding="utf-8")
            dest_root = root / "my results"
            first = fc.output_path(chat, "2896810049", "nico", "burn", 30, output_dir=dest_root)
            self.assertEqual(first.parent, (dest_root / "streamer").resolve())
            self.assertEqual(first.suffix, ".mp4")
            first.parent.mkdir(parents=True, exist_ok=True)
            first.write_text("keep", encoding="utf-8")
            second = fc.output_path(chat, "2896810049", "nico", "burn", 30, output_dir=dest_root)
            self.assertNotEqual(first, second)
            self.assertEqual(first.read_text(encoding="utf-8"), "keep")
            self.assertEqual(app_paths.completed_output_folder(first, dest_root), first.parent)
            self.assertEqual(app_paths.completed_output_folder(None, dest_root), dest_root.resolve())

    def test_cli_forwards_custom_destination(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td) / "custom-folder"
            with patch.object(fc, "process", return_value=Path(td) / "done.mp4") as job:
                self.assertEqual(fc.main(["--vod", "2896810049", "--output-dir", str(directory)]), 0)
            self.assertEqual(job.call_args.kwargs["output_dir"], directory)

    def test_gui_opens_exact_video_folder_only_after_success(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dest = root / "streamer"
            dest.mkdir()
            video = dest / "clip.mp4"
            video.write_bytes(b"sample")
            gui = object.__new__(gui_module.FastCommentGUI)
            gui.events = queue.Queue()
            gui.busy = True
            gui._completed_file = None
            gui._read_progress = MagicMock()
            gui.append = MagicMock()
            gui.root = MagicMock()
            gui.start_button = MagicMock()
            gui.cancel_button = MagicMock()
            gui.progressbar = MagicMock()
            gui.status = MagicMock()
            gui._show_output_folder = MagicMock()
            gui.open_on_complete = MagicMock()
            gui.open_on_complete.get.return_value = True
            gui.output_directory = MagicMock()
            gui.output_directory.get.return_value = str(root)

            gui.events.put(("log", f"完成動画: {video}"))
            gui.events.put(("done", 0))
            gui.poll()
            gui._show_output_folder.assert_called_once_with(dest)
            self.assertFalse(gui.busy)

            gui._show_output_folder.reset_mock()
            gui.events.put(("done", 1))
            gui.poll()
            gui._show_output_folder.assert_not_called()

            gui.open_on_complete.get.return_value = False
            gui.events.put(("done", 0))
            gui.poll()
            gui._show_output_folder.assert_not_called()

if __name__ == "__main__":
    unittest.main()

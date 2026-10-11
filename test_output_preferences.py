from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app_paths
import fast_comment as fc


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

if __name__ == "__main__":
    unittest.main()

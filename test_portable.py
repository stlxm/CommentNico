from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app_paths
import fast_comment as fc

class PortableTests(unittest.TestCase):
    def test_entrypoint_files_present(self):
        self.assertTrue((app_paths.APP_DIR / "FastComment_GUI.pyw").is_file())
        self.assertTrue((app_paths.APP_DIR / "FastCommentWorker.py").is_file())

    def test_tools_not_dependent_on_legacy_parent(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "tools").mkdir()
            (base / "tools" / "ffmpeg.exe").write_bytes(b"ok")
            with patch.object(app_paths, "APP_DIR", base):
                self.assertEqual(app_paths.executable("ffmpeg"), str(base / "tools" / "ffmpeg.exe"))

    def test_local_files_no_vod_id(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            v = p / "clip.mp4"
            c = p / "chat.json"
            v.write_bytes(b"test")
            c.write_text(json.dumps({"comments": []}), encoding="utf-8")
            with patch.object(fc, "process", return_value=p / "result.mp4") as run:
                self.assertEqual(fc.main(["--video", str(v), "--chat", str(c)]), 0)
                self.assertEqual(run.call_args.args[0], "")

    def test_missing_vod_id_is_rejected(self):
        with self.assertRaises(SystemExit) as caught:
            fc.main(["--video", "clip.mp4"])
        self.assertEqual(caught.exception.code, 2)

    def test_vod_url(self):
        self.assertEqual(fc.normalize_id("https://www.twitch.tv/videos/2896810049?t=1h"), "2896810049")
        with self.assertRaises(ValueError):
            fc.normalize_id("https://www.twitch.tv/channel")

    def test_comment_colors(self):
        event = {"commenter": {"name": "fox"}, "message": {"body": "hi", "user_color": "#ff12ab"}}
        self.assertEqual(fc.resolve_comment_color(event, fc.CommentSettings(color_mode="white")), "#FFFFFF")
        self.assertEqual(fc.resolve_comment_color(event, fc.CommentSettings(color_mode="twitch")), "#FF12AB")

if __name__ == "__main__":
    unittest.main()

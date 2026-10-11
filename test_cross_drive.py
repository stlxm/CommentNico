from __future__ import annotations

import errno
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import fast_comment as core


class CrossDriveExportTests(unittest.TestCase):
    def test_cross_drive_copy_publishes_complete_video(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            src = root / "C" / "burn_result.mp4"
            dest = root / "D" / "out" / "配信者" / "clip.mp4"
            src.parent.mkdir()
            src.write_bytes(b"valid encoded MP4 for copy test")
            original_replace = Path.replace
            attempts = []

            def simulate_cross_drive(path, target):
                attempts.append((Path(path), Path(target)))
                if Path(path) == src:
                    raise OSError(errno.EXDEV, "simulated cross-drive move")
                return original_replace(path, target)

            with patch.object(Path, "replace", simulate_cross_drive):
                core.finalize_output(src, dest)

            self.assertEqual(dest.read_bytes(), b"valid encoded MP4 for copy test")
            self.assertFalse(src.exists())
            self.assertEqual(len(attempts), 2)
            self.assertFalse(list(dest.parent.glob(".fastcomment_copy_*")))

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            src = root / "encoded.mp4"
            dest = root / "export.mp4"
            src.write_bytes(b"new")
            dest.write_bytes(b"keep old")
            with self.assertRaises(FileExistsError):
                core.finalize_output(src, dest)
            self.assertEqual(dest.read_bytes(), b"keep old")
            self.assertEqual(src.read_bytes(), b"new")

    def test_copy_failure_keeps_encoded_source_and_cleans_partial(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            src = root / "encoded.mp4"
            dest = root / "output" / "export.mp4"
            src.write_bytes(b"source still there")
            original_replace = Path.replace

            def simulate_cross_drive(path, target):
                if Path(path) == src:
                    raise OSError(errno.EXDEV, "simulated EXDEV")
                return original_replace(path, target)

            with patch.object(Path, "replace", simulate_cross_drive), patch.object(core.shutil, "copy2", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    core.finalize_output(src, dest)
            self.assertEqual(src.read_bytes(), b"source still there")
            self.assertFalse(dest.exists())
            self.assertEqual(list(dest.parent.glob(".fastcomment_copy_*")), [])

    def test_save_failure_after_nvenc_success_does_not_reencode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            render_count = []

            def fake_execute(args, **kwargs):
                if "-filters" in args:
                    return CompletedProcess(args, 0, stdout=" .S. ass V->V Render ASS subtitles", stderr="")
                if "-y" in args:
                    render_count.append(args)
                    Path(args[-1]).write_bytes(b"encoded by GPU")
                return CompletedProcess(args, 0, stdout="", stderr="")

            with patch.object(core, "execute", side_effect=fake_execute), \
                 patch.object(core, "encoder_candidates", return_value=[
                     ("NVIDIA NVENC", ["-c:v", "h264_nvenc"]),
                     ("CPU/libx264", ["-c:v", "libx264"]),
                 ]), \
                 patch.object(core, "video_metadata", return_value=(1280, 720, 30)), \
                 patch.object(core, "tool", return_value="ffprobe"), \
                 patch.object(core, "finalize_output", side_effect=OSError("destination disk full")):
                with self.assertRaisesRegex(OSError, "destination disk full"):
                    core.render("ffmpeg", root / "in.mp4", root / "comments.ass",
                                root / "out.mp4", root, mode="burn", prefer="auto",
                                normalize_audio=False, preview_seconds=30)
            self.assertEqual(len(render_count), 1)
            self.assertIn("h264_nvenc", render_count[0])
            self.assertNotIn("libx264", render_count[0])


if __name__ == "__main__":
    unittest.main()

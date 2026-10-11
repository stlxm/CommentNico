"""Regression tests for OBS MKV comments shifted onto recording time."""
from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import fast_comment as core


def sample(t: float, body: str = "こんにちは") -> dict:
    return {
        "content_offset_seconds": t,
        "message": {"body": body},
        "commenter": {"name": "viewer", "display_name": "viewer"},
    }


class ObsOffsetTests(unittest.TestCase):
    def test_signed_time_input_and_validation(self):
        self.assertEqual(core.parse_comment_offset("+12.5"), 12.5)
        self.assertEqual(core.parse_comment_offset("-00:01:30.5"), -90.5)
        self.assertEqual(core.parse_comment_offset("0"), 0)
        self.assertEqual(core.parse_comment_offset("  -8  "), -8)
        for value in ("", "hello", "--8", "nan", "inf", "25:00:00"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    core.parse_comment_offset(value)

    def test_positive_offset_delays_chat_on_obs_recording(self):
        entries = [sample(5.0)]
        events, _ = core.layout_comments(entries, 1280, 720,
            core.Options("nico", "right", None, 0.0, core.CommentSettings(), 12.0))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].at, 17.0)

    def test_negative_offset_advances_chat_and_ignores_pre_recording_messages(self):
        entries = [sample(2.0), sample(12.0)]
        events, _ = core.layout_comments(entries, 1280, 720,
            core.Options("nico", "right", None, 0.0, core.CommentSettings(), -8.0))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].at, 4.0)

    def test_shifted_comment_within_selected_30_second_clip(self):
        # The clip starts at OBS 00:20, while the same message is at Twitch 00:05.
        settings = core.CommentSettings()
        events, _ = core.layout_comments([sample(5.0)], 1280, 720,
            core.Options("nico", "right", 30.0, 20.0, settings, 16.0))
        self.assertEqual(events[0].at, 1.0)
        self.assertEqual(len(events), 1)

    def test_dense_preview_tracks_obs_timestamps(self):
        with tempfile.TemporaryDirectory() as temp:
            chat = Path(temp) / "chat.json"
            chat.write_text(json.dumps({"comments": [sample(9.0), sample(9.2), sample(9.6)]}), encoding="utf-8")
            start, count = core.suggest_preview_start(chat, 3.0, 80.0, 12.0)
            self.assertEqual(start, 20.0)
            self.assertEqual(count, 3)
            start2, count2 = core.suggest_preview_start(chat, 3.0, 80.0, -8.0)
            self.assertEqual(start2, 0.0)
            self.assertEqual(count2, 3)

    def test_ass_timestamps_reflect_offset_and_clip_start(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            chat, ass = root / "chat.json", root / "comments.ass"
            chat.write_text(json.dumps({"comments": [sample(5.0, "SYNC_TEST")]}), encoding="utf-8")
            count, _ = core.convert_chat_to_ass(chat, ass, 1280, 720,
                core.Options("nico", "right", 30.0, 20.0, core.CommentSettings(), 16.0))
            self.assertEqual(count, 1)
            ass_text = ass.read_text(encoding="utf-8-sig")
            self.assertIn("Dialogue: 0,0:00:01.", ass_text)
            self.assertIn("SYNC_TEST", ass_text)


if __name__ == "__main__":
    unittest.main()

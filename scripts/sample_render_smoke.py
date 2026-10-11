"""Actual FFmpeg sample-video smoke test (no Twitch assets required).

Designed for a CI machine with ffmpeg+libass on PATH and CJK fonts installed.
"""
from __future__ import annotations
from fast_comment import CommentSettings, render_sample_video_preview

ENTRIES = [
    {"content_offset_seconds": 0.2, "commenter": {"name": "viewer1"},
     "message": {"body": "こんばんは！", "user_color": "#FFAA77"}},
    {"content_offset_seconds": 0.6, "commenter": {"name": "viewer2"},
     "message": {"body": "888888", "user_color": "#AAFF88"}},
    {"content_offset_seconds": 0.9, "commenter": {"name": "viewer3"},
     "message": {"body": "ナイス", "user_color": "#77AAFF"}},
]


def main() -> None:
    frames, fps, count = render_sample_video_preview(
        ENTRIES, CommentSettings(font_size=38, speed_percent=140),
        "nico", seconds=2.0, fps=6
    )
    assert fps == 6, fps
    assert count == 3, count
    assert len(frames) == 12, len(frames)
    assert all(f.startswith(b"\x89PNG\r\n\x1a\n") for f in frames)
    assert frames[0] != frames[-1], "Sample scene did not animate"
    print(f"OK: FFmpeg/libass sample produced {len(frames)} PNG frames, {count} comments")


if __name__ == "__main__":
    main()

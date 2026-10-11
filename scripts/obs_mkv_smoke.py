"""End-to-end smoke: local OBS-style MKV with two audio tracks + shifted Twitch chat."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import fast_comment as fc


def main() -> None:
    ffmpeg, ffprobe = fc.tool("ffmpeg"), fc.tool("ffprobe")
    with tempfile.TemporaryDirectory(prefix="fc_obs_smoke_") as temp:
        work = Path(temp)
        source, chat, ass, result = (work / "obs.mkv", work / "chat.json",
                                      work / "comments.ass", work / "result.mp4")
        subprocess.run([
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=320x180:r=12:d=3",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-f", "lavfi", "-i", "sine=frequency=880:duration=3",
            "-map", "0:v:0", "-map", "1:a:0", "-map", "2:a:0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-y", str(source)
        ], check=True)
        comment = {"content_offset_seconds": 0.6,
                   "message": {"body": "OBS音声トラック分離テスト"},
                   "commenter": {"name": "viewer"}}
        chat.write_text(json.dumps({"comments": [comment]}, ensure_ascii=False),
                        encoding="utf-8")
        count, _ = fc.convert_chat_to_ass(chat, ass, 320, 180,
            fc.Options("nico", "right", None, 0.0, fc.CommentSettings(), 1.2))
        assert count == 1
        content = ass.read_text(encoding="utf-8-sig")
        assert "Dialogue: 0,0:00:01.80" in content, content

        # Model the exact user workflow: OBS MKV -> burnt-in MP4, audio copied
        # without downmixing. render() uses the same options as GUI export.
        fc.render(ffmpeg, source, ass, result, work, mode="burn", prefer="cpu",
                  normalize_audio=False, preview_seconds=3.0)
        assert result.is_file() and result.stat().st_size > 0
        probe = subprocess.run([
            ffprobe, "-v", "error", "-show_entries",
            "stream=codec_type,codec_name", "-of", "json", str(result)
        ], capture_output=True, text=True, check=True)
        streams = json.loads(probe.stdout)["streams"]
        assert sum(s["codec_type"] == "video" for s in streams) == 1, streams
        assert sum(s["codec_type"] == "audio" for s in streams) == 2, streams
        print("[OK] OBS MKV -> MP4: two independent AAC tracks and chat +1.2s")


if __name__ == "__main__":
    main()

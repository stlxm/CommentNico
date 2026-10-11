"""Twitch VOD comment compositor without Saccubus (stdlib + FFmpeg).

Modes: burn (MP4; GPU auto-detection / CPU fallback) and soft (MKV; stream-copy).
This is an independent prototype: it never changes the original Saccubus files.
"""
from __future__ import annotations

import argparse
import errno
import colorsys
from collections import deque
import hashlib
import math
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from app_paths import APP_DIR, CACHE_DIR, OUTPUT_DIR, SETTINGS_FILE, executable, resolve_output_directory, work_directory_for_output
ROOT = APP_DIR
CACHE = CACHE_DIR
OUTPUT = OUTPUT_DIR


def tool(name: str) -> str:
    return executable(name)


def _execute_ffmpeg_with_compact_progress(
    args: list[str], *, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Stream FFmpeg output without flooding consoles with progress key/value lines.

    Emit one structured update approximately every 5 s for the GUI while
    preserving warnings and diagnostics on failure. Never buffer the full
    stdout of an hours-long encode in memory.
    """
    print("[INFO] FFmpegで動画を変換しています…", flush=True)
    recent = deque(maxlen=90)
    out_time = "0"
    speed = "N/A"
    last_report = -1e12
    kwargs = {"cwd": cwd, "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
              "text": True, "errors": "replace", "bufsize": 1}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    with subprocess.Popen([str(x) for x in args], **kwargs) as proc:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.strip()
            if not line:
                continue
            key, sep, value = line.partition("=")
            if sep and key in {
                "frame", "fps", "stream_0_0_q", "bitrate", "total_size",
                "out_time_us", "out_time_ms", "out_time", "dup_frames",
                "drop_frames", "speed", "progress"
            }:
                if key == "out_time":
                    out_time = value
                elif key == "speed":
                    speed = value
                elif key == "progress":
                    now = time.monotonic()
                    if value == "end" or now - last_report >= 5.0:
                        # All progress data in one line; the GUI owns percent/ETA.
                        print(f"FC_PROGRESS|{out_time}|{speed}", flush=True)
                        if value == "end":
                            print("FC_FINALIZING", flush=True)
                        last_report = now
                continue
            recent.append(line)
            if re.search(r"(error|warning|failed|invalid|unable|cannot)", line, re.IGNORECASE):
                print("[FFmpeg] " + line, flush=True)
        returncode = proc.wait()
    if returncode:
        print("[ERROR] FFmpegが失敗しました。直近の診断ログ:", flush=True)
        for item in list(recent)[-18:]:
            print("  " + item, flush=True)
        raise subprocess.CalledProcessError(returncode, [str(x) for x in args])
    return subprocess.CompletedProcess(args, 0)


def execute(args: list[str], *, cwd: Path | None = None, quiet: bool = False) -> subprocess.CompletedProcess[str]:
    if not quiet and "-progress" in args and "pipe:1" in args:
        return _execute_ffmpeg_with_compact_progress(args, cwd=cwd)
    if not quiet:
        command_name = Path(str(args[0])).name
        print(f"[INFO] 実行開始: {command_name}", flush=True)
    return subprocess.run([str(x) for x in args], cwd=cwd, check=True,
                          capture_output=quiet, text=quiet, errors="replace" if quiet else None)


def video_metadata(file: Path, ffprobe: str) -> tuple[int, int, float | None]:
    if not file.is_file() or file.stat().st_size == 0:
        raise ValueError(f"動画が存在しない、または0バイトです: {file}")
    result = execute([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                      "stream=width,height:format=duration", "-of", "json", str(file)], quiet=True)
    data = json.loads(result.stdout)
    if not data.get("streams"):
        raise ValueError(f"動画ストリームがありません: {file}")
    stream = data["streams"][0]
    duration = data.get("format", {}).get("duration")
    return int(stream["width"]), int(stream["height"]), float(duration) if duration else None


def normalize_id(value: str) -> str:
    value = value.strip()
    if value.isdigit():
        return value
    parsed = urlparse(value)
    if parsed.hostname in {"www.twitch.tv", "twitch.tv", "m.twitch.tv"}:
        match = re.fullmatch(r"/videos/(\d+)/?", parsed.path)
        if match:
            return match.group(1)
    raise ValueError("Twitch動画IDか https://www.twitch.tv/videos/数字 を指定してください")


def download(cli: str, mode: str, vod_id: str, dest: Path, ffprobe: str | None = None) -> Path:
    if dest.exists() and dest.stat().st_size:
        try:
            if mode == "videodownload":
                assert ffprobe is not None
                video_metadata(dest, ffprobe)
            else:
                data = json.loads(dest.read_text(encoding="utf-8-sig"))
                if not isinstance(data.get("comments"), list):
                    raise ValueError("commentsがありません")
            print(f"[OK] 取得済みファイルを再利用: {dest}")
            return dest
        except (ValueError, OSError, subprocess.CalledProcessError, AssertionError, KeyError):
            print(f"[WARN] キャッシュが不正なため再ダウンロードします: {dest}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, 4):
        temp = dest.with_name(dest.stem + ".partial" + dest.suffix)
        temp.unlink(missing_ok=True)
        try:
            command = [cli, mode, "--id", vod_id, "--output", str(temp), "--collision", "Overwrite"]
            if mode == "videodownload":
                command += ["--quality", "1080p60"]
            print(f"[{attempt}/3] {mode} を開始します")
            execute(command)
            if mode == "videodownload":
                video_metadata(temp, ffprobe or tool("ffprobe"))
            else:
                parsed = json.loads(temp.read_text(encoding="utf-8-sig"))
                if not isinstance(parsed.get("comments"), list):
                    raise ValueError("取得したチャットJSONにcommentsがありません")
            temp.replace(dest)
            return dest
        except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            temp.unlink(missing_ok=True)
            print(f"[WARN] ダウンロード失敗: {exc}")
            if attempt == 3:
                raise RuntimeError(f"{mode} が3回失敗しました") from exc
            time.sleep(attempt)
    raise RuntimeError("予期しないダウンロード処理終了")


def safe_name(value: str, limit: int = 64) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", value).strip(" .")[:limit] or "untitled"


def ass_timestamp(seconds: float) -> str:
    units = max(0, round(seconds * 100))
    return f"{units // 360000}:{units // 6000 % 60:02}:{units // 100 % 60:02}.{units % 100:02}"


def escape_ass(value: str, max_chars: int = 150) -> str:
    value = "".join(" " if ch in "\r\n\t" or unicodedata.category(ch).startswith("C") else ch for ch in str(value))
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > max_chars:
        value = value[:max_chars - 1] + "…"
    # Avoid arbitrary ASS override injection and backslash escape sequences.
    return value.replace("\\", "＼").replace("{", "｛").replace("}", "｝")


def text_units(message: str) -> float:
    return sum(1.0 if unicodedata.east_asian_width(char) in "WF" else 0.62 for char in message)


def ass_color(value: str) -> str:
    if not re.fullmatch(r"#[A-Fa-f0-9]{6}", str(value)):
        return "&H00FFFFFF"
    red, green, blue = value[1:3], value[3:5], value[5:7]
    return f"&H00{blue}{green}{red}".upper()


@dataclass
class CommentSettings:
    # Font size is measured in pixels for a 720p source and scales with height.
    font_size: int = 22
    speed_percent: int = 100
    row_gap: float = 1.5
    area_percent: int = 75
    collision: str = "overlap"  # overlap or skip
    color_mode: str = "twitch"  # twitch, white, single, account, manual
    single_color: str = "#FFFFFF"
    account_colors: dict[str, str] = field(default_factory=dict)


def valid_hex_color(value: str) -> bool:
    return bool(re.fullmatch(r"#[0-9a-fA-F]{6}", value))


def load_comment_settings(path: Path | None) -> CommentSettings:
    cfg = CommentSettings()
    if not path or not path.exists():
        return cfg
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("コメント設定JSONはオブジェクトである必要があります")
    for key in ("font_size", "speed_percent", "area_percent"):
        if key in data:
            value = int(data[key])
            lower, upper = {"font_size": (12, 80), "speed_percent": (40, 300), "area_percent": (30, 95)}[key]
            if not lower <= value <= upper:
                raise ValueError(f"コメント設定 {key} は {lower}～{upper} にしてください")
            setattr(cfg, key, value)
    if "row_gap" in data:
        cfg.row_gap = float(data["row_gap"])
        if not math.isfinite(cfg.row_gap) or not 1.0 <= cfg.row_gap <= 3.0:
            raise ValueError("row_gap は1.0～3.0にしてください")
    for key, allowed in (("collision", {"overlap", "skip"}),
                         ("color_mode", {"twitch", "white", "single", "account", "manual"})):
        if key in data:
            if data[key] not in allowed:
                raise ValueError(f"コメント設定 {key} が不正です")
            setattr(cfg, key, data[key])
    if "single_color" in data:
        if not valid_hex_color(data["single_color"]):
            raise ValueError("単色指定は #RRGGBB の形式にしてください")
        cfg.single_color = data["single_color"].upper()
    mapping = data.get("account_colors", {})
    if not isinstance(mapping, dict):
        raise ValueError("account_colors は辞書形式にしてください")
    if len(mapping) > 2000:
        raise ValueError("アカウント別カラーは2000件以内にしてください")
    for name, color in mapping.items():
        if not isinstance(name, str) or not 0 < len(name) <= 64 or not isinstance(color, str) or not valid_hex_color(color):
            raise ValueError("アカウント名またはカラーの指定が不正です")
        cfg.account_colors[name.strip().casefold()] = color.upper()
    return cfg


def save_comment_settings(path: Path, settings: CommentSettings) -> None:
    from dataclasses import asdict
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def account_name(entry: dict) -> str:
    who = entry.get("commenter") or {}
    if not isinstance(who, dict):
        who = {}
    return str(who.get("name") or who.get("display_name") or "unknown").strip().casefold()


def resolve_comment_color(entry: dict, settings: CommentSettings) -> str:
    if settings.color_mode == "white":
        return "#FFFFFF"
    if settings.color_mode == "single":
        return settings.single_color
    who = account_name(entry)
    if settings.color_mode == "manual":
        return settings.account_colors.get(who, "#FFFFFF")
    if settings.color_mode == "account":
        digest = hashlib.sha256(who.encode("utf-8")).digest()
        hue = int.from_bytes(digest[:2], "big") / 65536
        r, g, b = colorsys.hsv_to_rgb(hue, 0.62, 1.0)
        return f"#{round(r*255):02X}{round(g*255):02X}{round(b*255):02X}"
    msg = entry.get("message") or {}
    color = msg.get("user_color") if isinstance(msg, dict) else None
    return color.upper() if isinstance(color, str) and valid_hex_color(color) else "#FFFFFF"


@dataclass
class Options:
    style: str = "nico"
    position: str = "right"
    sample_seconds: float | None = None
    start_seconds: float = 0.0
    settings: CommentSettings = field(default_factory=CommentSettings)


@dataclass
class CommentEvent:
    at: float
    end: float
    text: str
    color: str
    lane: int
    y: int
    x_start: int
    x_end: int
    font_size: int
    moving: bool
    align_right: bool = False



def parse_time(value: str | float | int) -> float:
    """Accept seconds or H:M:S / M:S for a preview start position."""
    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        value = str(value).strip()
        if not value:
            return 0.0
        fields = value.split(":")
        if len(fields) > 3 or not all(re.fullmatch(r"\d+(?:\.\d+)?", x) for x in fields):
            raise ValueError("開始位置は 00:15:30（時:分:秒）または秒数で入力してください")
        nums = [float(x) for x in fields]
        if len(nums) >= 2 and (nums[-1] >= 60 or (len(nums) == 3 and nums[-2] >= 60)):
            raise ValueError("分・秒は0〜59で入力してください")
        seconds = 0.0
        for num in nums:
            seconds = seconds * 60 + num
    if not (0 <= seconds < float("inf")):
        raise ValueError("開始位置は0以上の有限の数値にしてください")
    return seconds


def pretty_time(seconds: float) -> str:
    t = int(seconds)
    return f"{t // 3600:02}:{t // 60 % 60:02}:{t % 60:02}"


def suggest_preview_start(chat: Path, seconds: float, duration: float | None) -> tuple[float, int]:
    """Find a dense comment window in O(n log n), biased 1 s before first comment."""
    data = json.loads(chat.read_text(encoding="utf-8-sig"))
    entries = data.get("comments")
    if not isinstance(entries, list):
        raise ValueError("コメントJSONのcommentsが配列ではありません")
    times = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        message = entry.get("message") or {}
        if not isinstance(message, dict) or not str(message.get("body") or "").strip():
            continue
        try:
            t = float(entry.get("content_offset_seconds", -1))
        except (TypeError, ValueError):
            continue
        if 0 <= t < float("inf") and (duration is None or t < duration):
            times.append(t)
    if not times:
        return 0.0, 0
    times.sort()
    right = 0
    best_count = 0
    best_index = 0
    for left, at in enumerate(times):
        right = max(right, left)
        while right < len(times) and times[right] < at + seconds:
            right += 1
        count = right - left
        if count > best_count:
            best_count, best_index = count, left
    start = max(0.0, times[best_index] - 1.0)
    if duration is not None:
        start = min(start, max(0.0, duration - seconds))
    # Count in actual selected window, since clamping may shift it.
    count_actual = sum(1 for t in times if start <= t < start + seconds)
    return start, count_actual

def layout_comments(entries: list, width: int, height: int, options: Options) -> tuple[list[CommentEvent], int]:
    """Single positioning/color engine shared by ASS output and the animated GUI preview."""
    settings = options.settings
    font_size = max(12, round(settings.font_size * height / 720))
    line_height = max(font_size + 2, round(font_size * settings.row_gap))
    speed = max(35.0, max(75, width / 7) * settings.speed_percent / 100.0)
    usable_height = int(height * settings.area_percent / 100)
    max_lanes = min(max(1, usable_height // line_height), 30 if options.style == "nico" else 12)
    lane_available = [0.0] * max_lanes
    events: list[CommentEvent] = []
    collision_count = 0
    line_start_x = width + 24
    for entry in sorted((e for e in entries if isinstance(e, dict)),
                        key=lambda e: _comment_sort_time(e)):
        at = _comment_sort_time(entry)
        if not math.isfinite(at) or at < options.start_seconds or (options.sample_seconds is not None and at >= options.start_seconds + options.sample_seconds):
            continue
        msg = entry.get("message") or {}
        raw = msg.get("body", "") if isinstance(msg, dict) else ""
        message = escape_ass(raw)
        if not message:
            continue
        local_at = at - options.start_seconds
        color = resolve_comment_color(entry, settings)
        if options.style == "twitch":
            commenter = entry.get("commenter") or {}
            username = escape_ass(commenter.get("display_name") or commenter.get("name") or "chat", 32) if isinstance(commenter, dict) else "chat"
            label = f"{username}: {message}"
            lifetime = 7.0
            lane = min(range(max_lanes), key=lambda i: lane_available[i])
            collide = lane_available[lane] > local_at
            if collide and settings.collision == "skip":
                collision_count += 1
                continue
            collision_count += int(collide)
            lane_available[lane] = local_at + lifetime + .1
            event = CommentEvent(local_at, local_at + lifetime, label, color, lane,
                                 int(height * .05) + lane * line_height,
                                 12 if options.position == "left" else width - 12,
                                 12 if options.position == "left" else width - 12,
                                 font_size, False, options.position != "left")
        else:
            estimated_width = font_size * text_units(message) * 1.05
            lifetime = (width + estimated_width + 48) / speed
            lane = min(range(max_lanes), key=lambda i: lane_available[i])
            collide = lane_available[lane] > local_at
            if collide and settings.collision == "skip":
                collision_count += 1
                continue
            collision_count += int(collide)
            lane_available[lane] = local_at + (estimated_width + font_size * 1.5) / speed
            y = int(height * .05) + lane * line_height
            event = CommentEvent(local_at, local_at + lifetime, message, color, lane, y,
                                 line_start_x, int(-estimated_width) - 24,
                                 font_size, True)
        if options.sample_seconds is not None:
            event.end = min(event.end, options.sample_seconds)
        if event.end > event.at:
            events.append(event)
    return events, collision_count


def _comment_sort_time(entry: dict) -> float:
    try:
        return float(entry.get("content_offset_seconds", -1))
    except (ValueError, TypeError):
        return -1.0


def convert_chat_to_ass(chat: Path, out: Path, width: int, height: int,
                        options: Options) -> tuple[int, int]:
    data = json.loads(chat.read_text(encoding="utf-8-sig"))
    entries = data.get("comments", [])
    if not isinstance(entries, list):
        raise ValueError("コメントJSONのcommentsが配列ではありません")
    events, collision_count = layout_comments(entries, width, height, options)
    font_size = max(12, round(options.settings.font_size * height / 720))
    lines = [
        "[Script Info]", "Title: Twitch fast comments", "ScriptType: v4.00+",
        f"PlayResX: {width}", f"PlayResY: {height}", "ScaledBorderAndShadow: yes",
        "WrapStyle: 2", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,Meiryo,{font_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,2,1,7,10,10,10,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for ev in events:
        if ev.moving:
            tag = fr"{{\an7\move({ev.x_start},{ev.y},{ev.x_end},{ev.y})\c{ass_color(ev.color)}}}"
        else:
            alignment = "9" if ev.align_right else "7"
            tag = fr"{{\an{alignment}\pos({ev.x_start},{ev.y})\c{ass_color(ev.color)}}}"
        lines.append(f"Dialogue: 0,{ass_timestamp(ev.at)},{ass_timestamp(ev.end)},Default,,0,0,0,,{tag}{ev.text}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return len(events), collision_count



def render_exact_preview_frame(
    video: Path, chat: Path, out: Path, *, settings: CommentSettings, style: str,
    start_seconds: float, frame_seconds: float = 5.0,
    width: int = 640, height: int = 360
) -> tuple[int, int, float]:
    """Render one real source frame with the same libass filter used for export."""
    ffmpeg = tool("ffmpeg")
    video_width, video_height, duration = video_metadata(video, tool("ffprobe"))
    start = parse_time(start_seconds)
    if duration is not None and start >= duration:
        raise ValueError("プレビュー開始位置が動画の終了時刻を超えています")
    frame = max(0.0, float(frame_seconds))
    if duration is not None:
        frame = min(frame, max(0.0, duration - start - 0.15))
    span = max(14.0, frame + 1.0)
    from app_paths import DATA_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fast_actual_preview_", dir=DATA_DIR) as temp:
        work = Path(temp)
        ass = work / "comments.ass"
        count, dropped = convert_chat_to_ass(
            chat, ass, video_width, video_height,
            Options(style, "right", span, start, settings)
        )
        select = format(frame, ".3f").rstrip("0").rstrip(".") or "0"
        video_filter = (
            f"setpts=PTS-STARTPTS,ass=comments.ass,"
            f"select='gte(t,{select})',scale={int(width)}:{int(height)}"
        )
        # Apply libass at every decoded frame, then select the chosen instant.
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error",
               "-ss", str(start), "-i", str(video), "-an",
               "-vf", video_filter, "-frames:v", "1", "-fps_mode", "vfr",
               "-y", str(out)]
        out.parent.mkdir(parents=True, exist_ok=True)
        execute(cmd, cwd=work, quiet=True)
        if not out.is_file() or out.stat().st_size == 0:
            raise RuntimeError("FFmpegでプレビュー画像を生成できませんでした")
    return count, dropped, frame





def render_sample_comment_preview(
    entries: list[dict], settings: CommentSettings, style: str,
    output_file: Path, *, frame_at: float = 5.0,
    source_width: int = 1280, source_height: int = 720,
    preview_width: int = 640, preview_height: int = 360
) -> int:
    """Render a genuine FFmpeg/libass still using demo comments; no VOD needed.

    Uses the exact same ASS creation/layout as normal video export. Renders at
    720p before downscaling to the GUI's 640x360 canvas.
    """
    if not 0.0 <= frame_at <= 10.0:
        raise ValueError("サンプルの表示時刻が不正です")
    ffmpeg = tool("ffmpeg")
    from app_paths import DATA_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fast_sample_still_", dir=DATA_DIR) as temp:
        work = Path(temp)
        sample_json = work / "demo.json"
        sample_json.write_text(json.dumps({"comments": entries}, ensure_ascii=False), encoding="utf-8")
        ass_path = work / "comments.ass"
        count, _ = convert_chat_to_ass(
            sample_json, ass_path, source_width, source_height,
            Options(style, "right", 12.0, 0.0, settings))
        # Decode a few seconds of a synthetic frame source. Applying ASS
        # before choosing the 5-second frame preserves real text positions.
        vf = ("setpts=PTS-STARTPTS,ass=comments.ass,"
              f"select='gte(t,{frame_at:g})',scale={preview_width}:{preview_height}")
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i",
            f"testsrc2=size={source_width}x{source_height}:rate=12:duration={frame_at + 0.5:g}",
            "-an", "-vf", vf, "-frames:v", "1",
            "-fps_mode", "vfr", "-y", "sample.png"
        ]
        result = subprocess.run(command, cwd=work, capture_output=True,
                                text=True, errors="replace", timeout=120,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode:
            raise RuntimeError("サンプル画像のFFmpeg描画に失敗しました: " + (result.stderr or "")[-900:])
        rendered = work / "sample.png"
        if not rendered.is_file() or rendered.stat().st_size == 0:
            raise RuntimeError("サンプル画像が作成されませんでした")
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_bytes(rendered.read_bytes())
        return count



def render_sample_video_preview(
    entries: list[dict], settings: CommentSettings, style: str, *,
    seconds: float = 8.0, fps: int = 12, width: int = 640, height: int = 360
) -> tuple[list[bytes], int, int]:
    """Return animated sample frames rendered by the *export* ASS/FFmpeg path.

    No user MP4 or Twitch chat is required. The generated scene moves while
    real ASS captions pass across it. Render at 1280x720 before downscaling,
    mirroring how full video exports use libass at video resolution.
    """
    if not (1.0 <= seconds <= 12.0 and 6 <= fps <= 24):
        raise ValueError("サンプル動画の秒数またはFPSが不正です")
    ffmpeg = tool("ffmpeg")
    from app_paths import DATA_DIR
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fast_sample_video_", dir=DATA_DIR) as tmp:
        work = Path(tmp)
        sample_json = work / "demo.json"
        sample_json.write_text(json.dumps({"comments": entries}, ensure_ascii=False), encoding="utf-8")
        ass_path = work / "comments.ass"
        count, _ = convert_chat_to_ass(
            sample_json, ass_path, 1280, 720,
            Options(style, "right", seconds, 0.0, settings)
        )
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i",
            f"testsrc2=size=1280x720:rate={fps}:duration={seconds:g}",
            "-an",
            "-vf", f"setpts=PTS-STARTPTS,ass=comments.ass,scale={width}:{height},format=rgb24",
            "-frames:v", str(math.ceil(seconds * fps)),
            "-y", "frame_%04d.png"
        ]
        completed = subprocess.run(
            command, cwd=work, capture_output=True, text=True,
            errors="replace", timeout=180,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
        if completed.returncode:
            raise RuntimeError(
                "サンプル動画の生成に失敗しました: " + (completed.stderr or "")[-900:])
        paths = sorted(work.glob("frame_*.png"))
        if not paths:
            raise RuntimeError("サンプル動画のフレームが生成されませんでした")
        return [p.read_bytes() for p in paths], fps, count


def encoder_candidates(ffmpeg: str, prefer: str) -> list[tuple[str, list[str]]]:
    if prefer == "cpu":
        return [("CPU/libx264", ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"])]
    # Pick only encoders listed in this FFmpeg build; runtime availability
    # depends on hardware/drivers, so failed attempts fall back automatically.
    known = execute([ffmpeg, "-hide_banner", "-encoders"], quiet=True).stdout
    candidates = [
        ("NVIDIA NVENC", "h264_nvenc", ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "24", "-b:v", "0"]),
        ("Intel QuickSync", "h264_qsv", ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "25"]),
        ("AMD AMF", "h264_amf", ["-c:v", "h264_amf", "-quality", "speed", "-b:v", "8M"]),
    ]
    available = [(label, flags) for label, enc, flags in candidates if re.search(r"\b" + enc + r"\b", known)]
    cpu = ("CPU/libx264", ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"])
    if prefer == "gpu":
        return available + [cpu]
    return available + [cpu]


def finalize_output(source: Path, destination: Path) -> None:
    """Publish an encoded video safely, including across different Windows drives.

    Path.replace cannot move C: -> D: on Windows (WinError 17).
    For cross-drive writes, copy into a unique temporary file next to the
    destination and only publish the completed file with a final rename.
    """
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError(f"書き出した動画がありません: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"保存先のファイルが既に存在します: {destination}")

    try:
        source.replace(destination)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV and getattr(exc, "winerror", None) != 17:
            raise

    print("[INFO] 保存先が別ドライブのため、完成動画をコピーしてから確定します。", flush=True)
    with tempfile.NamedTemporaryFile(
        prefix=".fastcomment_copy_", suffix=destination.suffix,
        dir=destination.parent, delete=False
    ) as handle:
        staging = Path(handle.name)
    try:
        shutil.copy2(source, staging)
        if staging.stat().st_size != source.stat().st_size or staging.stat().st_size == 0:
            raise OSError("コピー後のファイルサイズが一致しません")
        if destination.exists():
            raise FileExistsError(f"保存先のファイルが既に存在します: {destination}")
        staging.replace(destination)
        source.unlink(missing_ok=True)
    finally:
        staging.unlink(missing_ok=True)


def render(ffmpeg: str, source: Path, ass: Path, dest: Path, work: Path,
           *, mode: str, prefer: str, normalize_audio: bool,
           preview_seconds: float | None, preview_start: float = 0.0) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if mode == "soft":
        temp_dest = work / "soft_result.mkv"
        command = [ffmpeg, "-hide_banner", "-nostats", "-progress", "pipe:1"]
        if preview_start:
            command += ["-ss", str(preview_start)]
        command += ["-i", str(source), "-i", str(ass),
                   "-map", "0:v:0", "-map", "0:a?", "-map", "1:0", "-c:v", "copy", "-c:a", "copy",
                   "-c:s", "ass", "-metadata:s:s:0", "language=jpn", "-disposition:s:0", "default"]
        if preview_seconds:
            command.extend(["-t", str(preview_seconds)])
        execute(command + ["-y", str(temp_dest)], cwd=work)
        if not temp_dest.exists() or temp_dest.stat().st_size == 0:
            raise ValueError("MKVが空です")
        finalize_output(temp_dest, dest)
        return "映像・音声は無劣化コピー（字幕は対応プレイヤーのみ表示）"

    filters = execute([ffmpeg, "-hide_banner", "-filters"], quiet=True).stdout
    if not re.search(r"\bass\s+V->V", filters):
        raise RuntimeError("FFmpegにass字幕フィルタ（libass）がありません。字幕対応版FFmpegが必要です")
    # Use a local ASCII-only filename and cwd, avoiding FFmpeg's special
    # escaping requirements for Windows drives and Japanese output paths.
    staged_ass = work / "comments.ass"
    if ass != staged_ass:
        shutil.copy2(ass, staged_ass)
    base = [ffmpeg, "-hide_banner", "-nostats", "-progress", "pipe:1"]
    if preview_start:
        # Input seeking saves decoding hours of video for a late preview.
        base += ["-ss", str(preview_start)]
    base += ["-i", str(source), "-map", "0:v:0", "-map", "0:a?",
             "-vf", "ass=comments.ass", "-pix_fmt", "yuv420p"]
    if normalize_audio:
        base += ["-c:a", "aac", "-b:a", "192k", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000"]
    else:
        base += ["-c:a", "copy"]
    if preview_seconds:
        base.extend(["-t", str(preview_seconds)])
    errors = []
    for label, flags in encoder_candidates(ffmpeg, prefer):
        temp_dest = work / "burn_result.mp4"
        temp_dest.unlink(missing_ok=True)
        try:
            print(f"\nエンコード方式: {label}", flush=True)
            execute(base + flags + ["-movflags", "+faststart", "-y", str(temp_dest)], cwd=work)
            video_metadata(temp_dest, tool("ffprobe"))
        except (subprocess.CalledProcessError, ValueError, OSError) as exc:
            errors.append(f"{label}: {exc}")
            temp_dest.unlink(missing_ok=True)
            if label != "CPU/libx264":
                print("[WARN] GPUエンコード失敗。次の方式に切り替えます。")
            continue
        # An output-disk failure must not waste time retrying other encoders.
        finalize_output(temp_dest, dest)
        return label
    raise RuntimeError("すべてのエンコード方式が失敗しました。\n" + "\n".join(errors))


def output_path(chat: Path, vod_id: str, style: str, mode: str, preview: float | None, preview_start: float = 0.0, output_dir: Path | None = None) -> Path:
    data = json.loads(chat.read_text(encoding="utf-8-sig"))
    streamer = safe_name(str((data.get("streamer") or {}).get("name") or "unknown"))
    video = data.get("video") or {}
    date = safe_name(str(video.get("created_at") or "unknown")[:10])
    title = safe_name(str(video.get("title") or vod_id))
    folder = (resolve_output_directory(output_dir) if output_dir is not None else OUTPUT) / streamer
    stem = f"{date}_{title}_{vod_id}_{style}_fast" + (f"_PREVIEW_{int(preview_start):06}s" if preview else "")
    suffix = ".mkv" if mode == "soft" else ".mp4"
    dest = folder / (stem + suffix)
    index = 2
    while dest.exists():
        dest = folder / f"{stem}_{index}{suffix}"
        index += 1
    return dest


def process(vod_id: str, *, video: Path | None, chat: Path | None, style: str,
            position: str, mode: str, prefer: str, normalize_audio: bool,
            preview_seconds: float | None, preview_start: float = 0.0,
            auto_preview: bool = False, settings: CommentSettings | None = None,
            output_dir: Path | None = None, cache_dir: Path | None = None,
            work_dir: Path | None = None) -> Path:
    if not vod_id and (video is None or chat is None):
        raise ValueError("動画またはJSONが不足している場合はVOD IDを入力してください")
    if not vod_id:
        # Local-only workflows must not depend on a Twitch video ID.
        vod_id = "local"
    ffmpeg = tool("ffmpeg")
    ffprobe = tool("ffprobe")
    cli = tool("TwitchDownloaderCLI") if video is None or chat is None else None
    cache_root = resolve_output_directory(cache_dir) if cache_dir is not None else CACHE
    cache_root.mkdir(parents=True, exist_ok=True)
    if video is not None:
        video = video.expanduser().resolve()
    if chat is not None:
        chat = chat.expanduser().resolve()
    if video is None:
        video = download(cli or tool("TwitchDownloaderCLI"), "videodownload", vod_id, cache_root / f"{vod_id}.mp4", ffprobe)
    if chat is None:
        chat = download(cli or tool("TwitchDownloaderCLI"), "chatdownload", vod_id, cache_root / f"{vod_id}.json")
    w, h, duration = video_metadata(video, ffprobe)
    print(f"動画: {w}x{h}  時間: {duration or '不明'}秒  サイズ: {video.stat().st_size / 1024 ** 2:.1f}MB")
    if auto_preview:
        if preview_seconds is None:
            raise ValueError("コメントの多い区間の自動選択にはプレビュー時間が必要です")
        preview_start, expected_count = suggest_preview_start(chat, preview_seconds, duration)
        print(f"[OK] コメントの多い区間を自動選択: {pretty_time(preview_start)} 付近（{expected_count}件）")
    if preview_seconds is not None:
        if mode == "soft" and preview_start > 0:
            raise ValueError("MKV無劣化コピーで動画途中から切り出すと開始位置がずれるため非対応です。途中からの30秒テストにはMP4焼き込みを選んでください。")
        if not 0 < preview_seconds <= 3600:
            raise ValueError("プレビュー時間は0秒より大きく、3600秒以内にしてください")
        if duration is not None and preview_start >= duration:
            raise ValueError(f"開始位置 {pretty_time(preview_start)} は動画の長さ {pretty_time(duration)} を超えています")
        print(f"[OK] テスト範囲: {pretty_time(preview_start)} から {preview_seconds:g}秒")
    elif preview_start:
        raise ValueError("開始位置の指定にはプレビューを有効にしてください")
    # Avoid filling C: with gigabytes of intermediate video when output is on D:.
    work_root = (resolve_output_directory(work_dir) if work_dir is not None else
                 work_directory_for_output(output_dir if output_dir is not None else OUTPUT))
    work_root.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(work_root).free
    if free < 512 * 1024 ** 2:
        raise OSError(f"作業先の空き容量が512MB未満です: {work_root}。保存先を変更してください")
    if preview_seconds is None and video.stat().st_size > free * 0.8:
        print(f"[WARN] 完成動画と作業用に空き容量が不足する可能性があります: 残り {free / 1024**3:.1f} GB", flush=True)
    print(f"[INFO] 一時動画の保存先: {work_root}", flush=True)
    with tempfile.TemporaryDirectory(prefix="fast_comments_", dir=work_root) as temp:
        work = Path(temp)
        ass = work / "comments.ass"
        count, overlaps = convert_chat_to_ass(chat, ass, w, h, Options(style, position, preview_seconds, preview_start, settings or CommentSettings()))
        kind = "間引き" if (settings and settings.collision == "skip") else "重なりの可能性"
        print(f"字幕: {count}件（混雑時の{kind}: {overlaps}件）")
        dest = output_path(chat, vod_id, style, mode, preview_seconds, preview_start, output_dir=output_dir)
        label = render(ffmpeg, video, ass, dest, work, mode=mode, prefer=prefer,
                       normalize_audio=normalize_audio, preview_seconds=preview_seconds,
                       preview_start=preview_start)
        print(f"\n[OK] 完成: {dest}\n[OK] 処理方式: {label}\n")
        return dest


def yn(question: str, default: bool = False) -> bool:
    hint = "Y/n" if default else "y/N"
    answer = input(f"{question} [{hint}]: ").strip().lower()
    return default if not answer else answer in {"y", "yes", "1"}


def choose(question: str, choices: dict[str, str], default: str) -> str:
    while True:
        print(question)
        for key, label in choices.items():
            print(f"  {key}: {label}" + (" (既定)" if key == default else ""))
        answer = input("番号: ").strip() or default
        if answer in choices:
            return answer
        print("番号が正しくありません")


def file_picker(title: str, types: list[tuple[str, str]]) -> str:
    """Show native file chooser via tkinter or Windows Forms (no packages)."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            return filedialog.askopenfilename(title=title, filetypes=types, parent=root) or ""
        finally:
            root.destroy()
    except Exception:
        # tkinter may be present but unavailable (for example no display).
        pass
    if os.name == "nt":
        # Windows PowerShell 5.1 can present OpenFileDialog without tkinter.
        powershell = shutil.which("powershell.exe")
        if powershell:
            filters = "|".join(f"{label}|{pattern}" for label, pattern in types)
            script = ("Add-Type -AssemblyName System.Windows.Forms; "
                      "$dlg=New-Object System.Windows.Forms.OpenFileDialog; "
                      "$dlg.Title=" + "'" + title.replace("'", "''") + "'; "
                      "$dlg.Filter=" + "'" + filters.replace("'", "''") + "'; "
                      "if($dlg.ShowDialog() -eq 'OK'){[Console]::Write($dlg.FileName)}")
            proc = subprocess.run([powershell, "-NoProfile", "-STA", "-Command", script],
                                  capture_output=True, text=True, errors="replace")
            if proc.returncode == 0:
                return proc.stdout.strip()
    raise RuntimeError("ファイル選択画面を開けませんでした。PythonのtkinterまたはWindows PowerShellを確認してください")


def interactive() -> argparse.Namespace:
    print("=" * 56)
    print("  FastComment  1.2（ライブプレビュー・配色設定対応）")
    print("=" * 56)
    vod_id = normalize_id(input("Twitch VOD ID またはアーカイブURL: "))
    existing = file_picker("既存の動画を選択（キャンセルでダウンロード）", [("動画ファイル", "*.mp4;*.mkv;*.mov;*.m4v"), ("すべてのファイル", "*.*")])
    video = Path(existing).expanduser().resolve() if existing else None
    chat = None
    if yn("取得済みチャットJSONを手元から選択しますか？", False):
        existing_chat = file_picker("チャットJSONを選択", [("JSONファイル", "*.json"), ("すべてのファイル", "*.*")])
        chat = Path(existing_chat).expanduser().resolve() if existing_chat else None
    style_index = choose("コメント表示方式", {"1": "ニコニコ風・横に流れる", "2": "Twitch風・横に固定表示（簡易）"}, "1")
    style = {"1": "nico", "2": "twitch"}[style_index]
    position = "right"
    if style == "twitch":
        position = "left" if choose("表示位置", {"1": "左側", "2": "右側"}, "2") == "1" else "right"
    mode = "soft" if choose("出力方式", {"1": "MP4にコメントを焼き込み（投稿用）", "2": "MKVに切替式字幕を付与（最速・再エンコードなし）"}, "1") == "2" else "burn"
    prefer = "auto"
    norm = False
    if mode == "burn":
        prefer = {"1": "auto", "2": "cpu"}[choose("エンコード設定", {"1": "GPU優先（失敗時CPU）", "2": "CPUだけ"}, "1")]
        norm = yn("音量ノーマライズを実行しますか？（追加の音声処理は同じパスで実施）")
    preview = 30.0 if yn("30秒のテスト動画を作成しますか？", True) else None
    auto_preview = False
    preview_start = 0.0
    if preview is not None:
        pick = choose("30秒テストを開始する位置", {"1": "コメントが多い区間を自動で選ぶ", "2": "時:分:秒を手入力", "3": "最初から"}, "1")
        auto_preview = (pick == "1")
        if pick == "2":
            preview_start = parse_time(input("開始位置（例 01:25:00）: "))
    return argparse.Namespace(vod=vod_id, video=video, chat=chat, style=style,
                              position=position, mode=mode, encoder=prefer,
                              normalize=norm, preview_seconds=preview,
                              preview_start=preview_start, auto_preview=auto_preview)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TwitchコメントをASS字幕化し、高速に合成")
    parser.add_argument("--vod", help="Twitchアーカイブ動画ID/URL")
    parser.add_argument("--video", type=Path, help="取得済みMP4（再ダウンロードを省略）")
    parser.add_argument("--chat", type=Path, help="取得済みチャットJSON（再ダウンロードを省略）")
    parser.add_argument("--style", choices=["nico", "twitch"], default="nico")
    parser.add_argument("--position", choices=["left", "right"], default="right")
    parser.add_argument("--mode", choices=["burn", "soft"], default="burn")
    parser.add_argument("--encoder", choices=["auto", "gpu", "cpu"], default="auto")
    parser.add_argument("--normalize", action="store_true")
    parser.add_argument("--preview-seconds", type=float, default=None)
    parser.add_argument("--preview-start", default="0", help="プレビュー開始位置。例 01:15:00 または秒数")
    parser.add_argument("--auto-preview", action="store_true", help="コメントの多い区間からプレビュー")
    parser.add_argument("--settings", type=Path, default=SETTINGS_FILE, help="GUIのコメント表示設定JSON")
    parser.add_argument("--output-dir", type=Path, help="完成動画の保存先フォルダ（配信者別に分類）")
    parser.add_argument("--cache-dir", type=Path, help="動画MP4とチャットJSONの再利用キャッシュ保存先")
    parser.add_argument("--work-dir", type=Path, help="エンコードの一時作業ファイルの場所")
    supplied = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(supplied) if supplied else interactive()
    if not args.vod and (not args.video or not args.chat):
        parser.error("--vod が必要です（動画とJSON両方指定の場合のみ省略可）")
    vod_id = normalize_id(args.vod) if args.vod else ""
    if not hasattr(args, "settings"):
        args.settings = SETTINGS_FILE
    if args.mode == "soft" and args.normalize:
        print("[ERROR] MKV無劣化コピー方式では音量ノーマライズできません。--normalizeを外すか--mode burnを選んでください。")
        return 1
    started = time.monotonic()
    try:
        path = process(vod_id, video=args.video, chat=args.chat, style=args.style,
                       position=args.position, mode=args.mode, prefer=args.encoder,
                       normalize_audio=args.normalize, preview_seconds=args.preview_seconds,
                       preview_start=parse_time(args.preview_start), auto_preview=args.auto_preview,
                       settings=load_comment_settings(args.settings),
                       output_dir=getattr(args, "output_dir", None),
                       cache_dir=getattr(args, "cache_dir", None),
                       work_dir=getattr(args, "work_dir", None))
        print(f"処理時間: {time.monotonic() - started:.1f}秒")
        print(f"完成動画: {path}")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"\n[ERROR] 処理に失敗しました: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
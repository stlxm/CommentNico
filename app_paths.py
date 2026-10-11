"""Paths for source development and a portable Windows release.

Executable/bundled tools belong together; user content is stored outside the app.
"""
from __future__ import annotations
import os
import shutil
import sys
import json
from dataclasses import dataclass
from pathlib import Path

APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DATA_DIR = Path(os.environ["FASTCOMMENT_DATA_DIR"]).expanduser().resolve() if os.environ.get("FASTCOMMENT_DATA_DIR") else (Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "FastComment")
CACHE_DIR = DATA_DIR / "Originals"
OUTPUT_DIR = DATA_DIR / "Output"
SETTINGS_FILE = DATA_DIR / "comment_settings.json"
LOG_DIR = DATA_DIR / "logs"
OUTPUT_PREFERENCES_FILE = DATA_DIR / "output_preferences.json"


def resolve_output_directory(value: str | Path) -> Path:
    """Resolve a user-selected destination without changing or creating it."""
    if not str(value).strip():
        raise ValueError("出力先フォルダを選択してください")
    path = Path(value).expanduser().resolve()
    if path.exists() and not path.is_dir():
        raise ValueError(f"出力先がフォルダではありません: {path}")
    return path


@dataclass
class OutputPreferences:
    directory: str = str(OUTPUT_DIR)
    open_on_complete: bool = True


def load_output_preferences(path: Path = OUTPUT_PREFERENCES_FILE) -> OutputPreferences:
    if not path.is_file():
        return OutputPreferences()
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("出力先設定の形式が正しくありません")
    directory = data.get("directory", str(OUTPUT_DIR))
    auto_open = data.get("open_on_complete", True)
    if not isinstance(directory, str) or not isinstance(auto_open, bool):
        raise ValueError("出力先設定の値が正しくありません")
    return OutputPreferences(str(resolve_output_directory(directory)), auto_open)


def save_output_preferences(prefs: OutputPreferences, path: Path = OUTPUT_PREFERENCES_FILE) -> None:
    directory = resolve_output_directory(prefs.directory)
    if not isinstance(prefs.open_on_complete, bool):
        raise ValueError("自動でフォルダを開く設定が不正です")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(
        {"directory": str(directory), "open_on_complete": prefs.open_on_complete},
        ensure_ascii=False, indent=2
    ) + "\n", encoding="utf-8")
    temporary.replace(path)



def completed_output_folder(completed_file: Path | None, directory: str | Path) -> Path:
    """Open the actual streamer subfolder when the completed video is known."""
    if completed_file is not None and completed_file.is_file():
        return completed_file.parent
    return resolve_output_directory(directory)


def executable(name: str) -> str:
    """Use bundled copies first; never search an adjacent legacy Saccubus install."""
    names = (name + ".exe", name) if not name.endswith(".exe") else (name,)
    for folder in (APP_DIR / "tools", APP_DIR):
        for fname in names:
            candidate = folder / fname
            if candidate.is_file():
                return str(candidate)
    # Source-only development can rely on explicit PATH, but frozen release must be independent.
    if not getattr(sys, "frozen", False):
        found = shutil.which(name) or shutil.which(name + ".exe")
        if found:
            return found
    raise FileNotFoundError(f"{name} が見つかりません。{APP_DIR / 'tools'} にexeを配置してください")


def worker_command() -> list[str]:
    """Packaged windowed GUI starts a separate console-enabled background worker."""
    if getattr(sys, "frozen", False):
        exe = APP_DIR / "FastCommentWorker.exe"
        if not exe.is_file():
            raise FileNotFoundError(f"変換用プログラムがありません: {exe}")
        return [str(exe)]
    return [sys.executable, "-u", str(APP_DIR / "fast_comment.py")]
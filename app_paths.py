"""Paths for source development and a portable Windows release.

Executable/bundled tools belong together; user content is stored outside the app.
"""
from __future__ import annotations
import os
import shutil
import sys
from pathlib import Path

APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DATA_DIR = Path(os.environ["FASTCOMMENT_DATA_DIR"]).expanduser().resolve() if os.environ.get("FASTCOMMENT_DATA_DIR") else (Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "FastComment")
CACHE_DIR = DATA_DIR / "Originals"
OUTPUT_DIR = DATA_DIR / "Output"
SETTINGS_FILE = DATA_DIR / "comment_settings.json"
LOG_DIR = DATA_DIR / "logs"


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
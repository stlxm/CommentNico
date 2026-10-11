"""FastComment 2.0: Windows GUI with live, encoder-free comment preview.

The canvas uses the same layout_comments() model as exported ASS subtitles.
Tk previews approximate font rasterization; actual 30-second exports are authoritative.
"""
from __future__ import annotations

import json
import re
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict
from pathlib import Path

import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

import fast_comment as core
from job_control import remaining_seconds, format_duration
from app_paths import (APP_DIR, CACHE_DIR, OUTPUT_DIR, SETTINGS_FILE, worker_command,
                       OutputPreferences, load_output_preferences, save_output_preferences,
                       resolve_output_directory, completed_output_folder,
                       StoragePreferences, load_storage_preferences, save_storage_preferences,
                       work_directory_for_output)

HERE = APP_DIR
SETTINGS_PATH = SETTINGS_FILE
SAMPLE = [
    (0.2, "mabi_fan", "わー！ こんにちは！"),
    (1.3, "game_love", "ナイス！すごい！！"),
    (2.4, "neko_55", "今日も配信ありがとう 😊"),
    (3.8, "mabi_fan", "コメントが右から流れるよ～"),
    (5.0, "viewer_a", "888888888"),
    (5.2, "viewer_b", "ここ好きｗｗｗ"),
    (6.0, "game_love", "色や速さを変えてみよう"),
    (7.2, "neko_55", "ファイト～！！"),
    (8.6, "viewer_b", "ちょうどいいサイズかな？"),
    (10.0, "mabi_fan", "ニコニコ風コメント"),
]
SAMPLE_ENTRIES = [{"content_offset_seconds": t, "commenter": {"name": name, "display_name": name},
                   "message": {"body": msg, "user_color": ["#FFBC58", "#93E4FF", "#A8FF9C"][i % 3]}}
                  for i, (t, name, msg) in enumerate(SAMPLE)]
COLORS = {"twitch": "Twitchのユーザー色", "white": "全員白", "single": "全員同じ指定色",
          "account": "アカウント別・自動色", "manual": "アカウント別・手動指定"}


def sample_entries_for_settings(settings: core.CommentSettings) -> list[dict]:
    """Show registered per-user manual colors in the sample video too."""
    if settings.color_mode != "manual" or not settings.account_colors:
        return SAMPLE_ENTRIES
    accounts = sorted(settings.account_colors)[:len(SAMPLE_ENTRIES)]
    return [
        {**entry,
         "commenter": {"name": accounts[i % len(accounts)],
                       "display_name": accounts[i % len(accounts)]}}
        for i, entry in enumerate(SAMPLE_ENTRIES)
    ]


class FastCommentGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("FastComment 2.0 — ライブプレビュー付き高速コメント合成")
        # Keep the main action bar visible even on 1366x768 laptops or DPI-scaled monitors.
        available_w = max(780, root.winfo_screenwidth() - 60)
        available_h = max(540, root.winfo_screenheight() - 115)
        root.geometry(f"{min(1140, available_w)}x{min(840, available_h)}")
        root.minsize(min(780, available_w), min(540, available_h))
        try:
            output_prefs = load_output_preferences()
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            messagebox.showwarning("出力先設定の読み込み失敗", f"既定の出力先で起動します。\n{exc}")
            output_prefs = OutputPreferences()
        self.output_directory = tk.StringVar(value=output_prefs.directory)
        try:
            cache_prefs = load_storage_preferences()
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            messagebox.showwarning("元動画の保存先設定", f"既定の保存先で起動します。\n{exc}")
            cache_prefs = StoragePreferences()
        self.cache_directory = tk.StringVar(value=cache_prefs.cache_directory)
        self.open_on_complete = tk.BooleanVar(value=output_prefs.open_on_complete)
        self._completed_file: Path | None = None
        self.vod = tk.StringVar()
        self.video = tk.StringVar()
        self.chat = tk.StringVar()
        self.comment_offset = tk.StringVar(value="0")
        self.obs_event_time = tk.StringVar()
        self.twitch_event_time = tk.StringVar()
        self.style = tk.StringVar(value="nico")
        self.mode = tk.StringVar(value="burn")
        self.encoder = tk.StringVar(value="auto")
        self.normal = tk.BooleanVar(value=True)
        self.preview = tk.BooleanVar(value=True)
        self.time_mode = tk.StringVar(value="auto")
        self.start_time = tk.StringVar(value="00:00:00")
        self.status = tk.StringVar(value="準備完了 — 変換開始は上のボタンから")
        self.progress_percent = tk.StringVar(value="未開始")
        self.progress_detail = tk.StringVar(value="0% / 速度 -- / 残り時間 --")
        self.preview_note = tk.StringVar(value="サンプルコメントを再生中（エンコード不要）")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False
        self._cancel_event = threading.Event()
        self._total_seconds = None
        self._processed_seconds = 0.0
        self._last_speed = ""
        self.worker_process: subprocess.Popen | None = None
        self._settings_job = None
        self._preview_started = time.monotonic()
        self._preview_paused_at: float | None = None
        self._preview_image = None
        self._exact_preview_image = None
        self._exact_preview_active = False
        self._sample_preview_active = False
        self._sample_preview_pending = False
        self._sample_preview_generation = 0
        self._sample_preview_image = None
        self._sample_preview_frames: list[bytes] = []
        self._sample_preview_fps = 12
        self._sample_preview_index = -1
        self._sample_preview_job = None
        self._preview_frame_path: Path | None = None
        self._preview_real_entries = None
        self._preview_start = 0.0
        self._preview_span = 14.0
        self._preview_events = []
        try:
            settings = core.load_comment_settings(SETTINGS_PATH)
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            messagebox.showwarning("設定の読み込み失敗", f"設定を初期値で起動します。\n{exc}")
            settings = core.CommentSettings()
        self.font_size = tk.IntVar(value=settings.font_size)
        self.speed_percent = tk.IntVar(value=settings.speed_percent)
        self.row_gap = tk.DoubleVar(value=settings.row_gap)
        self.area_percent = tk.IntVar(value=settings.area_percent)
        self.collision = tk.StringVar(value=settings.collision)
        self.color_mode = tk.StringVar(value=settings.color_mode)
        self.single_color = settings.single_color
        self.account_colors = dict(settings.account_colors)
        self.selected_account_color = "#FFB44C"

        outer = ttk.Frame(root, padding=(14, 12))
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="FastComment 2.0", font=("Segoe UI", 19, "bold")).pack(anchor="w")
        ttk.Label(outer, text="高速コメント合成 ＋ 再エンコード不要のライブプレビュー", foreground="#525252").pack(anchor="w", pady=(0, 9))
        # Place critical controls ABOVE the notebook, independent of tab height.
        # The previous bottom footer was pushed below the visible window on
        # some high-DPI displays by the tall video/output form.
        toolbar = ttk.LabelFrame(outer, text="変換の操作・進捗", padding=(10, 8))
        toolbar.pack(fill="x", pady=(0, 8))
        controls = ttk.Frame(toolbar)
        controls.pack(fill="x")
        self.start_button = ttk.Button(controls, text="▶ 変換開始（30秒テスト／全編）", command=self.start)
        self.start_button.pack(side="right")
        self.cancel_button = ttk.Button(controls, text="■ 中止", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="right", padx=(0, 10))
        ttk.Label(controls, text="進捗", font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Label(controls, textvariable=self.progress_percent,
                  font=("Segoe UI", 18, "bold"), width=9).pack(side="left", padx=(10, 0))
        self.progressbar = ttk.Progressbar(toolbar, orient="horizontal",
                                           mode="determinate", maximum=100)
        self.progressbar.pack(fill="x", pady=(5, 3))
        detail = ttk.Frame(toolbar)
        detail.pack(fill="x")
        ttk.Label(detail, textvariable=self.progress_detail).pack(side="left")
        ttk.Label(detail, textvariable=self.status, foreground="#555").pack(side="right")

        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill="both", expand=True)
        self.tab_jobs = ttk.Frame(self.tabs)
        self.tab_appearance = ttk.Frame(self.tabs, padding=12)
        self.tab_logs = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(self.tab_jobs, text="  ① 動画・出力  ")
        self.tabs.add(self.tab_appearance, text="  ② コメント設定とプレビュー  ")
        self.tabs.add(self.tab_logs, text="  ③ 処理ログ  ")
        self._build_job_tab()
        self._build_appearance_tab()
        self._build_log_tab()

        for var in [self.font_size, self.speed_percent, self.row_gap, self.area_percent, self.collision, self.color_mode, self.style]:
            var.trace_add("write", lambda *_: self.settings_changed())
        self._sync_options()
        self._reset_preview_clock()
        self._rebuild_preview()
        root.after(40, self._animate_preview)
        root.after(100, self.poll)
        root.after(400, self.render_sample_preview)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    @staticmethod
    def _entry(parent, label, var, *, browse=None, hint=None):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=label, width=24).pack(side="left")
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
        if browse:
            ttk.Button(row, text="参照…", command=browse).pack(side="left", padx=(8, 0))
        if hint:
            ttk.Label(row, text=hint, foreground="#666").pack(side="left", padx=(6, 0))

    def _build_job_tab(self):
        # Scroll the lengthy settings form, not the essential controls above.
        viewport = ttk.Frame(self.tab_jobs)
        viewport.pack(fill="both", expand=True)
        canvas = tk.Canvas(viewport, highlightthickness=0, borderwidth=0)
        vertical = ttk.Scrollbar(viewport, orient="vertical", command=canvas.yview)
        vertical.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=vertical.set)
        frame = ttk.Frame(canvas, padding=12)
        window_id = canvas.create_window((0, 0), window=frame, anchor="nw")
        frame.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))
        self._job_scroll_canvas = canvas
        files = ttk.LabelFrame(frame, text="動画・コメントの取得", padding=12)
        files.pack(fill="x")
        self._entry(files, "VOD ID / URL", self.vod, hint="例：2896810049")
        self._entry(files, "取得済みの動画", self.video,
                    browse=lambda: self._browse(self.video, "動画を選択", [("動画", "*.mp4 *.mkv *.mov"), ("すべて", "*.*")]))
        self._entry(files, "取得済みのチャットJSON", self.chat,
                    browse=lambda: self._browse(self.chat, "コメントJSONを選択", [("JSON", "*.json"), ("すべて", "*.*")]))
        ttk.Label(files, text="※ 未指定なら Originals の取得済みファイルを再利用。なければ TwitchDownloaderCLI でダウンロードします。",
                  foreground="#555").pack(anchor="w", pady=(7, 0))
        sync = ttk.LabelFrame(frame, text="OBS録画とTwitchコメントの時刻合わせ", padding=12)
        sync.pack(fill="x", pady=(12, 0))
        offset_row = ttk.Frame(sync)
        offset_row.pack(fill="x")
        ttk.Label(offset_row, text="コメント時刻補正（秒）").pack(side="left")
        ttk.Entry(offset_row, textvariable=self.comment_offset, width=13).pack(side="left", padx=(12, 8))
        ttk.Button(offset_row, text="0に戻す", command=lambda: self.comment_offset.set("0")).pack(side="left")
        ttk.Label(sync, text="OBSの録画開始がTwitchより12秒早い → +12（コメントを遅らせる）",
                  foreground="#555").pack(anchor="w", pady=(6, 0))
        ttk.Label(sync, text="OBSの録画開始がTwitchより8秒遅い → -8（コメントを早める）。小数も可。",
                  foreground="#555").pack(anchor="w")
        ttk.Label(sync, text="同じ場面の時刻から自動計算（動画の音声や映像自体は解析しません）",
                  foreground="#555").pack(anchor="w", pady=(6, 2))
        times = ttk.Frame(sync)
        times.pack(fill="x", pady=2)
        ttk.Label(times, text="OBS側").pack(side="left")
        ttk.Entry(times, textvariable=self.obs_event_time, width=12).pack(side="left", padx=(5, 12))
        ttk.Label(times, text="Twitch側").pack(side="left")
        ttk.Entry(times, textvariable=self.twitch_event_time, width=12).pack(side="left", padx=(5, 12))
        ttk.Button(times, text="時刻差を計算", command=self.calculate_comment_offset).pack(side="left")
        ttk.Label(sync, text="例：同じ場面がOBS 00:04:20 / Twitch 00:04:05 → +15秒。",
                  foreground="#555").pack(anchor="w", pady=(2, 0))
        opts = ttk.LabelFrame(frame, text="出力設定", padding=12)
        opts.pack(fill="x", pady=(12, 0))
        r = ttk.Frame(opts)
        r.pack(fill="x", pady=5)
        ttk.Label(r, text="コメント表示", width=18).pack(side="left")
        ttk.Radiobutton(r, text="ニコニコ風（流れる）", variable=self.style, value="nico").pack(side="left", padx=(0, 20))
        ttk.Radiobutton(r, text="Twitch風（固定）", variable=self.style, value="twitch").pack(side="left")
        r = ttk.Frame(opts)
        r.pack(fill="x", pady=5)
        ttk.Label(r, text="ファイル形式", width=18).pack(side="left")
        ttk.Radiobutton(r, text="MP4（焼き込み）", variable=self.mode, value="burn", command=self._sync_options).pack(side="left", padx=(0, 20))
        ttk.Radiobutton(r, text="MKV（字幕・再エンコードなし）", variable=self.mode, value="soft", command=self._sync_options).pack(side="left")
        r = ttk.Frame(opts)
        r.pack(fill="x", pady=5)
        ttk.Label(r, text="エンコーダー", width=18).pack(side="left")
        self.encoder_box = ttk.Combobox(r, textvariable=self.encoder, values=("auto", "cpu"), state="readonly", width=12)
        self.encoder_box.pack(side="left")
        ttk.Label(r, text=" auto = NVIDIA GPU 優先（失敗時CPU）", foreground="#555").pack(side="left", padx=(8, 0))
        self.normal_control = ttk.Checkbutton(opts, text="音声ノーマライズを同時に実行（MP4のみ）", variable=self.normal)
        self.normal_control.pack(anchor="w", pady=6)
        dest_row = ttk.Frame(opts)
        dest_row.pack(fill="x", pady=4)
        ttk.Label(dest_row, text="出力先フォルダ", width=18).pack(side="left")
        ttk.Entry(dest_row, textvariable=self.output_directory).pack(side="left", fill="x", expand=True)
        ttk.Button(dest_row, text="参照…", command=self.browse_output_directory).pack(side="left", padx=(8, 0))
        ttk.Button(dest_row, text="保存", command=lambda: self.save_output_preferences(show=True)).pack(side="left", padx=(6, 0))
        ttk.Checkbutton(opts, text="変換が完了したら保存先フォルダを自動で開く",
                        variable=self.open_on_complete, command=self.save_output_preferences).pack(anchor="w", pady=(2, 0))
        cache_row = ttk.Frame(opts)
        cache_row.pack(fill="x", pady=4)
        ttk.Label(cache_row, text="元動画・JSON保存先", width=18).pack(side="left")
        ttk.Entry(cache_row, textvariable=self.cache_directory).pack(side="left", fill="x", expand=True)
        ttk.Button(cache_row, text="参照…", command=self.browse_cache_directory).pack(side="left", padx=(8, 0))
        ttk.Button(cache_row, text="保存", command=lambda: self.save_cache_preferences(show=True)).pack(side="left", padx=(6, 0))
        ttk.Label(opts, text="一時動画は完成動画と同じドライブで作成し、終了時に削除します。",
                  foreground="#555").pack(anchor="w")
        test = ttk.LabelFrame(frame, text="テスト範囲", padding=12)
        test.pack(fill="x", pady=(12, 0))
        ttk.Checkbutton(test, text="30秒だけ動画を書き出して確認（推奨）", variable=self.preview,
                        command=self._sync_options).pack(anchor="w")
        r = ttk.Frame(test)
        r.pack(fill="x", pady=6)
        self.time_controls = []
        for label, val in (("コメントの多い区間を自動選択", "auto"), ("時刻を指定", "manual"), ("動画の先頭", "first")):
            b = ttk.Radiobutton(r, text=label, variable=self.time_mode, value=val, command=self._sync_options)
            b.pack(side="left", padx=(0, 22))
            self.time_controls.append(b)
        r = ttk.Frame(test)
        r.pack(anchor="w", pady=5)
        ttk.Label(r, text="開始位置（時:分:秒）").pack(side="left")
        self.start_entry = ttk.Entry(r, textvariable=self.start_time, width=16)
        self.start_entry.pack(side="left", padx=10)
        ttk.Label(r, text="例：01:25:00", foreground="#555").pack(side="left")
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=12)
        ttk.Button(actions, text="🎨 コメント設定とライブプレビューへ", command=lambda: self.tabs.select(self.tab_appearance)).pack(side="left")
        ttk.Button(actions, text="出力フォルダを開く", command=self.open_output).pack(side="left", padx=12)
        ttk.Label(frame, text="「30秒プレビュー」は実際の動画ファイルを作るテストです。コメント設定タブのライブプレビューは変換なしで動きます。",
                  foreground="#555").pack(anchor="w")

    def calculate_comment_offset(self):
        """Populate the per-export offset from a shared OBS/Twitch scene."""
        try:
            value = core.offset_between_matching_events(
                self.obs_event_time.get(), self.twitch_event_time.get())
        except ValueError as exc:
            messagebox.showerror("時刻差の計算", str(exc))
            return
        self.comment_offset.set(f"{value:+g}" if value else "0")
        messagebox.showinfo("時刻差を設定しました",
                            f"コメント時刻補正: {value:+g}秒\\n"
                            "まず30秒テストで映像とコメントのタイミングを確認してください。")

    def _build_appearance_tab(self):
        pane = ttk.Panedwindow(self.tab_appearance, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left = ttk.Frame(pane, width=332)
        right = ttk.Frame(pane)
        pane.add(left, weight=0)
        pane.add(right, weight=1)
        ttk.Label(left, text="表示の調整", font=("Segoe UI", 13, "bold")).pack(anchor="w", pady=(0, 6))
        self._scale_control(left, "文字サイズ（720p換算）", self.font_size, 12, 65, "px")
        self._scale_control(left, "コメントの流れる速度", self.speed_percent, 40, 250, "%")
        self._scale_control(left, "行間・上下の余白", self.row_gap, 1.0, 2.6, "倍", resolution=0.1)
        self._scale_control(left, "コメントを使う画面の高さ", self.area_percent, 30, 95, "%")
        ttk.Label(left, text="混雑時の表示", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(7, 2))
        r = ttk.Frame(left)
        r.pack(anchor="w")
        ttk.Radiobutton(r, text="重なっても表示", variable=self.collision, value="overlap").pack(side="left")
        ttk.Radiobutton(r, text="重なるコメントは間引く", variable=self.collision, value="skip").pack(side="left", padx=(5, 0))
        ttk.Label(left, text="コメントの色", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(9, 3))
        cb = ttk.Combobox(left, values=list(COLORS.values()), state="readonly", width=29)
        cb.set(COLORS[self.color_mode.get()])
        self.color_mode.trace_add("write", lambda *_: cb.set(COLORS[self.color_mode.get()]))
        cb.pack(anchor="w", fill="x", padx=(0, 7))
        cb.bind("<<ComboboxSelected>>", lambda e: self.color_mode.set(next(k for k, v in COLORS.items() if v == cb.get())))
        self.color_pick_frame = ttk.Frame(left)
        self.color_pick_frame.pack(fill="x", pady=7)
        ttk.Button(self.color_pick_frame, text="🎨 全員の色を選択…", command=self.pick_single_color).pack(side="left")
        self.single_swatch = tk.Label(self.color_pick_frame, width=3, height=1, bg=self.single_color, relief="sunken")
        self.single_swatch.pack(side="left", padx=8)
        ttk.Label(left, text="アカウント別の手動カラー（任意）", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(4, 2))
        row = ttk.Frame(left)
        row.pack(fill="x")
        self.account_entry = ttk.Entry(row)
        self.account_entry.pack(side="left", fill="x", expand=True)
        self.account_entry.insert(0, "mabi_fan")
        ttk.Button(row, text="色…", command=self.pick_account_color).pack(side="left", padx=(6, 0))
        self.manual_swatch = tk.Label(row, width=3, bg=self.selected_account_color, relief="sunken")
        self.manual_swatch.pack(side="left", padx=7)
        r = ttk.Frame(left)
        r.pack(anchor="w", pady=5)
        ttk.Button(r, text="登録・更新", command=self.add_account_color).pack(side="left")
        ttk.Button(r, text="選択した色を削除", command=self.delete_account_color).pack(side="left", padx=(7, 0))
        self.account_list = tk.Listbox(left, height=4, exportselection=False)
        self.account_list.pack(fill="x", padx=(0, 7))
        self.account_list.bind("<<ListboxSelect>>", self.account_selected)
        self._refresh_accounts()
        ttk.Label(left, text="※ 色を適用するには『アカウント別・手動指定』を選択", foreground="#555").pack(anchor="w", pady=(2, 0))
        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=8)
        ttk.Button(btns, text="設定を保存", command=lambda: self.save_settings(show=True)).pack(side="left")
        ttk.Button(btns, text="初期値に戻す", command=self.reset_settings).pack(side="left", padx=8)

        ttk.Label(right, text="完成動画と同じ描画・サンプル動画", font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=10, pady=(0, 6))
        self.canvas = tk.Canvas(right, width=640, height=360, background="#111827", highlightthickness=1, highlightbackground="#444")
        self.canvas.pack(fill="both", expand=False, padx=10)
        self.canvas.bind("<Configure>", lambda e: self._redraw_background())
        ttk.Label(right, textvariable=self.preview_note, foreground="#525252", wraplength=645).pack(anchor="w", padx=10, pady=(7, 0))
        buttons = ttk.Frame(right)
        buttons.pack(fill="x", padx=10, pady=8)
        ttk.Button(buttons, text="▶ サンプル動画を再生・更新", command=self.render_sample_preview).pack(side="left")
        ttk.Button(buttons, text="実コメントから再生", command=self.load_real_comments).pack(side="left", padx=7)
        self.pause_button = ttk.Button(buttons, text="⏸ 一時停止", command=self.toggle_pause)
        self.pause_button.pack(side="left", padx=7)
        exact_actions = ttk.Frame(right)
        exact_actions.pack(fill="x", padx=10, pady=(0, 4))
        ttk.Button(exact_actions, text="実配信の1コマを確認（任意）", command=self.load_exact_preview).pack(side="left")
        ttk.Button(exact_actions, text="ライブ表示に戻す", command=self.return_live_preview).pack(side="left", padx=8)
        ttk.Button(right, text="選択済みMP4の1コマを背景に使う", command=self.load_video_background).pack(anchor="w", padx=10)
        ttk.Label(right, text="サンプル動画は書き出しと同じASS／FFmpegで描画します。文字のサイズ・色・縁取り・速さ・重なりを確認できます。設定変更で自動生成します。",
                  wraplength=640, foreground="#555").pack(anchor="w", padx=10, pady=10)
        self._redraw_background()

    def _scale_control(self, parent, label, variable, lower, upper, suffix, *, resolution=1):
        line = ttk.Frame(parent)
        line.pack(fill="x", pady=3)
        display = ttk.Label(line, text="", width=7)
        display.pack(side="right")
        ttk.Label(line, text=label).pack(side="left")
        scale = tk.Scale(parent, variable=variable, from_=lower, to=upper, orient="horizontal", resolution=resolution,
                         showvalue=False, length=290, highlightthickness=0, bd=0)
        scale.pack(fill="x", padx=(0, 8))
        def update(*_):
            value = variable.get()
            display.configure(text=f"{value:g}{suffix}")
        variable.trace_add("write", update)
        update()

    def _build_log_tab(self):
        ttk.Label(self.tab_logs, text="処理状況（進捗率は画面上部に常時表示）").pack(anchor="w")
        ttk.Label(self.tab_logs, text="通常は必要なメッセージのみ表示します。エラー時はFFmpegの診断情報を表示します。",
                  foreground="#555").pack(anchor="w", pady=(3, 0))
        box = ttk.Frame(self.tab_logs)
        box.pack(fill="both", expand=True, pady=8)
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        # Long FFmpeg command lines no longer wrap into dozens of fake log rows.
        self.log = tk.Text(box, wrap="none", font=("Consolas", 10), state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(box, orient="vertical", command=self.log.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(box, orient="horizontal", command=self.log.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.log.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)

    def _browse(self, variable, title, filetypes):
        path = filedialog.askopenfilename(parent=self.root, title=title, filetypes=filetypes)
        if path:
            variable.set(path)

    def browse_cache_directory(self):
        current = Path(self.cache_directory.get().strip()).expanduser()
        start = current if current.is_dir() else CACHE_DIR.parent
        chosen = filedialog.askdirectory(parent=self.root, title="元動画とJSONの保存先", initialdir=str(start))
        if chosen:
            self.cache_directory.set(chosen)
            self.save_cache_preferences()

    def save_cache_preferences(self, *, show=False):
        try:
            folder = resolve_output_directory(self.cache_directory.get())
            save_storage_preferences(StoragePreferences(str(folder)))
            if show:
                messagebox.showinfo("保存しました", "元動画とJSONの保存先を保存しました。既存の動画は移動しません。")
            return True
        except (ValueError, OSError) as exc:
            messagebox.showerror("元動画保存先の設定失敗", str(exc))
            return False

    def browse_output_directory(self):
        current = Path(self.output_directory.get().strip()).expanduser()
        start = current if current.is_dir() else OUTPUT_DIR.parent
        chosen = filedialog.askdirectory(parent=self.root, title="完成動画の保存先を選択",
                                          initialdir=str(start))
        if chosen:
            self.output_directory.set(chosen)
            self.save_output_preferences()

    def save_output_preferences(self, *, show=False):
        try:
            destination = resolve_output_directory(self.output_directory.get())
            save_output_preferences(OutputPreferences(str(destination), self.open_on_complete.get()))
            if show:
                messagebox.showinfo("保存しました", "出力先と自動で開く設定を保存しました。次回起動時にも使います。")
            return True
        except (ValueError, OSError) as exc:
            messagebox.showerror("出力先の保存失敗", str(exc))
            return False

    def _show_output_folder(self, folder: Path):
        if not folder.is_dir():
            raise FileNotFoundError(f"フォルダが見つかりません: {folder}")
        if os.name == "nt":
            os.startfile(str(folder))
        else:
            messagebox.showinfo("保存先", str(folder))

    def _sync_options(self):
        burn = self.mode.get() == "burn"
        self.encoder_box.configure(state="readonly" if burn else "disabled")
        self.normal_control.configure(state="normal" if burn else "disabled")
        for button in self.time_controls:
            button.configure(state="normal" if self.preview.get() else "disabled")
        self.start_entry.configure(state="normal" if self.preview.get() and self.time_mode.get() == "manual" else "disabled")

    def current_settings(self):
        return core.CommentSettings(font_size=self.font_size.get(), speed_percent=self.speed_percent.get(),
                                    row_gap=round(self.row_gap.get(), 2), area_percent=self.area_percent.get(),
                                    collision=self.collision.get(), color_mode=self.color_mode.get(),
                                    single_color=self.single_color, account_colors=dict(self.account_colors))

    def settings_changed(self):
        if self._settings_job is not None:
            self.root.after_cancel(self._settings_job)
        self._sample_preview_generation += 1
        self._sample_preview_pending = True
        self._sample_preview_active = False
        self._settings_job = self.root.after(200, self._apply_settings_change)
        if self._sample_preview_job is not None:
            self.root.after_cancel(self._sample_preview_job)
        self._sample_preview_job = self.root.after(700, self.render_sample_preview)
        self.preview_note.set("変更した設定でサンプル動画を再作成中…")

    def _apply_settings_change(self):
        self._settings_job = None
        self._rebuild_preview()
        self.save_settings()

    def save_settings(self, *, show=False):
        try:
            core.save_comment_settings(SETTINGS_PATH, self.current_settings())
            if show:
                messagebox.showinfo("保存しました", "コメント設定を保存しました。次回起動時も引き継ぎます。")
        except (ValueError, OSError) as exc:
            messagebox.showerror("保存失敗", str(exc))

    def reset_settings(self):
        if not messagebox.askyesno("初期値に戻す", "表示設定とアカウント別カラーを初期値に戻しますか？"):
            return
        cfg = core.CommentSettings()
        self.font_size.set(cfg.font_size)
        self.speed_percent.set(cfg.speed_percent)
        self.row_gap.set(cfg.row_gap)
        self.area_percent.set(cfg.area_percent)
        self.collision.set(cfg.collision)
        self.color_mode.set(cfg.color_mode)
        self.single_color = cfg.single_color
        self.single_swatch.configure(bg=self.single_color)
        self.account_colors.clear()
        self._refresh_accounts()
        self.settings_changed()

    def pick_single_color(self):
        chosen = colorchooser.askcolor(color=self.single_color, parent=self.root, title="全員のコメント色")
        if chosen[1]:
            self.single_color = chosen[1].upper()
            self.single_swatch.configure(bg=self.single_color)
            self.color_mode.set("single")
            self.settings_changed()

    def pick_account_color(self):
        chosen = colorchooser.askcolor(color=self.selected_account_color, parent=self.root, title="アカウントのコメント色")
        if chosen[1]:
            self.selected_account_color = chosen[1].upper()
            self.manual_swatch.configure(bg=self.selected_account_color)

    def add_account_color(self):
        name = self.account_entry.get().strip().casefold()
        if not name or len(name) > 64:
            messagebox.showerror("入力エラー", "アカウント名は1～64文字で入力してください")
            return
        self.account_colors[name] = self.selected_account_color
        self.color_mode.set("manual")
        self._refresh_accounts()
        self.settings_changed()

    def delete_account_color(self):
        picks = self.account_list.curselection()
        if not picks:
            return
        name = self.account_list.get(picks[0]).split("  →  ", 1)[0]
        self.account_colors.pop(name, None)
        self._refresh_accounts()
        self.settings_changed()

    def account_selected(self, _):
        picks = self.account_list.curselection()
        if not picks:
            return
        name = self.account_list.get(picks[0]).split("  →  ", 1)[0]
        self.account_entry.delete(0, "end")
        self.account_entry.insert(0, name)
        self.selected_account_color = self.account_colors.get(name, "#FFFFFF")
        self.manual_swatch.configure(bg=self.selected_account_color)

    def _refresh_accounts(self):
        self.account_list.delete(0, "end")
        for name, color in sorted(self.account_colors.items()):
            self.account_list.insert("end", f"{name}  →  {color}")

    def _reset_preview_clock(self):
        self._preview_started = time.monotonic()
        self._preview_paused_at = None
        if hasattr(self, "pause_button"):
            self.pause_button.configure(text="⏸ 一時停止")

    def _rebuild_preview(self):
        entries = SAMPLE_ENTRIES if self._preview_real_entries is None else self._preview_real_entries
        start = 0.0 if self._preview_real_entries is None else self._preview_start
        try:
            offset = core.parse_comment_offset(self.comment_offset.get()) if self._preview_real_entries is not None else 0.0
        except ValueError:
            offset = 0.0  # Input validation happens before actual preview/export.
        opts = core.Options(self.style.get(), "right", self._preview_span, start, self.current_settings(), offset)
        self._preview_events, dropped = core.layout_comments(entries, 1280, 720, opts)
        if dropped and self.collision.get() == "skip":
            self.preview_note.set(f"表示コメント {len(self._preview_events)}件（混雑のため {dropped}件間引き）")

    def show_sample(self):
        self.return_live_preview()
        self._preview_real_entries = None
        self._preview_span = 14.0
        self.preview_note.set("サンプルコメントを再生中（エンコード不要・変更を即時反映）")
        self._reset_preview_clock()
        self._rebuild_preview()

    def load_real_comments(self):
        self.return_live_preview()
        path = Path(self.chat.get().strip()) if self.chat.get().strip() else None
        if path is None:
            try:
                vod = core.normalize_id(self.vod.get())
                path = resolve_output_directory(self.cache_directory.get()) / (vod + ".json")
            except ValueError:
                path = None
        if path is None or not path.is_file():
            messagebox.showinfo("コメントJSONが必要です", "先に動画・出力タブでVOD IDを入力するか、既存のチャットJSONを『参照…』から選択してください。\n取得済みなら Originals のキャッシュを利用します。")
            return
        self.preview_note.set("コメントJSONを読み込み中…")
        chosen_mode = self.time_mode.get()
        chosen_time = self.start_time.get()
        try:
            offset = core.parse_comment_offset(self.comment_offset.get())
        except ValueError as exc:
            messagebox.showerror("時刻補正の入力", str(exc))
            return
        def job():
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                comments = data.get("comments")
                if not isinstance(comments, list):
                    raise ValueError("commentsの形式が不正です")
                if chosen_mode == "manual":
                    start = core.parse_time(chosen_time)
                elif chosen_mode == "first":
                    start = 0.0
                else:
                    start, _ = core.suggest_preview_start(path, 30.0, None, offset)
                window = [e for e in comments if isinstance(e, dict)
                          and start <= core._comment_sort_time(e) + offset < start + 14.0]
                self.events.put(("preview_loaded", (window, start, path.name)))
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                self.events.put(("preview_error", str(exc)))
        threading.Thread(target=job, daemon=True).start()

    def return_live_preview(self):
        had_image = self._exact_preview_active or self._sample_preview_active
        if self._sample_preview_job is not None:
            self.root.after_cancel(self._sample_preview_job)
            self._sample_preview_job = None
        self._exact_preview_active = False
        self._sample_preview_active = False
        self._sample_preview_pending = False
        self._sample_preview_frames = []
        self._sample_preview_index = -1
        self._sample_preview_generation += 1
        if had_image:
            self._redraw_background()
            self.preview_note.set("軽量プレビュー。正確な描画は「サンプル画像を更新」で確認してください")
            self._reset_preview_clock()

    def render_sample_preview(self):
        """Generate a moving example using the same FFmpeg ASS overlay as exports."""
        self._sample_preview_job = None
        self._sample_preview_generation += 1
        generation = self._sample_preview_generation
        style = self.style.get()
        cfg = self.current_settings()
        self._sample_preview_pending = True
        self._sample_preview_active = False
        self._exact_preview_active = False
        self.preview_note.set("FFmpegで8秒間のサンプル動画を生成中…")
        def job():
            try:
                frames, fps, count = core.render_sample_video_preview(sample_entries_for_settings(cfg), cfg, style)
                self.events.put(("sample_preview_loaded", (generation, frames, fps, count)))
            except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                self.events.put(("sample_preview_error", (generation, str(exc))))
        threading.Thread(target=job, daemon=True).start()

    def load_exact_preview(self):
        """Display one genuine libass-composited video frame in a worker thread."""
        try:
            video = Path(self.video.get().strip()) if self.video.get().strip() else None
            chat = Path(self.chat.get().strip()) if self.chat.get().strip() else None
            if video is None or chat is None:
                vod_id = core.normalize_id(self.vod.get())
                if video is None:
                    video = resolve_output_directory(self.cache_directory.get()) / (vod_id + ".mp4")
                if chat is None:
                    chat = resolve_output_directory(self.cache_directory.get()) / (vod_id + ".json")
            if not video.is_file() or not chat.is_file():
                raise ValueError("実描画にはダウンロード済みの動画とチャットJSONが必要です。動画・出力タブで指定するか、先に30秒テストを実行してください。")
            requested_time = self.start_time.get()
            mode = self.time_mode.get()
            appearance = self.current_settings()
            style = self.style.get()
            offset = core.parse_comment_offset(self.comment_offset.get())
        except (ValueError, OSError) as exc:
            messagebox.showinfo("実描画プレビュー", str(exc))
            return
        self.preview_note.set("FFmpegで実際のコメントの描画を確認中…")
        def job():
            try:
                if mode == "manual":
                    start = core.parse_time(requested_time)
                elif mode == "first":
                    start = 0.0
                else:
                    _, _, duration = core.video_metadata(video, core.tool("ffprobe"))
                    start, _ = core.suggest_preview_start(chat, 30.0, duration, offset)
                with tempfile.TemporaryDirectory(prefix="fast_exact_frame_") as tmp:
                    frame_path = Path(tmp) / "frame.png"
                    count, dropped, frame_seconds = core.render_exact_preview_frame(
                        video, chat, frame_path, settings=appearance, style=style,
                        start_seconds=start, comment_offset_seconds=offset)
                    self.events.put(("exact_preview_loaded",
                                     (frame_path.read_bytes(), start + frame_seconds, count, dropped)))
            except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
                self.events.put(("preview_error", f"FFmpegでの実描画に失敗しました: {exc}"))
        threading.Thread(target=job, daemon=True).start()

    def toggle_pause(self):
        if self._preview_paused_at is None:
            self._preview_paused_at = time.monotonic()
            self.pause_button.configure(text="▶ 再開")
        else:
            self._preview_started += time.monotonic() - self._preview_paused_at
            self._preview_paused_at = None
            self.pause_button.configure(text="⏸ 一時停止")

    def _redraw_background(self):
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("background")
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        if self._sample_preview_active and self._sample_preview_image:
            self.canvas.create_image(0, 0, image=self._sample_preview_image, anchor="nw", tags="background")
        elif self._exact_preview_active and self._exact_preview_image:
            self.canvas.create_image(0, 0, image=self._exact_preview_image, anchor="nw", tags="background")
        elif self._preview_image:
            self.canvas.create_image(0, 0, image=self._preview_image, anchor="nw", tags="background")
        else:
            self.canvas.create_rectangle(0, 0, width, height, fill="#142233", outline="", tags="background")
            self.canvas.create_rectangle(0, height*.60, width, height, fill="#0d1827", outline="", tags="background")
            self.canvas.create_text(width*.5, height*.5, text="FastComment | 配信動画プレビュー", fill="#546c8b",
                                    font=("Segoe UI", 19, "bold"), tags="background")
        self.canvas.tag_lower("background")

    def load_video_background(self):
        try:
            path = Path(self.video.get().strip()) if self.video.get().strip() else None
            if path is None:
                vod = core.normalize_id(self.vod.get())
                path = resolve_output_directory(self.cache_directory.get()) / (vod + ".mp4")
            if not path.is_file() or not path.stat().st_size:
                raise ValueError("動画を選ぶか、Originalsに元MP4を保存してください")
            seconds = core.parse_time(self.start_time.get()) if self.time_mode.get() == "manual" else self._preview_start
            ffmpeg = core.tool("ffmpeg")
        except (ValueError, OSError, FileNotFoundError) as exc:
            messagebox.showerror("背景の読み込み", str(exc))
            return
        self.preview_note.set("動画の1コマを読み込み中…")
        def job():
            try:
                with tempfile.TemporaryDirectory(prefix="fast_frame_") as tmp:
                    out = Path(tmp) / "frame.png"
                    proc = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", str(seconds),
                                           "-i", str(path), "-frames:v", "1", "-vf", "scale=640:360,format=rgb24",
                                           "-f", "image2", "-vcodec", "png", "-y", str(out)],
                                          capture_output=True, text=True, timeout=90)
                    if proc.returncode != 0 or not out.is_file():
                        raise RuntimeError(proc.stderr[-500:] or "フレームを抽出できませんでした")
                    self.events.put(("background", out.read_bytes()))
            except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
                self.events.put(("preview_error", str(exc)))
        threading.Thread(target=job, daemon=True).start()

    def _animate_preview(self):
        try:
            if self.canvas.winfo_exists():
                now = self._preview_paused_at or time.monotonic()
                t = (now - self._preview_started) % self._preview_span
                cw = max(1, self.canvas.winfo_width())
                ch = max(1, self.canvas.winfo_height())
                self.canvas.delete("comments")
                if getattr(self, "_sample_preview_active", False):
                    if self._sample_preview_frames:
                        import base64
                        frame_index = (int((now - self._preview_started) * self._sample_preview_fps)
                                       % len(self._sample_preview_frames))
                        if frame_index != self._sample_preview_index:
                            self._sample_preview_index = frame_index
                            data = self._sample_preview_frames[frame_index]
                            self._sample_preview_image = tk.PhotoImage(
                                data=base64.b64encode(data).decode("ascii"), format="png")
                            self._redraw_background()
                    return
                if getattr(self, "_sample_preview_pending", False) or self._exact_preview_active:
                    return
                sx, sy = cw / 1280, ch / 720
                for event in self._preview_events:
                    if not event.at <= t < event.end:
                        continue
                    x = event.x_start + ((t-event.at) / (event.end-event.at)) * (event.x_end-event.x_start) if event.moving else event.x_start
                    # Tk positive font sizes mean POINTS (DPI-scaled), whereas
                    # libass font_size is in pixels at PlayResY. Negative Tk
                    # sizes request pixels, avoiding ~33% larger preview text.
                    pixel_size = max(1, round(event.font_size * sy))
                    font = ("Meiryo", -pixel_size, "bold")
                    anchor = "ne" if event.align_right else "nw"
                    outline = max(1, round(2 * sy))
                    for dx, dy in ((-outline, 0), (outline, 0), (0, -outline), (0, outline)):
                        self.canvas.create_text(x*sx + dx, event.y*sy + dy, text=event.text, font=font,
                                                fill="#090909", anchor=anchor, tags="comments")
                    self.canvas.create_text(x*sx, event.y*sy, text=event.text, font=font,
                                            fill=event.color, anchor=anchor, tags="comments")
        finally:
            self.root.after(40, self._animate_preview)

    def open_output(self):
        try:
            target = resolve_output_directory(self.output_directory.get())
            target.mkdir(parents=True, exist_ok=True)
            self._show_output_folder(target)
        except (ValueError, OSError) as exc:
            messagebox.showerror("出力先フォルダを開けません", str(exc))

    def append(self, message):
        self.log.configure(state="normal")
        self.log.insert("end", str(message) + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def start(self):
        if self.busy:
            return
        try:
            vod_id = core.normalize_id(self.vod.get()) if self.vod.get().strip() else ""
            if not vod_id and (not self.video.get().strip() or not self.chat.get().strip()):
                raise ValueError("VOD IDを入力するか、動画とチャットJSONの両方を選択してください")
            if self.video.get().strip() and not Path(self.video.get().strip()).is_file():
                raise ValueError("選択した動画が見つかりません")
            if self.chat.get().strip() and not Path(self.chat.get().strip()).is_file():
                raise ValueError("選択したコメントJSONが見つかりません")
            offset = core.parse_comment_offset(self.comment_offset.get())
            if self.preview.get() and self.time_mode.get() == "manual":
                core.parse_time(self.start_time.get())
            if self.preview.get() and self.mode.get() == "soft" and self.time_mode.get() != "first":
                raise ValueError("途中からの30秒テストはMP4焼き込みを選択してください（MKVの無劣化コピーでは時刻がずれます）")
        except (ValueError, OSError) as exc:
            messagebox.showerror("入力の確認", str(exc))
            return
        if not self.save_output_preferences() or not self.save_cache_preferences():
            return
        self.save_settings()
        try:
            args = worker_command() + ["--style", self.style.get(), "--mode", self.mode.get(), "--settings", str(SETTINGS_PATH)]
        except OSError as exc:
            messagebox.showerror("起動エラー", str(exc))
            return
        output_dir = resolve_output_directory(self.output_directory.get())
        args += ["--output-dir", str(output_dir)]
        args += ["--cache-dir", str(resolve_output_directory(self.cache_directory.get()))]
        args += ["--work-dir", str(work_directory_for_output(output_dir))]
        args += ["--comment-offset", str(offset)]
        if vod_id:
            args += ["--vod", vod_id]
        if self.video.get().strip():
            args += ["--video", self.video.get().strip()]
        if self.chat.get().strip():
            args += ["--chat", self.chat.get().strip()]
        if self.mode.get() == "burn":
            args += ["--encoder", self.encoder.get()]
            if self.normal.get():
                args.append("--normalize")
        if self.preview.get():
            args += ["--preview-seconds", "30"]
            if self.time_mode.get() == "auto":
                args += ["--auto-preview"]
            elif self.time_mode.get() == "manual":
                args += ["--preview-start", self.start_time.get()]
        self._completed_file = None
        self._cancel_event.clear()
        self.busy = True
        self._total_seconds = 30.0 if self.preview.get() else None
        self._processed_seconds = 0.0
        self._last_speed = ""
        self.progressbar.configure(value=0)
        self.progress_percent.set("準備中")
        self.progress_detail.set("入力を確認・処理を開始しています")
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.tabs.select(self.tab_logs)
        self.status.set("処理中 — ログタブで進捗確認できます（中止可能）")
        self.append("=" * 40)
        self.append("開始しました。コメント設定は変換開始時の内容で保存されています。")
        if offset:
            self.append(f"OBS録画用の時刻補正: {offset:+g}秒（+で遅らせる、-で早める）")
        threading.Thread(target=self._run_worker, args=(args,), daemon=True).start()

    @staticmethod
    def _terminate_worker(proc):
        if proc.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True, timeout=15,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                proc.terminate()
        except (OSError, subprocess.TimeoutExpired):
            # The worker might already have exited while cancellation happened.
            pass

    def _run_worker(self, args):
        """Run the converter; cancellation wins even if clicked before startup."""
        proc = None
        try:
            if self._cancel_event.is_set():
                self.events.put(("cancelled", None))
                return
            kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
                      "text": True, "errors": "replace", "bufsize": 1}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            proc = subprocess.Popen(args, **kwargs)
            self.worker_process = proc
            # Close the race between clicking Cancel and Popen completing.
            if self._cancel_event.is_set():
                self._terminate_worker(proc)
            assert proc.stdout is not None
            for line in proc.stdout:
                self.events.put(("log", line.rstrip("\r\n")))
            exit_code = proc.wait()
            self.events.put(("cancelled" if self._cancel_event.is_set() else "done", exit_code))
        except (ValueError, OSError) as exc:
            self.events.put(("cancelled" if self._cancel_event.is_set() else "error", str(exc)))
        finally:
            self.worker_process = None

    def cancel(self):
        if not self.busy:
            return
        if not messagebox.askyesno("処理を中止", "実行中の処理を中止しますか？元動画やJSONは削除されません。"):
            return
        self._cancel_event.set()
        self.status.set("中止を要求しています…")
        self.cancel_button.configure(state="disabled")
        proc = self.worker_process
        if proc is not None:
            self._terminate_worker(proc)

    def _read_progress(self, line: str):
        """Keep the prominent progress gauge up to date, independent of log tab."""
        if line == "FC_FINALIZING":
            self._show_finalizing()
            return
        if line.startswith("FC_PROGRESS|"):
            # New worker emits a compact single line instead of FFmpeg's 12+
            # progress key/value lines every few seconds.
            fields = line.split("|", 2)
            if len(fields) == 3:
                try:
                    self._processed_seconds = core.parse_time(fields[1])
                except ValueError:
                    pass
                self._last_speed = fields[2].strip()
                self._update_progress_display()
            return
        if "videodownload を開始" in line:
            self.status.set("動画をダウンロード中…")
            if hasattr(self, "progress_percent"):
                self.progress_percent.set("取得中")
                self.progress_detail.set("動画の取得中・完了時刻は未計測")
        elif "chatdownload を開始" in line:
            self.status.set("コメントをダウンロード中…")
            if hasattr(self, "progress_percent"):
                self.progress_percent.set("取得中")
                self.progress_detail.set("チャット取得中")
        elif line.startswith("エンコード方式:"):
            self._processed_seconds = 0.0
            self._last_speed = ""
            self.status.set(f"{line} — 開始")
            if hasattr(self, "progress_percent"):
                self.progress_percent.set("0%")
                self.progress_detail.set("速度 計測中 / 残り時間 計測中")
        if line.startswith("動画:") and self._total_seconds is None:
            match = re.search(r"時間:\s*([0-9.]+)秒", line)
            if match:
                self._total_seconds = float(match.group(1))
        if line.startswith("out_time="):
            try:
                self._processed_seconds = core.parse_time(line.partition("=")[2])
            except ValueError:
                pass
        if line.startswith("speed="):
            self._last_speed = line.partition("=")[2].strip()
        if line == "progress=continue":
            self._update_progress_display()
        elif line == "progress=end":
            self._show_finalizing()

    def _update_progress_display(self):
        if self._total_seconds:
            percent = min(99.0, max(0.0, 100 * self._processed_seconds / self._total_seconds))
            self.progressbar.configure(value=percent)
            if hasattr(self, "progress_percent"):
                self.progress_percent.set(f"{percent:.1f}%")
            eta = remaining_seconds(self._total_seconds, self._processed_seconds, self._last_speed)
            remaining = f"残り約 {format_duration(eta)}" if eta is not None else "残り時間 計測中"
        else:
            remaining = "残り時間 未計測"
            if hasattr(self, "progress_percent"):
                self.progress_percent.set("計測中")
        speed = self._last_speed if self._last_speed not in ("", "N/A") else "計測中"
        if hasattr(self, "progress_detail"):
            self.progress_detail.set(f"速度 {speed} / {remaining}")
        self.status.set("エンコード中")

    def _show_finalizing(self):
        if hasattr(self, "progress_percent"):
            self.progress_percent.set("保存中")
            self.progress_detail.set("エンコード終了・完成動画を保存中")
        self.status.set("最終保存中（完了するまで終了しないでください）")

    def poll(self):
        while True:
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if event == "log":
                if payload.startswith("完成動画: "):
                    candidate = Path(payload[len("完成動画: "):].strip())
                    if candidate.is_file():
                        self._completed_file = candidate
                self._read_progress(payload)
                if not (payload.startswith(("FC_FINALIZING", "FC_PROGRESS|", "frame=", "fps=", "out_time=", "speed=", "bitrate=", "total_size=", "out_time_ms=", "out_time_us=", "dup_frames=", "drop_frames=", "stream_", "progress="))):
                    self.append(payload)
            elif event == "preview_loaded":
                entries, start, filename = payload
                self._preview_real_entries = entries
                self._preview_start = start
                self._preview_span = 14.0
                self._reset_preview_clock()
                self._rebuild_preview()
                self.preview_note.set(f"実コメント: {filename} / {core.pretty_time(start)} から14秒・{len(entries)}件")
            elif event == "sample_preview_loaded":
                generation, frames, fps, count = payload
                if generation != self._sample_preview_generation:
                    continue
                self._sample_preview_frames = frames
                self._sample_preview_fps = fps
                self._sample_preview_index = -1
                self._sample_preview_pending = False
                self._sample_preview_active = True
                self._exact_preview_active = False
                self._reset_preview_clock()
                self.canvas.delete("comments")
                self.preview_note.set(
                    f"FFmpeg実描画・8秒のサンプル動画（{fps}fps / コメント{count}件）。"
                    "設定変更後に自動更新、停止・再生も可能です。")
            elif event == "sample_preview_error":
                generation, message = payload
                if generation == self._sample_preview_generation:
                    self._sample_preview_pending = False
                    self.preview_note.set("サンプル画像の生成に失敗: " + message)
            elif event == "exact_preview_loaded":
                import base64
                png, timestamp, count, dropped = payload
                self._exact_preview_image = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"), format="png")
                self._exact_preview_active = True
                self.canvas.delete("comments")
                self._redraw_background()
                self.preview_note.set(f"FFmpeg実描画: {core.pretty_time(timestamp)} の1コマ（候補コメント {count} 件）／設定を変えるとライブ表示に戻ります")
            elif event == "background":
                import base64
                # PhotoImage accepts binary PPM data when base64-encoded as a Tk string.
                self._preview_image = tk.PhotoImage(data=base64.b64encode(payload).decode("ascii"), format="png")
                self._redraw_background()
                self.preview_note.set("配信動画の1コマを背景にしました（字幕設定はリアルタイム反映）")
            elif event == "preview_error":
                self.preview_note.set(f"プレビューの読込失敗: {payload}")
            else:
                self.busy = False
                self.start_button.configure(state="normal")
                self.cancel_button.configure(state="disabled")
                cancelled = event == "cancelled"
                success = event == "done" and payload == 0
                self.progressbar.configure(value=100 if success else 0)
                if hasattr(self, "progress_percent"):
                    self.progress_percent.set("100%" if success else ("中止" if cancelled else "エラー"))
                    self.progress_detail.set(
                        "完成動画を保存しました" if success else
                        ("元動画は残しています" if cancelled else "処理ログを確認してください"))
                self.status.set("中止しました。元動画は残しています" if cancelled else (
                    "変換完了。出力フォルダを確認してください" if success else
                    "失敗しました。ログを確認してください"))
                self.append("処理を中止しました" if cancelled else ("正常終了" if success else f"処理失敗：{payload}"))
                if success and self.open_on_complete.get():
                    try:
                        target = completed_output_folder(self._completed_file, self.output_directory.get())
                        self._show_output_folder(target)
                    except (ValueError, OSError) as exc:
                        messagebox.showwarning("フォルダを開けませんでした", f"動画の変換は正常に完了しました。\n{exc}")
        self.root.after(100, self.poll)

    def on_close(self):
        if self.busy:
            messagebox.showinfo("処理中", "変換中です。中止ボタンから停止するか、完了後に閉じてください。")
            return
        if self._settings_job is not None:
            self.root.after_cancel(self._settings_job)
        if self._sample_preview_job is not None:
            self.root.after_cancel(self._sample_preview_job)
        if not self.save_output_preferences() or not self.save_cache_preferences():
            return
        self.save_settings()
        self.root.destroy()


def main(on_ready=None):
    """Start GUI; optionally signal readiness when Tk enters its event loop."""
    root = tk.Tk()
    ttk.Style(root)
    FastCommentGUI(root)
    if on_ready is not None:
        root.after_idle(on_ready)
    root.mainloop()


if __name__ == "__main__":
    main()
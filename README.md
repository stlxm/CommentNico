# CommentNico / FastComment 2.0 (Windows beta)

Independent Windows application for Twitch VOD acquisition and comments overlay. **This is a testing build, not a validated product release.** Do not remove your previous FastComment installation until tested.

## Capabilities

- Normally supply a Twitch VOD ID / video URL; acquire video and chat automatically and reuse cached files.
- Optionally select both an existing MP4 and chat JSON without a VOD ID.
- Live GUI preview: font size, speed, layout, row spacing, user colors, and collision settings.
- More accurately scaled on-screen text: Tk uses pixel font sizes matching FFmpeg/libass scale rather than DPI-scaled point sizes.
- A **実際のFFmpeg描画で1コマ確認** button showing a genuine video frame with libass-rendered comments before final export.
- MP4 comments burned into the video using NVIDIA NVENC (CPU fallback) or MKV with switchable ASS subtitles.
- Audio loudness normalization and selectable 30-second previews from chat-active scenes.
- A custom output directory you can browse to and save across restarts.
- Automatically open the folder containing the exported video after a **successful** conversion (can be disabled).

- Encoding progress with FFmpeg's measured speed and estimated time remaining (downloads report stage only, not an invented ETA).
- Reliable cancellation even when Stop is pressed just as the worker process starts; cancelled runs are shown separately from errors.

## GitHub Desktop: update without downloading ZIPs

This is the fastest way to use source changes and bug fixes. GitHub Desktop updates the **source**, not an existing packaged EXE.

1. In GitHub Desktop choose **File → Clone repository** and select `stlxm/CommentNico` (branch **main**).
2. Choose **Repository → Show in Explorer** to open that cloned directory.
3. First run: double-click **`FastCommentを起動.cmd`**. It uses the Windows Python 3 installation (with Tkinter) and will try to **copy**, not move, the three existing tools from `FastComment2/tools` or other known locations. If not found, select your existing tools folder in the dialog. Python 3.11+ must already be installed.
4. Every later update: **Fetch origin → Pull origin** in GitHub Desktop, close the old window and double-click **`FastCommentを起動.cmd`**. The updated Python source takes effect immediately; no ZIP, no EXE rebuild.
5. To launch a **packaged EXE** instead, double-click **`EXEを更新して起動.cmd`**. This requires Python 3.11+ and PyInstaller (installed automatically on the first build). It rebuilds only if the source changed, stores the app in `release/FastComment`, and opens it. Builds may take a few minutes.

All downloaded tools remain ignored by Git, in `tools/`; GitHub Desktop will not stage personal binaries. Settings and videos are stored outside the repository (in `%LOCALAPPDATA%/FastComment` unless the user chooses another output directory). Do **not** modify/delete the previous `D:/配信用/FastComment2` installation until the updated app is verified.

**Cross-drive saving:** Exports can be written to D: while temporary encoding uses C:. A successful encode is copied to a temporary file on D:, then safely finalized without wasting time retrying other encoders.

## Getting a Windows test build (no Python install required)

Open the **Actions** tab, select **Windows portable beta**, choose the latest successful run and download `FastComment-Windows-beta` under Artifacts. This artifact contains the new app's **FastComment.exe** and **FastCommentWorker.exe**, but to comply with third-party tool redistribution caution it does **not** bundle the external TwitchDownloader/FFmpeg executables.

Before first launch, copy the following three files from your *existing working* tool installation into the **new** `tools` subfolder:

- `TwitchDownloaderCLI.exe` (version 1.56.1)
- `ffmpeg.exe` (a build containing the libass filter and h264_nvenc encoder)
- `ffprobe.exe`

Run `FastComment.exe`. Keep the two EXEs and tools folder together. Neither your old Saccubus/Java folder nor a standalone Python installation should be needed at runtime.

The new user data location is `%LOCALAPPDATA%\FastComment` (or set `FASTCOMMENT_DATA_DIR`).

## Finishing FastComment before final preview tuning

FastComment currently focuses on a safe normal workflow: VOD ID, cached MP4/JSON reuse, optional output folder, a 30-second burn-in before full export, and NVENC on supported GPUs.

Progress is a **time estimate**, not a guarantee; it is only shown while FFmpeg publishes an actual `speed=...x` measurement. Downloads and initial preparation show stages instead. Pressing **中止** stops the worker (and its child processes on Windows) without intentionally deleting original videos. A cancelled conversion is not reported as a failed codec.

The final task in the release checklist is to compare live preview font size/movement to the FFmpeg MP4 export. A one-frame still cannot demonstrate movement. We are intentionally deferring this polish until download, long-running conversion, save/cancel, and safe migration have been verified.

## Comparing live preview and the actual MP4

The live comment preview is instant and interactive, but approximates how FFmpeg/libass rasterizes fonts and shadows. On the **② コメント設定とプレビュー** tab:

1. Choose the VOD, a downloaded MP4 and chat JSON on **① 動画・出力**. Files already cached for the VOD are recognized.
2. Set the comment size, color, speed, and spacing while the live preview animates.
3. Click **実際のFFmpeg描画で1コマ確認** for a frame rendered through the **same libass filter** used by the final exported video. This takes a moment and requires a local video and JSON. It uses the 30s test's automatic dense-comment region, or your chosen start time.
4. If you change a setting, FastComment switches back to live preview; click the actual-frame button again to see the revised FFmpeg result.
5. Click **ライブ表示に戻す** to resume animation.

The actual-frame button shows **one frame**, not motion. For final timing / overlap / appearance, run the 30-second MP4 test. The sample messages in live preview are demonstrations, not your stream's real comments; choose **実コメントから再生** to see real messages.

## Choosing and saving your output folder

Open **① 動画・出力** in FastComment. Under **出力設定**, select **出力先フォルダ → 参照…** or type an absolute path, then click **保存**. Your destination is reused automatically on later launches, even after replacing the EXEs.

The **変換が完了したら保存先フォルダを自動で開く** checkbox is on by default and can be unchecked. After a successful conversion, Windows Explorer opens the folder containing the completed MP4/MKV (inside the selected root, grouped by streamer). Failed or cancelled jobs do not open folders.

These options are saved to `%LOCALAPPDATA%\\FastComment\\output_preferences.json`, separate from video files and `comment_settings.json`. Existing videos remain untouched.

The CLI/worker also supports `--output-dir "D:\\YourFolder\\Videos"`.

## Developer build on Windows

Install Python 3.11, download the repository sources, run:

```powershell
py -3 -m unittest discover -s . -p "test_*.py" -v
.\build_windows.ps1 -TwitchDownloader "D:\path\TwitchDownloaderCLI.exe" -FFmpeg "D:\path\ffmpeg.exe" -FFprobe "D:\path\ffprobe.exe"
```

The second command produces a portable directory `release\FastComment` with executables and tools. The program folder is portable; it is not a single-file standalone EXE.

## Safe migration checklist

1. Back up your original `FastComment`, `Originals`, `Output` and `comment_settings.json`. Do not overwrite them.
2. Keep the new app in a separate directory, never inside the old folder.
3. Copy previously downloaded MP4 and JSON files into `%LOCALAPPDATA%\FastComment\Originals`, if you want to reuse them. Copy settings to `%LOCALAPPDATA%\FastComment\comment_settings.json` while the app is closed.
4. Test a cached VOD, a fresh download, a 30-second GPU burn-in with real chat, normalizing audio, full-length export, and accurate sync.
5. Temporarily rename your **old** install folder to ensure the new app does not depend on it. Restore the name if anything fails.
6. **Only after all tests and backup confirmation** consider deleting old program files; preserve user videos.

## Scope and known limitations

- Windows/NVENC on the user's RTX 3060 Ti must be validated locally before public release.
- GIF/emote image rendering, silence trimming, automatic highlights and thumbnail editing are future separate tools.
- Live preview approximates font metrics; compare with the 30-second MP4 burn-in.
- The optional switchable-subtitle MKV preview does not support arbitrary nonzero start times.
- Never commit personal videos, chat logs, user settings or credentials.
- Consult [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before redistributing external binaries.

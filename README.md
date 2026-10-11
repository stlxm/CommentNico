# CommentNico / FastComment 2.0 (Windows beta)

Independent Windows application for Twitch VOD acquisition and comments overlay. **This is a testing build, not a validated product release.** Do not remove your previous FastComment installation until tested.

## Capabilities

- Normally supply a Twitch VOD ID / video URL; acquire video and chat automatically and reuse cached files.
- Optionally select both an existing MP4 and chat JSON without a VOD ID.
- Live GUI preview: font size, speed, layout, row spacing, user colors, and collision settings.
- MP4 comments burned into the video using NVIDIA NVENC (CPU fallback) or MKV with switchable ASS subtitles.
- Audio loudness normalization and selectable 30-second previews from chat-active scenes.
- A custom output directory you can browse to and save across restarts.
- Automatically open the folder containing the exported video after a **successful** conversion (can be disabled).

- Progress / logs and cancel button.

## Getting a Windows test build (no Python install required)

Open the **Actions** tab, select **Windows portable beta**, choose the latest successful run and download `FastComment-Windows-beta` under Artifacts. This artifact contains the new app's **FastComment.exe** and **FastCommentWorker.exe**, but to comply with third-party tool redistribution caution it does **not** bundle the external TwitchDownloader/FFmpeg executables.

Before first launch, copy the following three files from your *existing working* tool installation into the **new** `tools` subfolder:

- `TwitchDownloaderCLI.exe` (version 1.56.1)
- `ffmpeg.exe` (a build containing the libass filter and h264_nvenc encoder)
- `ffprobe.exe`

Run `FastComment.exe`. Keep the two EXEs and tools folder together. Neither your old Saccubus/Java folder nor a standalone Python installation should be needed at runtime.

The new user data location is `%LOCALAPPDATA%\FastComment` (or set `FASTCOMMENT_DATA_DIR`).

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

# Third-party tools

FastComment application code uses the Python standard library. An independent Windows build also needs copies of external tools:

- [TwitchDownloader](https://github.com/lay295/TwitchDownloader), version 1.56.1, to fetch VODs and chat.
- [FFmpeg](https://ffmpeg.org/), including an FFmpeg build with libass and NVIDIA NVENC support.
- [PyInstaller](https://pyinstaller.org/), used during Windows packaging.

**Redistribution notice:** When publishing packages containing third-party programs, inspect their actual distribution licenses and requirements. FFmpeg builds with GPL libraries may require GPL terms and corresponding source-code availability. Keep license/copyright notices. A CI build artifact is for testing, not a license audit or a public release.

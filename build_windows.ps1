param(
  [Parameter(Mandatory=$true)][string]$TwitchDownloader,
  [Parameter(Mandatory=$true)][string]$FFmpeg,
  [Parameter(Mandatory=$true)][string]$FFprobe
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
foreach ($p in @($TwitchDownloader, $FFmpeg, $FFprobe)) {
  if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { throw "Required tool not found: $p" }
}
py -3 -m pip install --disable-pip-version-check 'pyinstaller==6.16.0'
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller install failed' }
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name FastComment --distpath "$PSScriptRoot\dist_gui" --workpath "$PSScriptRoot\build_gui" FastComment_GUI.pyw
if ($LASTEXITCODE -ne 0) { throw 'GUI build failed' }
py -3 -m PyInstaller --noconfirm --clean --onefile --console --name FastCommentWorker --distpath "$PSScriptRoot\dist_worker" --workpath "$PSScriptRoot\build_worker" FastCommentWorker.py
if ($LASTEXITCODE -ne 0) { throw 'Worker build failed' }
$release = Join-Path $PSScriptRoot 'release\FastComment'
New-Item -ItemType Directory -Force (Join-Path $release 'tools') | Out-Null
Copy-Item "$PSScriptRoot\dist_gui\FastComment.exe" $release -Force
Copy-Item "$PSScriptRoot\dist_worker\FastCommentWorker.exe" $release -Force
Copy-Item -LiteralPath $TwitchDownloader -Destination (Join-Path $release 'tools\TwitchDownloaderCLI.exe') -Force
Copy-Item -LiteralPath $FFmpeg -Destination (Join-Path $release 'tools\ffmpeg.exe') -Force
Copy-Item -LiteralPath $FFprobe -Destination (Join-Path $release 'tools\ffprobe.exe') -Force
Copy-Item README.md $release -Force
Copy-Item THIRD_PARTY_NOTICES.md $release -Force
"Build completed: $release"

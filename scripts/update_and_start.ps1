param()
$ErrorActionPreference = "Stop"
$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $project
& (Join-Path $PSScriptRoot "bootstrap_tools.ps1") -ProjectRoot $project

$files = @("app_paths.py", "fast_comment.py", "fast_comment_gui.py", "FastComment_GUI.pyw", "FastCommentWorker.py", "build_windows.ps1")
$hashes = foreach ($path in $files) { (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $project $path)).Hash }
$fingerprint = $hashes -join ":"
$release = Join-Path $project "release\FastComment"
$gui = Join-Path $release "FastComment.exe"
$worker = Join-Path $release "FastCommentWorker.exe"
$stamp = Join-Path $release ".source-hashes"
$current = if (Test-Path -LiteralPath $stamp) { Get-Content -LiteralPath $stamp -Raw } else { "" }

$shouldBuild = -not (Test-Path -LiteralPath $gui -PathType Leaf) -or -not (Test-Path -LiteralPath $worker -PathType Leaf) -or ($current.Trim() -ne $fingerprint)
if ($shouldBuild) {
    Write-Host "Source changed, building the current EXE version (may take a few minutes)..."
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw "Python 3.11+ and the Windows Python launcher (py.exe) are required to build the EXE locally."
    }
    & (Join-Path $project "build_windows.ps1") -TwitchDownloader (Join-Path $project "tools\TwitchDownloaderCLI.exe") -FFmpeg (Join-Path $project "tools\ffmpeg.exe") -FFprobe (Join-Path $project "tools\ffprobe.exe")
    if (-not (Test-Path -LiteralPath $gui -PathType Leaf) -or -not (Test-Path -LiteralPath $worker -PathType Leaf)) {
        throw "EXE build did not produce both applications."
    }
    Set-Content -LiteralPath $stamp -Value $fingerprint -Encoding ASCII
}
else { Write-Host "The local EXE already matches the latest pulled source." }
Write-Host "Launching: $gui"
Start-Process -FilePath $gui -WorkingDirectory $release

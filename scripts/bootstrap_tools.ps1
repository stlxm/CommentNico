param([string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$toolDir = Join-Path $ProjectRoot "tools"
$names = @("TwitchDownloaderCLI.exe", "ffmpeg.exe", "ffprobe.exe")
New-Item -ItemType Directory -Path $toolDir -Force | Out-Null

$missing = @($names | Where-Object { -not (Test-Path -LiteralPath (Join-Path $toolDir $_) -PathType Leaf) })
if ($missing.Count -eq 0) { return }

$parent = Split-Path -Parent $ProjectRoot
$sources = @(
    (Join-Path $parent "FastComment2\tools"),
    (Join-Path $parent "FastComment2"),
    (Join-Path $parent "TwitchDownloaderCLI-1.56.1-Windows-x64"),
    "D:\配信用\FastComment2\tools",
    "D:\配信用\TwitchDownloaderCLI-1.56.1-Windows-x64",
    $env:FASTCOMMENT_TOOLS_DIR
)
foreach ($source in $sources) {
    if (-not $source -or -not (Test-Path -LiteralPath $source -PathType Container)) { continue }
    foreach ($name in $names) {
        $target = Join-Path $toolDir $name
        $candidate = Join-Path $source $name
        if (-not (Test-Path -LiteralPath $target) -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            Copy-Item -LiteralPath $candidate -Destination $target
            Write-Host "Copied tool: $name"
        }
    }
}
$missing = @($names | Where-Object { -not (Test-Path -LiteralPath (Join-Path $toolDir $_) -PathType Leaf) })
if ($missing.Count -ne 0) {
    Write-Host "Required tools missing: $($missing -join ', ')"
    Write-Host "Choose a folder with the missing executable(s) from your previous installation."
    Add-Type -AssemblyName System.Windows.Forms
    $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
    $dlg.Description = "Select the folder containing TwitchDownloaderCLI.exe and FFmpeg tools"
    if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        foreach ($name in $missing) {
            $candidate = Join-Path $dlg.SelectedPath $name
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                Copy-Item -LiteralPath $candidate -Destination (Join-Path $toolDir $name)
                Write-Host "Copied tool: $name"
            }
        }
    }
}
$missing = @($names | Where-Object { -not (Test-Path -LiteralPath (Join-Path $toolDir $_) -PathType Leaf) })
if ($missing.Count -ne 0) {
    throw "Copy the following files into '$toolDir': $($missing -join ', ')"
}

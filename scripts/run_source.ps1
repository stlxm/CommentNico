param()
$ErrorActionPreference = "Stop"
$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
& (Join-Path $PSScriptRoot "bootstrap_tools.ps1") -ProjectRoot $project
$pythonPath = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $candidate = & py -3 -c "import sys, tkinter; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $candidate) { $pythonPath = ($candidate | Select-Object -Last 1).Trim() }
}
if (-not $pythonPath -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $candidate = & python -c "import sys, tkinter; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $candidate) { $pythonPath = ($candidate | Select-Object -Last 1).Trim() }
}
if (-not $pythonPath) {
    throw "Python 3 with tkinter is required for quick source launches. Install Python 3.11+ once, or use the built EXE instead."
}
$pythonw = Join-Path (Split-Path -Parent $pythonPath) "pythonw.exe"
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) { $pythonw = $pythonPath }
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
Write-Host "Starting FastComment from current GitHub Desktop source..."
Start-Process -FilePath $pythonw -ArgumentList @("-u", ('"' + (Join-Path $project "FastComment_GUI.pyw") + '"')) -WorkingDirectory $project

# clipbot Windows setup: installs Python + FFmpeg (via winget) if missing,
# creates a private virtual environment in .venv and installs clipbot into it.
# Safe to run again at any time (for example after pulling updates).

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Invoke-Py([string]$cmd, [string[]]$rest) {
    # $cmd is "py -3" or "python"; split it so it works as a native command.
    $parts = $cmd -split " "
    $exe = $parts[0]
    $pre = @($parts | Select-Object -Skip 1)
    & $exe @pre @rest
}

function Find-Python {
    foreach ($cmd in @("py -3", "python")) {
        $exe = ($cmd -split " ")[0]
        if (Get-Command $exe -ErrorAction SilentlyContinue) {
            try {
                $v = Invoke-Py $cmd @("-c", "import sys; print(str(sys.version_info[0]) + '.' + str(sys.version_info[1]))")
                if ($LASTEXITCODE -eq 0 -and $v -and [version]"$v" -ge [version]"3.10") { return $cmd }
            } catch { }
        }
    }
    return $null
}

Write-Host "== clipbot setup ==" -ForegroundColor Cyan

$haveWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)

# 1) Python
$py = Find-Python
if (-not $py) {
    if (-not $haveWinget) { throw "Python 3.10+ not found and winget is unavailable. Install Python 3.12 from python.org (tick 'Add to PATH'), then run setup again." }
    Write-Host "Installing Python 3.12..."
    winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
    Refresh-Path
    $py = Find-Python
    if (-not $py) { throw "Python installed but not found yet. Close this window and double-click setup.bat again." }
}
Write-Host "Python: $py" -ForegroundColor Green

# 2) FFmpeg (full build includes libass for captions and zscale for HDR)
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    if (-not $haveWinget) { throw "FFmpeg not found and winget is unavailable. See docs/WINDOWS_SETUP.md for the manual install." }
    Write-Host "Installing FFmpeg..."
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
    Refresh-Path
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    throw "FFmpeg installed but not on PATH yet. Close this window and double-click setup.bat again."
}
Write-Host "FFmpeg: $((Get-Command ffmpeg).Source)" -ForegroundColor Green

# 3) Virtual environment + clipbot
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating .venv ..."
    Invoke-Py $py @("-m", "venv", ".venv")
    if ($LASTEXITCODE -ne 0) { throw "could not create the virtual environment" }
}
& .venv\Scripts\python.exe -m pip install --upgrade pip --quiet
& .venv\Scripts\python.exe -m pip install -e . --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

foreach ($d in @("footage", "plans", "out")) { New-Item -ItemType Directory -Force -Path $d | Out-Null }

Write-Host ""
& .venv\Scripts\clipbot.exe doctor
Write-Host ""
Write-Host "Done. Open a terminal in this folder and run:  .\clipbot check examples\witness-memory.yaml" -ForegroundColor Cyan

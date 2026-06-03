<#
.SYNOPSIS
    Build "EL Pipeline.exe" from gui/app.py using PyInstaller.
.DESCRIPTION
    Produces a single-file, windowed .exe in dist/EL Pipeline.exe.
    The .exe must sit next to docker-compose.yml, .env, and the Docker
    image (built separately via `docker compose build`).

    Prerequisites:
      - Python 3.12+ virtual environment (.venv) with customtkinter,
        pyinstaller, and requests installed.
      - All project dependencies installed (requirements.txt).

    Usage (from the repo root):
      .\gui\build.ps1
#>

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
$GuiSource = "$PSScriptRoot\app.py"

Write-Host "=== EL Pipeline GUI Builder ===" -ForegroundColor Cyan
Write-Host "Source : $GuiSource"
Write-Host "Root   : $ProjectRoot"

# Activate .venv if present
$Venv = Join-Path $ProjectRoot ".venv"
if (Test-Path "$Venv\Scripts\python.exe") {
    & "$Venv\Scripts\python.exe" -c "import customtkinter" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing build deps..." -ForegroundColor Yellow
        & "$Venv\Scripts\pip.exe" install customtkinter pyinstaller requests
    }
    $Py = "$Venv\Scripts\python.exe"
} else {
    $Py = "python"
}

Write-Host "Running PyInstaller..." -ForegroundColor Cyan
& $Py -m PyInstaller --noconfirm `
    --onefile `
    --windowed `
    --name "EL Pipeline" `
    --add-data "$ProjectRoot\.env.example;." `
    --distpath (Join-Path $ProjectRoot "dist") `
    --workpath (Join-Path $ProjectRoot "build\pyi") `
    --specpath (Join-Path $ProjectRoot "build") `
    $GuiSource

if ($LASTEXITCODE -eq 0) {
    $ExePath = Join-Path $ProjectRoot "dist\EL Pipeline.exe"
    Write-Host ""
    Write-Host "\u2705  SUCCESS" -ForegroundColor Green
    Write-Host "   $ExePath"
    Write-Host ""
    Write-Host "Copy this .exe to your project root (where docker-compose.yml lives)"
    Write-Host "and double-click to run." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "\u274c  BUILD FAILED" -ForegroundColor Red
    exit 1
}

<#
  Klatsch 🐾 — Setup Script
  ==========================
  Run this script on any Windows machine to:
  1. Create a Python virtual environment
  2. Install dependencies from requirements.txt
  3. (Optional) Create a Windows Startup shortcut for auto-start at login

  Prerequisites:
  - Python 3.11+ installed
  - FFmpeg installed (for edge-tts audio decode): winget install ffmpeg
  - An OpenClaw gateway running somewhere on the network

  Usage:
    powershell -ExecutionPolicy Bypass -File setup.ps1
#>

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvDir = Join-Path $ScriptDir ".venv"
$PythonExe = "python"

Write-Host "=== Klatsch Setup ===" -ForegroundColor Green

# 1. Create venv
if (-not (Test-Path $VenvDir)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    & $PythonExe -m venv $VenvDir
}

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

# 2. Install dependencies
Write-Host "Installing dependencies..." -ForegroundColor Yellow
& $VenvPython -m pip install --upgrade pip -q
& $VenvPython -m pip install -r (Join-Path $ScriptDir "requirements.txt") -q
Write-Host "Dependencies installed." -ForegroundColor Green

# 3. Check ffmpeg
if (-not (Get-Command "ffmpeg" -ErrorAction SilentlyContinue)) {
    Write-Host "WARNING: ffmpeg not found. Install with: winget install ffmpeg" -ForegroundColor Yellow
}
else {
    Write-Host "ffmpeg found." -ForegroundColor Green
}

# 4. Optional: create a Windows Startup shortcut (--tray mode)
$answer = Read-Host "Create a Windows Startup shortcut for --tray mode? [y/N]"
if ($answer -match "^[Yy]$") {
    $WScriptShell = New-Object -ComObject WScript.Shell
    $StartupDir = [Environment]::GetFolderPath("Startup")
    $ShortcutPath = Join-Path $StartupDir "Klatsch.lnk"
    $Shortcut = $WScriptShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = Join-Path $VenvDir "Scripts\pythonw.exe"
    $Shortcut.Arguments = "`"$(Join-Path $ScriptDir 'klatsch.py')`" --tray"
    $Shortcut.WorkingDirectory = $ScriptDir
    $Shortcut.Description = "Klatsch 🐾 — OpenClaw Local Agent"
    $Shortcut.Save()
    Write-Host "Startup shortcut created: $ShortcutPath" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== Done! ===" -ForegroundColor Green
Write-Host "Configure via environment variables (see README.md), then run:"
Write-Host "  .\.venv\Scripts\python.exe klatsch.py --tray"

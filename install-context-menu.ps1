<#
  Klatsch 🐾 — Explorer Context Menu Installer
  ==============================================
  Registers Windows Explorer context menu entries and a "Send To" shortcut.

  Actions installed:
  - Right-click → "Mit Klatsch vorlesen"     (TTS read-aloud)
  - Right-click → "An Klatsch senden"        (ask AI agent)
  - Right-click → "Mit Klatsch zusammenfassen" (AI summary)
  - Send To → "Klatsch 🐾"                   (default: ask)

  Usage:
    powershell -ExecutionPolicy Bypass -File install-context-menu.ps1
    powershell -ExecutionPolicy Bypass -File install-context-menu.ps1 -Uninstall

  Note: Requires elevation for HKLM registry writes (all users).
  Falls back to HKCU (current user only) without elevation.
#>

param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ScriptDir ".venv\Scripts\pythonw.exe"
$SendScript = Join-Path $ScriptDir "klatsch-send.py"

# Check prerequisites
if (-not (Test-Path $PythonExe)) {
    Write-Host "ERROR: Python venv not found at $PythonExe" -ForegroundColor Red
    Write-Host "Run setup.ps1 first to create the virtual environment." -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $SendScript)) {
    Write-Host "ERROR: klatsch-send.py not found at $SendScript" -ForegroundColor Red
    exit 1
}

# Registry root — try HKLM (all users), fall back to HKCU
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$regBase = if ($isAdmin) { "HKLM:" } else { "HKCU:" }
$shellBase = "$regBase\SOFTWARE\Classes\*\shell"
$dirShellBase = "$regBase\SOFTWARE\Classes\Directory\shell"

$entries = @(
    @{
        Name   = "KlatschSpeak"
        Label  = "Mit Klatsch vorlesen 🔊"
        Action = "speak"
        Icon   = ""
    },
    @{
        Name   = "KlatschAsk"
        Label  = "An Klatsch senden 🐾"
        Action = "ask"
        Icon   = ""
    },
    @{
        Name   = "KlatschSummarize"
        Label  = "Mit Klatsch zusammenfassen 📝"
        Action = "summarize"
        Icon   = ""
    }
)

if ($Uninstall) {
    Write-Host "=== Klatsch Context Menu — Uninstall ===" -ForegroundColor Yellow

    foreach ($entry in $entries) {
        $keyPath = "$shellBase\$($entry.Name)"
        if (Test-Path $keyPath) {
            Remove-Item -Path $keyPath -Recurse -Force
            Write-Host "  Removed: $($entry.Label)" -ForegroundColor Green
        }
        $dirKeyPath = "$dirShellBase\$($entry.Name)"
        if (Test-Path $dirKeyPath) {
            Remove-Item -Path $dirKeyPath -Recurse -Force
        }
    }

    # Remove Send To shortcut
    $sendToDir = [Environment]::GetFolderPath("SendTo")
    $sendToLink = Join-Path $sendToDir "Klatsch.lnk"
    if (Test-Path $sendToLink) {
        Remove-Item $sendToLink -Force
        Write-Host "  Removed: Send To shortcut" -ForegroundColor Green
    }

    Write-Host "Done. Context menu entries removed." -ForegroundColor Green
    exit 0
}

# ──────────────────────────────────────────────────────────────────────────────
# Install
# ──────────────────────────────────────────────────────────────────────────────

Write-Host "=== Klatsch Context Menu — Install ===" -ForegroundColor Green
if (-not $isAdmin) {
    Write-Host "  (Running as current user — HKCU. Run as admin for all users.)" -ForegroundColor Yellow
}

foreach ($entry in $entries) {
    $cmd = "`"$PythonExe`" `"$SendScript`" $($entry.Action) `"%1`""

    # File context menu
    $keyPath = "$shellBase\$($entry.Name)"
    if (-not (Test-Path $keyPath)) { New-Item -Path $keyPath -Force | Out-Null }
    Set-ItemProperty -Path $keyPath -Name "(Default)" -Value $entry.Label
    # SubCommands group for cleaner menu (optional, Windows 11)
    $cmdPath = "$keyPath\command"
    if (-not (Test-Path $cmdPath)) { New-Item -Path $cmdPath -Force | Out-Null }
    Set-ItemProperty -Path $cmdPath -Name "(Default)" -Value $cmd

    # Directory context menu (same actions for folders)
    $dirCmd = "`"$PythonExe`" `"$SendScript`" $($entry.Action) `"%V`""
    $dirKeyPath = "$dirShellBase\$($entry.Name)"
    if (-not (Test-Path $dirKeyPath)) { New-Item -Path $dirKeyPath -Force | Out-Null }
    Set-ItemProperty -Path $dirKeyPath -Name "(Default)" -Value $entry.Label
    $dirCmdPath = "$dirKeyPath\command"
    if (-not (Test-Path $dirCmdPath)) { New-Item -Path $dirCmdPath -Force | Out-Null }
    Set-ItemProperty -Path $dirCmdPath -Name "(Default)" -Value $dirCmd

    Write-Host "  Installed: $($entry.Label)" -ForegroundColor Green
}

# ──────────────────────────────────────────────────────────────────────────────
# Send To shortcut
# ──────────────────────────────────────────────────────────────────────────────

$sendToDir = [Environment]::GetFolderPath("SendTo")
$sendToLink = Join-Path $sendToDir "Klatsch.lnk"
$WScriptShell = New-Object -ComObject WScript.Shell
$Shortcut = $WScriptShell.CreateShortcut($sendToLink)
$Shortcut.TargetPath = $PythonExe
$Shortcut.Arguments = "`"$SendScript`" ask"
$Shortcut.WorkingDirectory = $ScriptDir
$Shortcut.Description = "An Klatsch senden 🐾"
$Shortcut.Save()
Write-Host "  Installed: Send To → Klatsch" -ForegroundColor Green

Write-Host ""
Write-Host "=== Done! ===" -ForegroundColor Green
Write-Host "Right-click any file in Explorer to see the Klatsch options."
Write-Host "Or use: Right-click → Send To → Klatsch"
Write-Host ""
Write-Host "To uninstall: powershell -File install-context-menu.ps1 -Uninstall" -ForegroundColor Gray

@echo off
REM Klatsch 🐾 — Quick launcher
REM Copy this file and adjust the variables below for each host.

REM --- Configure ---
set GATEWAY_URL=http://localhost:18789
set GATEWAY_TOKEN=opensesame
set HOST_NAME=%COMPUTERNAME%
REM PEERS=http://other-host:7790
REM WAKE_WORDS=hey klatsch,klatsch
REM TTS_VOICE=de-DE-ConradNeural

"%~dp0.venv\Scripts\pythonw.exe" "%~dp0klatsch.py" --tray

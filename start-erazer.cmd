@echo off
title Klatsch - ERAZER
cd /d "D:\Projekte\klatsch"

:: Peer config: NEMESIS (LAN | Tailscale)
set PEERS_CONFIG=192.168.0.67|100.75.157.7
set HOST_NAME=ERAZER
set PEER_PORT=7790
set SPEAKER_SCORE=0.8

:: Gateway on NEMESIS
set GATEWAY_URL=http://192.168.0.67:18789

echo Starting Klatsch on ERAZER...
.venv\Scripts\python.exe klatsch.py --tray %*

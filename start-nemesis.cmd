@echo off
title Klatsch - NEMESIS
cd /d "C:\Users\dano\AppData\Local\Programs\Klatsch"

:: Peer config: ERAZER (LAN | Tailscale)
set PEERS_CONFIG=192.168.0.172|100.75.39.4
set HOST_NAME=NEMESIS
set PEER_PORT=7790
set SPEAKER_SCORE=1.0

:: Gateway
set GATEWAY_URL=http://192.168.0.67:18789

echo Starting Klatsch on NEMESIS...
.venv\Scripts\python.exe klatsch.py --tray %*

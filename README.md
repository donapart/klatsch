# Klatsch 🐾

**Always-on local agent for the [OpenClaw](https://openclaw.ai) ecosystem.**

Klatsch runs on each of your machines (Windows or Linux/Pi) and gives OpenClaw eyes and ears on that host:

- 🎙️ **Voice assistant** — wake-word detection, Whisper STT, edge-TTS, German/English
- 🔔 **Notification hub** — receive push messages from the gateway and speak them aloud
- 📡 **Peer coordinator** — Follow-Me routing: whoever is closest to the mic answers
- 🖥️ **System awareness** — processes, CPU/RAM, disk health, screenshot, clipboard
- 💾 **Inventory proxy** — exposes local disks and Git repos via HTTP
- ⏰ **Reminders** — schedule spoken reminders by voice
- 📢 **Intercom + broadcast** — speak to one peer or all peers at once
- 🌅 **Morning briefing** — daily 06–09 h gateway briefing (date, weather, agenda)
- 🤖 **Ollama integration** — "frag Ollama …" routes to a local LLM

The name is German for both "clap" and "gossip" — because when it works, you clap, and it always knows what's going on. 👏

---

## Requirements

- Python 3.11+
- [FFmpeg](https://ffmpeg.org/) (for edge-tts audio decode): `winget install ffmpeg`
- An [OpenClaw](https://openclaw.ai) gateway running somewhere on the network

---

## Installation

```powershell
# Clone
git clone https://github.com/donapart/klatsch.git
cd klatsch

# Create venv + install deps
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Or run the one-shot setup script (Windows, auto-creates a startup shortcut):

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

---

## Configuration

All settings are via environment variables (or a `.env` file):

| Variable | Default | Description |
|---|---|---|
| `GATEWAY_URL` | `http://localhost:18789` | OpenClaw gateway base URL |
| `GATEWAY_TOKEN` | `opensesame` | Gateway auth token |
| `AGENT_ID` | `main` | Agent ID to route voice commands to |
| `HOST_NAME` | machine hostname | Displayed in tray and logs |
| `WAKE_WORDS` | `hey nemesis,nemesis` | Comma-separated wake words |
| `TTS_VOICE` | `de-DE-ConradNeural` | edge-tts voice name |
| `WHISPER_MODEL` | `base` | faster-whisper model size (`tiny`/`base`/`small`) |
| `MIC_THRESHOLD` | `0.015` | Voice activity threshold 0.0–1.0 |
| `INPUT_DEVICE` | system default | Audio input device index |
| `OUTPUT_DEVICE` | system default | Audio output device index |
| `VOLUME` | `100` | TTS playback volume 0–100 |
| `PEERS` | *(empty)* | Space-separated peer URLs, e.g. `http://erazer:7790` |
| `SPEAKER_SCORE` | `0.5` | Follow-Me speaker proximity score 0.0–1.0 |

---

## Running

```powershell
# Normal mode (console)
python klatsch.py

# Background with system tray icon
python klatsch.py --tray

# Discover audio devices
python klatsch.py --list-devices

# Test microphone (5 s recording)
python klatsch.py --test-mic

# Specific devices
python klatsch.py --input-device 3 --output-device 5
```

---

## HTTP API (peer server, default port 7790)

Each Klatsch instance runs a small HTTP server so peers and external services can interact with it.

### GET endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Status, hostname, presence |
| `GET /inventory` | Local disks + Git project list |
| `GET /screenshot` | Screenshot as base64 PNG |
| `GET /clipboard` | Read clipboard text |
| `GET /processes` | Top-20 processes by CPU |
| `GET /syshealth` | CPU%, RAM%, disk usage |
| `GET /find-file?q=query` | Search files by name |

### POST endpoints

```jsonc
POST /speak        {"text": "Hello!"}
POST /notify       {"text": "...", "from": "Bot"}
POST /intercom     {"text": "...", "from": "NEMESIS"}
POST /clipboard    {"text": "text to set"}
POST /open-app     {"app": "chrome"}
POST /remind       {"text": "Stand-up!", "minutes": 15}
POST /broadcast    {"text": "...", "endpoint": "/notify"}
POST /wake-claim   (internal Follow-Me protocol)
```

---

## Voice commands (German)

| Say | Action |
|---|---|
| *"Hey Nemesis, …"* | Wake + command |
| *"pause"* | Pause current TTS |
| *"weiter"* | Resume TTS |
| *"Nemesis, sag ERAZER: …"* | Intercom to peer |
| *"sag allen dass …"* | Broadcast to all peers |
| *"öffne Chrome"* | Open application |
| *"fokussiere Discord"* | Bring window to foreground |
| *"Zwischenablage"* | Read clipboard aloud |
| *"erinnere mich in 10 Minuten an …"* | Set reminder |
| *"Systemstatus"* | Speak CPU + RAM |
| *"frag Ollama …"* | Query local LLM |

---

## Multi-device Follow-Me

Set `PEERS=http://other-host:7790` on every host. When the wake word fires on multiple devices simultaneously, the one closest to the speaker (highest mic amplitude) wins — the others stay silent.

---

## Optional dependencies

| Package | Feature |
|---|---|
| `openwakeword` | Lightweight wake-word detection (falls back to Whisper) |
| `pystray` + `Pillow` | System tray icon (`--tray` mode) |
| `psutil` | `GET /processes`, `GET /syshealth`, presence watcher, disk watcher |
| `pyperclip` | Clipboard read/write |

---

## License

MIT — see [LICENSE](LICENSE).

Built on top of [OpenClaw](https://openclaw.ai).

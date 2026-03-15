#!/usr/bin/env python3
"""
Klatsch 🐾 — OpenClaw Local Agent
===================================
Always-on local agent per host: voice assistant, disk/project inventory proxy,
notification hub and peer coordinator for the OpenClaw ecosystem.

Named after the German word for "clap" / "gossip" — because when it works,
you clap, and the agent always knows what's going on. 👏🐾

Usage:
  python klatsch.py                     # normal mode
  python klatsch.py --tray              # background with system tray icon
  python klatsch.py --list-devices      # show available audio devices
  python klatsch.py --test-mic          # record 5s, show levels, play back
  python klatsch.py --input-device 3    # use input device #3
  python klatsch.py --output-device 5   # use output device #5
  python klatsch.py --volume 80         # set TTS playback volume (0-100)

Requirements:
  pip install -r requirements.txt

Configuration via env vars:
  GATEWAY_URL       - Gateway base URL (default: http://192.168.0.67:18789)
  GATEWAY_TOKEN     - Auth token (default: opensesame)
  AGENT_ID          - Agent ID to talk to (default: main)
  WAKE_WORDS        - Comma-separated wake words (default: hey klatsch,klatsch)
  TTS_VOICE         - edge-tts voice name (default: de-DE-ConradNeural)
  WHISPER_MODEL     - faster-whisper model size (default: base)
  MIC_THRESHOLD     - Voice activity threshold 0.0-1.0 (default: 0.015)
  SILENCE_SECONDS   - Seconds of silence to end utterance (default: 1.5)
  INPUT_DEVICE      - Audio input device index (default: system default)
  OUTPUT_DEVICE     - Audio output device index (default: system default)
  VOLUME            - TTS playback volume 0-100 (default: 100)
  HOST_NAME         - Display name for this host (default: auto-detected hostname)
  PEER_PORT         - HTTP port for peer coordination (default: 7790)
  PEERS             - Comma-separated peer URLs (e.g. http://192.168.0.172:7790,http://192.168.0.67:7790)
  SPEAKER_SCORE     - Speaker quality 0.0-1.0 (default: 1.0); used for Follow-Me TTS delegation
  CONVERSATION_TIMEOUT - Seconds to stay in multi-turn mode after response (default: 8)
"""

import asyncio
import argparse
import io
import json
import logging
import os
import queue
import signal
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np
import requests
import sounddevice as sd
from colorama import Fore, Style, init as colorama_init
from scipy.io.wavfile import write as write_wav
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    from faster_whisper import WhisperModel

    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

try:
    import edge_tts

    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

try:
    import openwakeword
    from openwakeword.model import Model as OWWModel

    HAS_OWW = True
except ImportError:
    HAS_OWW = False

try:
    import pystray
    from PIL import Image, ImageDraw, ImageGrab

    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    import pyperclip

    HAS_CLIPBOARD = True
except ImportError:
    HAS_CLIPBOARD = False

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://192.168.0.67:18789")
GATEWAY_TOKEN = os.getenv("GATEWAY_TOKEN", "opensesame")
AGENT_ID = os.getenv("AGENT_ID", "main")
WAKE_WORDS = [
    w.strip().lower()
    for w in os.getenv("WAKE_WORDS", "hey klatsch,klatsch").split(",")
    if w.strip()
]
TTS_VOICE = os.getenv("TTS_VOICE", "de-DE-ConradNeural")
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL", "base")
MIC_THRESHOLD = float(os.getenv("MIC_THRESHOLD", "0.015"))
SILENCE_SECONDS = float(os.getenv("SILENCE_SECONDS", "1.5"))
SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_SIZE = 1280  # 80ms at 16kHz — good for wake word detection

# Audio device selection (set via CLI args or env vars)
INPUT_DEVICE = os.getenv("INPUT_DEVICE")
OUTPUT_DEVICE = os.getenv("OUTPUT_DEVICE")
VOLUME = int(os.getenv("VOLUME", "100"))
import platform

HOST_NAME = os.getenv("HOST_NAME", platform.node().upper() or "UNKNOWN")

# Peer coordination for Follow-Me output routing
PEER_PORT = int(os.getenv("PEER_PORT", "7790"))
PEERS = [p.strip() for p in os.getenv("PEERS", "").split(",") if p.strip()]
SPEAKER_SCORE = float(
    os.getenv("SPEAKER_SCORE", "1.0")
)  # 0.0=no speaker, 1.0=great speaker
CONVERSATION_TIMEOUT = float(
    os.getenv("CONVERSATION_TIMEOUT", "8")
)  # multi-turn window

# Interrupt keywords that cancel TTS playback
INTERRUPT_WORDS = {
    "stopp",
    "stop",
    "halt",
    "danke",
    "genug",
    "ruhe",
    "still",
    "okay danke",
}
# Pause/resume: "pause" pauses TTS, "weiter" resumes
PAUSE_WORDS = {"pause"}
RESUME_WORDS = {"weiter", "weitermachen", "fortfahren"}

# Intercom patterns: "sag dem <peer>: <message>" or "sage <peer>: <message>"
import re

INTERCOM_PATTERN = re.compile(
    r"^(?:sag|sage|tell)\s+(?:dem|der|the)?\s*([\w-]+)[:\s,]+(.+)$",
    re.IGNORECASE,
)
# Map friendly names to peer URLs (populated from PEERS + HOST_NAME)
PEER_NAME_MAP: dict[str, str] = {}

colorama_init()
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("klatsch")


# ──────────────────────────────────────────────────────────────────────────────
# Audio Device Utilities
# ──────────────────────────────────────────────────────────────────────────────
def list_audio_devices():
    """Print all available audio input/output devices."""
    devices = sd.query_devices()
    default_in = sd.default.device[0]
    default_out = sd.default.device[1]

    print(f"\n{Fore.GREEN}=== Audio Input Devices (Microphones) ==={Style.RESET_ALL}")
    for i, d in enumerate(devices):
        if d["max_input_channels"] > 0:
            marker = " <-- DEFAULT" if i == default_in else ""
            sr = int(d["default_samplerate"])
            print(
                f"  [{i:2d}] {d['name']:<50} (ch: {d['max_input_channels']}, {sr} Hz){Fore.YELLOW}{marker}{Style.RESET_ALL}"
            )

    print(f"\n{Fore.GREEN}=== Audio Output Devices (Speakers) ==={Style.RESET_ALL}")
    for i, d in enumerate(devices):
        if d["max_output_channels"] > 0:
            marker = " <-- DEFAULT" if i == default_out else ""
            sr = int(d["default_samplerate"])
            print(
                f"  [{i:2d}] {d['name']:<50} (ch: {d['max_output_channels']}, {sr} Hz){Fore.YELLOW}{marker}{Style.RESET_ALL}"
            )

    print(
        f"\n{Fore.CYAN}Use --input-device <ID> and --output-device <ID> to select.{Style.RESET_ALL}"
    )
    print(
        f"{Fore.CYAN}Or set INPUT_DEVICE / OUTPUT_DEVICE env vars.{Style.RESET_ALL}\n"
    )


def test_microphone(device_index=None, duration=5):
    """Record from microphone, show VU meter, then play back."""
    dev = device_index
    dev_name = "default"
    if dev is not None:
        dev_name = sd.query_devices(dev)["name"]

    print(f"\n{Fore.GREEN}=== Microphone Test ==={Style.RESET_ALL}")
    print(f"  Device: [{dev or 'default'}] {dev_name}")
    print(f"  Recording {duration}s — speak now!\n")

    frames = []
    peak_levels = []

    def test_callback(indata, frame_count, time_info, status):
        if status:
            log.warning(f"Audio status: {status}")
        frames.append(indata.copy())
        amp = np.abs(indata).max()
        peak_levels.append(amp)
        # Live VU meter
        bar_len = int(min(amp / 0.1, 1.0) * 40)
        bar = "█" * bar_len + "░" * (40 - bar_len)
        level_db = 20 * np.log10(max(amp, 1e-10))
        color = Fore.GREEN if amp < 0.03 else (Fore.YELLOW if amp < 0.08 else Fore.RED)
        sys.stdout.write(
            f"\r  {color}|{bar}| {level_db:+5.1f} dB  peak: {amp:.4f}{Style.RESET_ALL}"
        )
        sys.stdout.flush()

    try:
        with sd.InputStream(
            device=dev,
            channels=CHANNELS,
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            callback=test_callback,
        ):
            time.sleep(duration)
    except Exception as e:
        print(f"\n{Fore.RED}Error opening device: {e}{Style.RESET_ALL}")
        return

    print("\n")

    if not frames:
        print(f"{Fore.RED}No audio captured.{Style.RESET_ALL}")
        return

    audio = np.concatenate(frames, axis=0)
    max_peak = max(peak_levels) if peak_levels else 0
    avg_peak = np.mean(peak_levels) if peak_levels else 0

    print(
        f"  Peak level:    {max_peak:.4f}  ({20 * np.log10(max(max_peak, 1e-10)):+.1f} dB)"
    )
    print(
        f"  Average level: {avg_peak:.4f}  ({20 * np.log10(max(avg_peak, 1e-10)):+.1f} dB)"
    )
    print(f"  Current MIC_THRESHOLD: {MIC_THRESHOLD}")
    if max_peak < MIC_THRESHOLD:
        print(
            f"  {Fore.RED}⚠ Your mic level is below the threshold — lower MIC_THRESHOLD or speak louder.{Style.RESET_ALL}"
        )
    elif avg_peak > MIC_THRESHOLD * 3:
        print(f"  {Fore.GREEN}✓ Mic levels look good.{Style.RESET_ALL}")
    else:
        print(
            f"  {Fore.YELLOW}~ Mic levels are borderline — adjust MIC_THRESHOLD if needed.{Style.RESET_ALL}"
        )

    # Playback
    out_dev = int(OUTPUT_DEVICE) if OUTPUT_DEVICE else None
    out_name = sd.query_devices(out_dev)["name"] if out_dev is not None else "default"
    print(f"\n  Playing back on: [{out_dev or 'default'}] {out_name}")
    try:
        sd.play(audio, samplerate=SAMPLE_RATE, device=out_dev, blocking=True)
    except Exception as e:
        print(f"  {Fore.RED}Playback error: {e}{Style.RESET_ALL}")

    print(f"\n{Fore.GREEN}Test complete.{Style.RESET_ALL}\n")


def detect_output_device(input_device=None, verbose=True):
    """Play a test tone on each output device while recording with mic.
    Returns the device index with the loudest pickup, or None."""
    TONE_FREQ = 440  # Hz (A4)
    TONE_DURATION = 1.5  # seconds per device
    DETECT_THRESHOLD = 0.01  # peak amplitude to count as 'heard'

    in_dev = input_device
    if in_dev is None:
        in_dev = sd.default.device[0]
    in_name = sd.query_devices(in_dev)["name"]

    devices = sd.query_devices()
    outputs = [
        (i, d["name"]) for i, d in enumerate(devices) if d["max_output_channels"] > 0
    ]

    # Generate test tone
    t = np.linspace(0, TONE_DURATION, int(SAMPLE_RATE * TONE_DURATION), endpoint=False)
    tone = (np.sin(2 * np.pi * TONE_FREQ * t) * 0.5).astype(np.float32)

    if verbose:
        print(f"\n{Fore.GREEN}=== Output Device Detection ==={Style.RESET_ALL}")
        print(f"  Mic: [{in_dev}] {in_name}")
        print(f"  Testing {len(outputs)} output devices with {TONE_FREQ}Hz tone...\n")

    results = []
    for idx, name in outputs:
        try:
            if verbose:
                short = name[:50]
                print(f"  [{idx:2d}] {short:50s} ... ", end="", flush=True)
            recording = sd.playrec(
                tone.reshape(-1, 1),
                samplerate=SAMPLE_RATE,
                input_mapping=[1],
                output_mapping=[1],
                device=(in_dev, idx),
                dtype="float32",
            )
            sd.wait()
            peak = float(np.max(np.abs(recording)))
            avg = float(np.mean(np.abs(recording)))
            db = 20 * np.log10(max(peak, 1e-10))
            results.append((idx, name, peak, avg, db))
            if verbose:
                marker = (
                    f" {Fore.GREEN}<-- SOUND DETECTED!{Style.RESET_ALL}"
                    if peak > DETECT_THRESHOLD
                    else ""
                )
                print(f"peak={peak:.4f} ({db:.1f} dB) avg={avg:.4f}{marker}")
            time.sleep(0.2)
        except Exception as e:
            if verbose:
                print(f"{Fore.RED}ERROR: {e}{Style.RESET_ALL}")
            results.append((idx, name, 0, 0, -99))

    detected = [(i, n, p, a, d) for i, n, p, a, d in results if p > DETECT_THRESHOLD]
    detected.sort(key=lambda x: -x[2])  # loudest first

    if verbose:
        print(f"\n{Fore.GREEN}=== Results ==={Style.RESET_ALL}")
        if detected:
            print("  Output devices where sound was picked up by mic:")
            for i, n, p, a, d in detected:
                print(f"    [{i:2d}] {n[:50]:50s}  peak={p:.4f} ({d:.1f} dB)")
            best = detected[0]
            print(
                f"\n  {Fore.GREEN}Best output: [{best[0]}] {best[1]}{Style.RESET_ALL}"
            )
        else:
            print(
                f"  {Fore.RED}No sound detected on any output device!{Style.RESET_ALL}"
            )
            print(
                f"  {Fore.YELLOW}Make sure speakers are on and mic is not muted.{Style.RESET_ALL}"
            )

    return detected[0][0] if detected else None


def set_volume(vol: int):
    """Set the global playback volume (0-100)."""
    global VOLUME
    VOLUME = max(0, min(100, vol))
    log.info(f"Volume set to {VOLUME}%")


def get_input_devices():
    """Return list of (index, name) for input devices."""
    devices = sd.query_devices()
    return [
        (i, d["name"]) for i, d in enumerate(devices) if d["max_input_channels"] > 0
    ]


def get_output_devices():
    """Return list of (index, name) for output devices."""
    devices = sd.query_devices()
    return [
        (i, d["name"]) for i, d in enumerate(devices) if d["max_output_channels"] > 0
    ]


def switch_input_device(device_index):
    """Switch the live audio input stream to a different device."""
    global INPUT_DEVICE
    INPUT_DEVICE = str(device_index)
    old_stream = state.audio_stream
    if old_stream:
        try:
            old_stream.stop()
            old_stream.close()
        except Exception:
            pass
    try:
        new_stream = sd.InputStream(
            device=device_index,
            callback=audio_callback,
            channels=CHANNELS,
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
        )
        new_stream.start()
        state.audio_stream = new_stream
        name = sd.query_devices(device_index)["name"]
        log.info(f"Switched input to [{device_index}] {name}")
    except Exception as e:
        log.error(f"Failed to switch input device: {e}")
        # Try to restart old stream
        if old_stream:
            try:
                old_stream.start()
                state.audio_stream = old_stream
            except Exception:
                pass


def switch_output_device(device_index):
    """Switch the output device for TTS playback."""
    global OUTPUT_DEVICE
    OUTPUT_DEVICE = str(device_index)
    name = sd.query_devices(device_index)["name"]
    log.info(f"Switched output to [{device_index}] {name}")


# ──────────────────────────────────────────────────────────────────────────────
# State
# ──────────────────────────────────────────────────────────────────────────────
class AssistantState:
    def __init__(self):
        self.running = True
        self.is_speaking = False  # TTS playing
        self.is_listening_command = False  # after wake word, capturing user speech
        self.listening_enabled = True  # can be toggled from tray
        self.whisper_model = None
        self.oww_model = None
        self.audio_queue: queue.Queue = queue.Queue()
        self.tray_icon = None
        self.audio_stream = None  # sd.InputStream — held so we can swap device
        self.session_key = f"{HOST_NAME.lower()}-voice-{int(time.time())}"
        # Follow-Me state
        self.last_wake_amplitude = 0.0  # peak amplitude during last wake word
        self.last_wake_time = 0.0  # timestamp of last wake word
        self.peer_claims: dict = {}  # host -> (amplitude, timestamp, speaker_score)
        self.follow_me_enabled = len(PEERS) > 0  # auto-enable if peers configured
        self.best_speaker_peer: str | None = (
            None  # peer URL with best speaker, set after claim
        )
        # TTS interrupt
        self.tts_interrupt = False  # flag to stop ongoing TTS
        self.tts_paused = False  # flag to pause ongoing TTS
        self.tts_resume_event = threading.Event()  # signalled when TTS should resume
        self.tts_resume_event.set()  # starts in non-paused state
        # Multi-turn conversation
        self.conversation_mode = False
        self.last_response_time = 0.0
        # Presence detection
        self.presence_active = False  # True = someone at keyboard/mouse
        self.last_activity_time = 0.0
        # Disk watcher
        self.known_disks: set = set()  # partition mountpoints seen last check
        # Reminders
        self.reminders: list = []  # list of (fire_at: float, text: str)


state = AssistantState()


# ──────────────────────────────────────────────────────────────────────────────
# Follow-Me: Peer Coordination
# ──────────────────────────────────────────────────────────────────────────────
WAKE_CLAIM_WINDOW = 1.0  # seconds: claims within this window compete


class PeerHandler(BaseHTTPRequestHandler):
    """Tiny HTTP handler for peer wake-word claims."""

    def log_message(self, fmt, *args):
        pass  # suppress default access log

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "host": HOST_NAME,
                        "app": "klatsch",
                        "listening": state.listening_enabled,
                        "presence": state.presence_active,
                    }
                ).encode()
            )
        elif self.path == "/inventory":
            data = scan_local_inventory()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
        elif self.path == "/screenshot":
            data = take_screenshot()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
        elif self.path == "/clipboard":
            data = {"host": HOST_NAME, "text": get_clipboard_text()}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
        elif self.path == "/processes":
            data = get_processes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
        elif self.path == "/syshealth":
            data = get_syshealth()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
        elif self.path.startswith("/find-file"):
            from urllib.parse import urlparse, parse_qs

            q = parse_qs(urlparse(self.path).query).get("q", [""])[0]
            data = find_files(q)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if self.path == "/wake-claim":
            peer_host = body.get("host", "unknown")
            peer_amp = float(body.get("amplitude", 0))
            peer_ts = float(body.get("timestamp", 0))
            state.peer_claims[peer_host] = (peer_amp, peer_ts)
            resp = {
                "host": HOST_NAME,
                "amplitude": state.last_wake_amplitude,
                "timestamp": state.last_wake_time,
                "speaker_score": SPEAKER_SCORE,
            }
            self._json(200, resp)
        elif self.path == "/speak":
            text = body.get("text", "")
            if text:
                threading.Thread(target=speak, args=(text,), daemon=True).start()
            self._json(200, {"ok": True, "host": HOST_NAME})
        elif self.path == "/notify":
            text = body.get("text", body.get("message", ""))
            source = body.get("from", body.get("source", "System"))
            if text:
                notification = f"{source} sagt: {text}" if source != "System" else text
                threading.Thread(
                    target=speak, args=(notification,), daemon=True
                ).start()
            self._json(200, {"ok": True, "host": HOST_NAME})
        elif self.path == "/intercom":
            text = body.get("text", "")
            sender = body.get("from", "Jemand")
            if text:
                announcement = f"Durchsage von {sender}: {text}"
                threading.Thread(
                    target=speak, args=(announcement,), daemon=True
                ).start()
            self._json(200, {"ok": True, "host": HOST_NAME})
        elif self.path == "/clipboard":
            text = body.get("text", "")
            ok = set_clipboard_text(text)
            self._json(200, {"ok": ok, "host": HOST_NAME})
        elif self.path == "/open-app":
            app = body.get("app", "")
            result = open_application(app)
            self._json(200, {"ok": result, "host": HOST_NAME, "app": app})
        elif self.path == "/remind":
            text = body.get("text", "")
            seconds = float(body.get("seconds", 0))
            minutes = float(body.get("minutes", 0))
            delay = seconds + minutes * 60
            if text and delay > 0:
                fire_at = time.time() + delay
                state.reminders.append((fire_at, text))
                log.info(f"Reminder in {delay:.0f}s: {text}")
            self._json(200, {"ok": True, "host": HOST_NAME, "fire_in_seconds": delay})
        elif self.path == "/broadcast":
            # Push a message to all peers (fire-and-forget in background)
            text = body.get("text", body.get("message", ""))
            endpoint = body.get("endpoint", "/notify")
            if text:
                threading.Thread(
                    target=broadcast_to_peers, args=(text, endpoint), daemon=True
                ).start()
            self._json(200, {"ok": True, "host": HOST_NAME, "peers": len(PEERS)})
        else:
            self.send_response(404)
            self.end_headers()

    def _json(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ─────────────────────────────────────── Utility functions ──────────────────


def take_screenshot() -> dict:
    """Capture the primary screen and return a base64-encoded PNG."""
    import base64, io

    result: dict = {"host": HOST_NAME, "image": None, "error": None}
    if not HAS_TRAY:  # PIL already imported via tray
        result["error"] = "Pillow not available"
        return result
    try:
        img = ImageGrab.grab()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result["image"] = base64.b64encode(buf.getvalue()).decode()
        result["size"] = {"width": img.width, "height": img.height}
    except Exception as exc:
        result["error"] = str(exc)
    return result


def get_clipboard_text() -> str:
    """Read text from the system clipboard."""
    if HAS_CLIPBOARD:
        try:
            return pyperclip.paste() or ""
        except Exception:
            pass
    # Fallback: Windows win32api
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.OpenClipboard(0)  # type: ignore[attr-defined]
            handle = ctypes.windll.user32.GetClipboardData(13)  # CF_UNICODETEXT
            ctypes.windll.user32.CloseClipboard()
            return ctypes.wstring_at(handle) if handle else ""
        except Exception:
            pass
    return ""


def set_clipboard_text(text: str) -> bool:
    """Write text to the system clipboard."""
    if HAS_CLIPBOARD:
        try:
            pyperclip.copy(text)
            return True
        except Exception:
            pass
    return False


def get_processes() -> dict:
    """Return top 20 processes by CPU usage."""
    if not HAS_PSUTIL:
        return {"host": HOST_NAME, "error": "psutil not available"}
    procs = []
    for p in sorted(
        psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]),
        key=lambda x: x.info.get("cpu_percent") or 0,
        reverse=True,
    )[:20]:
        procs.append(
            {
                "pid": p.info["pid"],
                "name": p.info["name"],
                "cpu": round(p.info.get("cpu_percent") or 0, 1),
                "mem": round(p.info.get("memory_percent") or 0, 1),
            }
        )
    return {"host": HOST_NAME, "processes": procs}


def get_syshealth() -> dict:
    """Return CPU, RAM, disk and (where available) temperature readings."""
    if not HAS_PSUTIL:
        return {"host": HOST_NAME, "error": "psutil not available"}
    data: dict = {
        "host": HOST_NAME,
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "ram_percent": psutil.virtual_memory().percent,
        "disks": [],
        "temps": {},
    }
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            data["disks"].append(
                {
                    "mount": part.mountpoint,
                    "total_gb": round(usage.total / 1e9, 1),
                    "used_gb": round(usage.used / 1e9, 1),
                    "free_gb": round(usage.free / 1e9, 1),
                    "percent": usage.percent,
                }
            )
        except PermissionError:
            pass
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            data["temps"] = {k: [t.current for t in v] for k, v in temps.items()}
    except AttributeError:
        pass  # Windows doesn't expose sensor temps via psutil
    return data


def find_files(query: str, roots: list[str] | None = None) -> dict:
    """Search for files whose name contains *query* (case-insensitive)."""
    import os, fnmatch

    if not query:
        return {"host": HOST_NAME, "results": []}
    if roots is None:
        # Sensible defaults (adjust paths for your system)
        defaults = [
            r"D:\Projekte",
            r"C:\Users",
            os.path.expanduser("~"),
            r"D:\OpenClaw",
        ]
        roots = [r for r in defaults if os.path.isdir(r)]
    results: list[str] = []
    pattern = f"*{query.lower()}*"
    for root in roots:
        for dirpath, _dirs, files in os.walk(root):
            # Skip very deep or hidden/system dirs
            depth = dirpath.replace(root, "").count(os.sep)
            if depth > 6:
                _dirs.clear()
                continue
            skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv"}
            _dirs[:] = [d for d in _dirs if d not in skip_dirs]
            for fname in files:
                if fnmatch.fnmatch(fname.lower(), pattern):
                    results.append(os.path.join(dirpath, fname))
                    if len(results) >= 50:
                        return {
                            "host": HOST_NAME,
                            "query": query,
                            "results": results,
                            "truncated": True,
                        }
    return {"host": HOST_NAME, "query": query, "results": results}


# Map of voice/API app names → Windows start commands
_APP_MAP: dict[str, list[str]] = {
    "vscode": ["code"],
    "vs code": ["code"],
    "code": ["code"],
    "notepad": ["notepad.exe"],
    "explorer": ["explorer.exe"],
    "chrome": [
        "chrome",
        "google-chrome",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ],
    "firefox": ["firefox"],
    "terminal": ["wt.exe"],  # Windows Terminal
    "powershell": ["powershell.exe"],
    "cmd": ["cmd.exe"],
    "discord": [
        r"C:\Users\dano\AppData\Local\Discord\app-latest\Discord.exe",
        "discord",
    ],
    "spotify": [r"C:\Users\dano\AppData\Roaming\Spotify\Spotify.exe", "spotify"],
    "task manager": ["taskmgr.exe"],
    "rechner": ["calc.exe"],
    "calculator": ["calc.exe"],
}


def open_application(name: str) -> bool:
    """Launch an application by name. Returns True if launch was attempted."""
    import subprocess, shutil

    name_lower = name.lower().strip()
    # Exact or partial match in app map
    candidates = _APP_MAP.get(name_lower)
    if not candidates:
        for key, cmds in _APP_MAP.items():
            if name_lower in key or key in name_lower:
                candidates = cmds
                break
    if candidates:
        for cmd in candidates:
            try:
                subprocess.Popen(cmd, shell=(not shutil.which(cmd)))
                log.info(f"Opened app: {cmd}")
                return True
            except (FileNotFoundError, OSError):
                continue
    # Fallback: try to start by name directly
    try:
        import subprocess

        subprocess.Popen(name, shell=True)
        return True
    except Exception:
        return False


def query_ollama(prompt: str, model: str = "llama3", host: str = "localhost") -> str:
    """Send a prompt to a local Ollama instance. Returns response text."""
    try:
        url = f"http://{host}:11434/api/generate"
        resp = requests.post(
            url, json={"model": model, "prompt": prompt, "stream": False}, timeout=30
        )
        if resp.ok:
            return resp.json().get("response", "").strip()
    except Exception as exc:
        log.warning(f"Ollama query failed: {exc}")
    return ""


# ──────────────────────────────────────── Background threads ─────────────────


def presence_watcher():
    """Track mouse position to detect if someone is at the machine."""
    if not HAS_PSUTIL:
        return
    prev_pos = None
    while state.running:
        try:
            mouse = psutil.Process(os.getpid())  # dummy — use win32api on Windows
            if sys.platform == "win32":
                import ctypes

                pt = ctypes.wintypes.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                pos = (pt.x, pt.y)
            else:
                pos = None
            if pos != prev_pos and pos is not None:
                state.presence_active = True
                state.last_activity_time = time.time()
                prev_pos = pos
            elif time.time() - state.last_activity_time > 300:
                # 5 min of no movement → away
                state.presence_active = False
        except Exception:
            pass
        time.sleep(5)


def disk_watcher():
    """Watch for newly connected drives/volumes and announce them."""
    if not HAS_PSUTIL:
        return
    # Initialise known disks silently on first run
    state.known_disks = {p.mountpoint for p in psutil.disk_partitions(all=False)}
    while state.running:
        time.sleep(10)
        try:
            current = {p.mountpoint for p in psutil.disk_partitions(all=False)}
            new = current - state.known_disks
            for mount in new:
                log.info(f"New drive detected: {mount}")
                label = mount.rstrip("\\").rstrip("/").split("\\")[-1] or mount
                threading.Thread(
                    target=speak,
                    args=(f"Neues Laufwerk verbunden: {label}",),
                    daemon=True,
                ).start()
            state.known_disks = current
        except Exception as exc:
            log.debug(f"disk_watcher error: {exc}")


def reminder_watcher():
    """Fire scheduled reminders when their time comes."""
    while state.running:
        time.sleep(5)
        now = time.time()
        due = [(ts, txt) for ts, txt in state.reminders if ts <= now]
        if due:
            state.reminders = [(ts, txt) for ts, txt in state.reminders if ts > now]
            for _, txt in due:
                log.info(f"Reminder fired: {txt}")
                threading.Thread(
                    target=speak, args=(f"Erinnerung: {txt}",), daemon=True
                ).start()


_morning_briefing_done_date: str = ""  # guard: only once per day


def morning_briefing():
    """Between 06:00–09:00 on first run of the day, fetch a briefing from the gateway."""
    global _morning_briefing_done_date
    # Wait 30 s for everything to settle before the first check
    time.sleep(30)
    while state.running:
        now = time.localtime()
        today = time.strftime("%Y-%m-%d")
        if 6 <= now.tm_hour < 9 and _morning_briefing_done_date != today:
            _morning_briefing_done_date = today
            log.info("Morning briefing triggered")
            answer = send_to_gateway(
                "Guten Morgen! Gib mir bitte eine kurze Zusammenfassung: Datum, Uhrzeit, "
                "aktuelles Wetter falls bekannt, und was heute wichtig sein könnte."
            )
            if answer:
                threading.Thread(target=speak, args=(answer,), daemon=True).start()
        time.sleep(60)  # check every minute


def focus_window(name: str) -> bool:
    """Bring a window matching *name* (substring, case-insensitive) to the foreground."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        EnumWindows = user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)
        )

        name_lower = name.lower()
        found_hwnd = ctypes.c_int(0)
        buf = ctypes.create_unicode_buffer(512)

        def _cb(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            user32.GetWindowTextW(hwnd, buf, 512)
            title = buf.value.lower()
            if name_lower in title:
                found_hwnd.value = hwnd
                return False  # stop enumeration
            return True

        EnumWindows(EnumWindowsProc(_cb), 0)
        if found_hwnd.value:
            hwnd = found_hwnd.value
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            log.info(f"Focused window: {hwnd}")
            return True
    except Exception as exc:
        log.warning(f"focus_window error: {exc}")
    return False


def broadcast_to_peers(text: str, endpoint: str = "/notify") -> dict:
    """Send a message to ALL configured peers. Returns {peer_url: ok/error}."""
    results: dict = {}
    peers = list(PEERS) if PEERS else []
    for peer_url in peers:
        try:
            resp = requests.post(
                f"{peer_url}{endpoint}",
                json={"text": text, "from": HOST_NAME, "source": HOST_NAME},
                timeout=3,
            )
            results[peer_url] = (
                "ok" if resp.status_code == 200 else f"http {resp.status_code}"
            )
        except Exception as exc:
            results[peer_url] = str(exc)
    log.info(f"broadcast_to_peers({endpoint}): {results}")
    return results


def scan_local_inventory() -> dict:
    """Scan local disks and project directories. Returns JSON-serialisable dict.

    Detects drives/volumes by label+UUID (Windows: wmic, Linux: lsblk).
    Finds Git repos under known project roots and reports branch/status.
    """
    import subprocess, shutil

    host_info = {
        "host": HOST_NAME,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "app": "klatsch",
        "disks": [],
        "projects": [],
    }

    # ── Disk scan ──
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                [
                    "wmic",
                    "logicaldisk",
                    "get",
                    "DeviceID,VolumeName,Size,FreeSpace,VolumeSerialNumber",
                    "/format:csv",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            for line in result.stdout.splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 6 and parts[1] and parts[1] != "DeviceID":
                    drive_id, free, size, serial, label = (
                        parts[1],
                        parts[2],
                        parts[3],
                        parts[4],
                        parts[5],
                    )
                    try:
                        size_gb = round(int(size) / 1e9, 1) if size else 0
                        free_gb = round(int(free) / 1e9, 1) if free else 0
                    except ValueError:
                        size_gb, free_gb = 0, 0
                    host_info["disks"].append(
                        {
                            "id": drive_id,
                            "label": label,
                            "serial": serial,
                            "size_gb": size_gb,
                            "free_gb": free_gb,
                        }
                    )
        else:
            # Linux (Docker / WSL)
            result = subprocess.run(
                ["lsblk", "-o", "NAME,LABEL,UUID,SIZE,MOUNTPOINT", "-J"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)

                def _walk(devices):
                    for d in devices:
                        if d.get("mountpoint"):
                            host_info["disks"].append(
                                {
                                    "id": d.get("mountpoint"),
                                    "label": d.get("label", ""),
                                    "serial": d.get("uuid", ""),
                                    "name": d.get("name", ""),
                                    "size": d.get("size", ""),
                                }
                            )
                        for child in d.get("children", []):
                            _walk([child])

                _walk(data.get("blockdevices", []))
    except Exception as e:
        host_info["disk_error"] = str(e)

    # ── Project scan ──
    # Windows: scan D:\Projekte and any other known roots; Linux: /mnt/projects
    roots = []
    if sys.platform == "win32":
        for candidate in ["D:\\Projekte", "C:\\Projekte", "E:\\Projekte"]:
            if Path(candidate).exists():
                roots.append(Path(candidate))
    else:
        for candidate in ["/mnt/projects", "/mnt/d/Projekte", "/home/dano/Projekte"]:
            if Path(candidate).exists():
                roots.append(Path(candidate))

    git = shutil.which("git")

    for root in roots:
        try:
            for item in sorted(root.iterdir()):
                if not item.is_dir():
                    continue
                git_dir = item / ".git"
                if not git_dir.exists():
                    continue
                proj = {
                    "name": item.name,
                    "path": str(item),
                    "root": str(root),
                }
                if git:
                    try:
                        branch = subprocess.run(
                            [git, "-C", str(item), "rev-parse", "--abbrev-ref", "HEAD"],
                            capture_output=True,
                            text=True,
                            timeout=5,
                        ).stdout.strip()
                        status = subprocess.run(
                            [git, "-C", str(item), "status", "--short"],
                            capture_output=True,
                            text=True,
                            timeout=5,
                        ).stdout.strip()
                        last = subprocess.run(
                            [git, "-C", str(item), "log", "-1", "--format=%cr · %s"],
                            capture_output=True,
                            text=True,
                            timeout=5,
                        ).stdout.strip()
                        remote = subprocess.run(
                            [git, "-C", str(item), "remote", "get-url", "origin"],
                            capture_output=True,
                            text=True,
                            timeout=5,
                        ).stdout.strip()
                        proj["branch"] = branch
                        proj["dirty"] = bool(status)
                        proj["last_commit"] = last
                        proj["remote"] = remote
                    except Exception:
                        pass
                host_info["projects"].append(proj)
        except PermissionError:
            pass

    return host_info


def start_peer_server():
    """Start the peer coordination HTTP server in a daemon thread."""
    try:
        server = HTTPServer(("0.0.0.0", PEER_PORT), PeerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        log.info(f"Peer coordination server on port {PEER_PORT}")
    except Exception as e:
        log.warning(f"Could not start peer server on port {PEER_PORT}: {e}")


def broadcast_wake_claim(amplitude: float) -> bool:
    """Broadcast our wake-word detection to all peers.
    Returns True if we have the strongest signal (should output), False otherwise."""
    now = time.time()
    state.last_wake_amplitude = amplitude
    state.last_wake_time = now
    state.peer_claims.clear()

    if not PEERS:
        return True  # no peers, always output

    # Send claim to all peers in parallel
    peer_speaker_scores: dict = {}  # peer_url -> speaker_score

    def send_claim(peer_url):
        try:
            resp = requests.post(
                f"{peer_url}/wake-claim",
                json={
                    "host": HOST_NAME,
                    "amplitude": amplitude,
                    "timestamp": now,
                    "speaker_score": SPEAKER_SCORE,
                },
                timeout=0.5,
            )
            if resp.status_code == 200:
                data = resp.json()
                peer_host = data.get("host", peer_url)
                peer_amp = float(data.get("amplitude", 0))
                peer_ts = float(data.get("timestamp", 0))
                peer_spk = float(data.get("speaker_score", 1.0))
                peer_speaker_scores[peer_url] = peer_spk
                # Only consider if peer also detected wake word recently
                if abs(peer_ts - now) < WAKE_CLAIM_WINDOW:
                    state.peer_claims[peer_host] = (peer_amp, peer_ts, peer_spk)
        except Exception:
            pass  # peer offline or unreachable

    threads = [threading.Thread(target=send_claim, args=(p,)) for p in PEERS]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=0.6)

    # Find peer with best speaker (for potential TTS delegation)
    best_spk_url = None
    best_spk_score = SPEAKER_SCORE
    for peer_url, spk_score in peer_speaker_scores.items():
        if spk_score > best_spk_score:
            best_spk_score = spk_score
            best_spk_url = peer_url
    state.best_speaker_peer = best_spk_url  # None means we have the best speaker

    # Now decide: am I the strongest input signal?
    my_amp = amplitude
    for peer_host, (peer_amp, peer_ts, _peer_spk) in state.peer_claims.items():
        if peer_amp > my_amp:
            log.info(
                f"Follow-Me: {peer_host} has stronger signal ({peer_amp:.4f} > {my_amp:.4f}), deferring"
            )
            return False
        elif peer_amp == my_amp:
            # Tie-break by hostname (alphabetical)
            if peer_host < HOST_NAME:
                log.info(f"Follow-Me: tie with {peer_host}, deferring (alphabetical)")
                return False

    log.info(f"Follow-Me: I have the strongest signal ({my_amp:.4f}), I will respond")
    if state.best_speaker_peer:
        log.info(
            f"Follow-Me: TTS will be delegated to {state.best_speaker_peer} (speaker_score {best_spk_score:.1f} > {SPEAKER_SCORE:.1f})"
        )
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Whisper STT
# ──────────────────────────────────────────────────────────────────────────────
def load_whisper():
    if not HAS_WHISPER:
        log.error("faster-whisper not installed. Run: pip install faster-whisper")
        return
    log.info(f"Loading Whisper model '{WHISPER_MODEL_SIZE}'...")
    state.whisper_model = WhisperModel(
        WHISPER_MODEL_SIZE, device="cpu", compute_type="int8"
    )
    log.info("Whisper model loaded.")


def transcribe(audio_np: np.ndarray) -> str:
    """Transcribe float32 audio numpy array to text."""
    if state.whisper_model is None:
        return ""
    try:
        # faster-whisper accepts float32 numpy array directly
        segments, _info = state.whisper_model.transcribe(
            audio_np.flatten().astype(np.float32),
            language="de",
            beam_size=5,
            vad_filter=True,
        )
        text = " ".join(seg.text for seg in segments).strip()
        return text
    except Exception as e:
        log.error(f"Transcription error: {e}")
        return ""


# ──────────────────────────────────────────────────────────────────────────────
# Wake Word Detection
# Uses OpenWakeWord (lightweight) when available, or Whisper transcription fallback
# ──────────────────────────────────────────────────────────────────────────────
OWW_THRESHOLD = 0.5  # confidence threshold for openwakeword detection


def load_oww():
    """Load OpenWakeWord model if available."""
    if not HAS_OWW:
        return
    try:
        openwakeword.utils.download_models()
        state.oww_model = OWWModel(
            wakeword_models=[
                "hey_jarvis_v0.1"
            ],  # closest built-in; works for custom trigger
            inference_framework="onnx",
        )
        log.info("OpenWakeWord model loaded (lightweight wake detection enabled)")
    except Exception as e:
        log.warning(f"OpenWakeWord load failed, using Whisper fallback: {e}")
        state.oww_model = None


def oww_check_wake(audio_block: np.ndarray) -> bool:
    """Check a single audio block for wake word using OpenWakeWord.
    Returns True if wake word detected with high confidence."""
    if state.oww_model is None:
        return False
    try:
        # OWW expects int16 audio at 16kHz
        audio_int16 = (audio_block.flatten() * 32767).astype(np.int16)
        prediction = state.oww_model.predict(audio_int16)
        for model_name, score in prediction.items():
            if score > OWW_THRESHOLD:
                log.debug(f"OWW wake detection: {model_name}={score:.3f}")
                return True
    except Exception as e:
        log.debug(f"OWW prediction error: {e}")
    return False


def check_wake_word_in_text(text: str) -> bool:
    """Simple text-based wake word check on transcription."""
    lower = text.lower().strip()
    for ww in WAKE_WORDS:
        if lower.startswith(ww):
            return True
    return False


def strip_wake_word(text: str) -> str:
    """Remove wake word prefix from transcribed text."""
    lower = text.lower().strip()
    for ww in WAKE_WORDS:
        if lower.startswith(ww):
            remainder = text[len(ww) :].strip().lstrip(",").lstrip(".").strip()
            return remainder
    return text


# ──────────────────────────────────────────────────────────────────────────────
# Interrupt / Pause / Resume helpers
# ──────────────────────────────────────────────────────────────────────────────
def check_interrupt_word(text: str) -> bool:
    """Check if transcribed text contains an interrupt keyword."""
    lower = text.lower().strip().rstrip(".!?,;:")
    return lower in INTERRUPT_WORDS or any(w in lower.split() for w in INTERRUPT_WORDS)


def check_pause_word(text: str) -> bool:
    """Check if transcribed text is a pause command."""
    lower = text.lower().strip().rstrip(".!?,;:")
    return lower in PAUSE_WORDS or any(w in lower.split() for w in PAUSE_WORDS)


def check_resume_word(text: str) -> bool:
    """Check if transcribed text is a resume command."""
    lower = text.lower().strip().rstrip(".!?,;:")
    return lower in RESUME_WORDS or any(w in lower.split() for w in RESUME_WORDS)


# ──────────────────────────────────────────────────────────────────────────────
# Intercom helpers
# ──────────────────────────────────────────────────────────────────────────────
def check_intercom_command(text: str) -> tuple[str, str] | None:
    """Parse intercom command from text. Returns (peer_name, message) or None."""
    m = INTERCOM_PATTERN.match(text.strip())
    if m:
        return m.group(1).strip().lower(), m.group(2).strip()
    return None


def send_intercom(peer_name: str, message: str) -> bool:
    """Send intercom message to a named peer. Returns True on success."""
    url = PEER_NAME_MAP.get(peer_name)
    if not url:
        log.warning(
            f"Intercom: unknown peer '{peer_name}', known: {list(PEER_NAME_MAP.keys())}"
        )
        return False
    try:
        resp = requests.post(
            f"{url}/intercom",
            json={"text": message, "from": HOST_NAME},
            timeout=2,
        )
        return resp.status_code == 200
    except Exception as e:
        log.error(f"Intercom send failed: {e}")
        return False


def _handle_local_command(text: str) -> bool:
    """Handle locally-executable voice commands without gateway round-trip.

    Returns True if the command was handled (caller should skip send_to_gateway).
    """
    import re

    tl = text.lower().strip()

    # ── App open: "öffne chrome" / "starte notepad" ──
    m = re.match(r"(?:öffne?|starte?|start)\s+(.+)", tl)
    if m:
        app = m.group(1).strip()
        if open_application(app):
            threading.Thread(target=speak, args=(f"Öffne {app}.",), daemon=True).start()
        else:
            threading.Thread(
                target=speak, args=(f"Konnte {app} nicht öffnen.",), daemon=True
            ).start()
        return True

    # ── Read clipboard ──
    if any(w in tl for w in ("zwischenablage", "clipboard", "was ist in der ablage")):
        clip = get_clipboard_text()
        msg = (
            f"In der Zwischenablage steht: {clip}"
            if clip
            else "Die Zwischenablage ist leer."
        )
        threading.Thread(target=speak, args=(msg,), daemon=True).start()
        return True

    # ── Reminder: "erinnere mich in 10 minuten mit …" ──
    m = re.match(
        r"erinnere?\s+(?:mich\s+)?in\s+(\d+)\s*(minute[n]?|sekunde[n]?|stunde[n]?)\s*(?:an\s+|daran\s+|dass?\s+)?(.+)?$",
        tl,
    )
    if m:
        amount = int(m.group(1))
        unit = m.group(2).rstrip("n")  # minuten→minute etc.
        reminder_text = (m.group(3) or "Zeit ist um").strip()
        if "sekunde" in unit:
            delay = amount
        elif "stunde" in unit:
            delay = amount * 3600
        else:
            delay = amount * 60
        fire_at = time.time() + delay
        state.reminders.append((fire_at, reminder_text))
        label = f"{amount} {unit}{'n' if amount != 1 else ''}"
        threading.Thread(
            target=speak, args=(f"Okay, ich erinnere dich in {label}.",), daemon=True
        ).start()
        return True

    # ── System health via voice ──
    if any(
        w in tl
        for w in (
            "systemstatus",
            "cpu auslastung",
            "speicher",
            "wie viel ram",
            "festplatte",
        )
    ):
        health = get_syshealth()
        cpu = health.get("cpu_percent", "?")
        ram = health.get("ram_percent", "?")
        threading.Thread(
            target=speak,
            args=(f"CPU {cpu} Prozent, RAM {ram} Prozent.",),
            daemon=True,
        ).start()
        return True

    # ── Ollama local query: "frag ollama …" ──
    m = re.match(r"frag(?:e)?\s+(?:ollama|ki|lokal)\s+(.+)", tl)
    if m:
        prompt = m.group(1).strip()

        def _ask():
            threading.Thread(
                target=speak, args=("Frage Ollama...",), daemon=True
            ).start()
            answer = query_ollama(prompt)
            if answer:
                speak(answer)
            else:
                speak("Ollama hat nicht geantwortet.")

        threading.Thread(target=_ask, daemon=True).start()
        return True

    # ── Focus window: "fokussiere Discord" / "bringe Chrome nach vorne" ──
    m = re.match(
        r"(?:fokussiere?|bringe?|zeige?)\s+(.+?)(?:\s+(?:nach\s+vorne|in\s+den\s+vordergrund))?\s*$",
        tl,
    )
    if m and any(
        w in tl
        for w in ("fokus", "vorne", "vordergrund", "bringe", "zeige", "fokussiere")
    ):
        target = m.group(1).strip()
        if focus_window(target):
            threading.Thread(
                target=speak, args=(f"{target} ist jetzt vorne.",), daemon=True
            ).start()
        else:
            threading.Thread(
                target=speak, args=(f"Konnte {target} nicht finden.",), daemon=True
            ).start()
        return True

    # ── Broadcast to all peers: "sag allen dass …" / "melde überall …" ──
    m = re.match(
        r"(?:sag|sage|ruf|melde|teile?\s+mit)\s+(?:allen|alle|überall)\s+(?:dass?\s+)?(.+)",
        tl,
    )
    if m:
        msg = m.group(1).strip()
        threading.Thread(target=speak, args=("Sende an alle...",), daemon=True).start()
        threading.Thread(
            target=broadcast_to_peers, args=(msg, "/notify"), daemon=True
        ).start()
        return True

    return False


def build_peer_name_map():
    """Query all peers for their host name and build name→URL map."""
    for peer_url in PEERS:
        try:
            resp = requests.get(f"{peer_url}/health", timeout=1)
            if resp.status_code == 200:
                data = resp.json()
                name = data.get("host", peer_url).lower()
                PEER_NAME_MAP[name] = peer_url
                log.info(f"Peer map: {name} → {peer_url}")
        except Exception:
            log.debug(f"Peer {peer_url} unreachable for name map")


# ──────────────────────────────────────────────────────────────────────────────
# Confirmation beep
# ──────────────────────────────────────────────────────────────────────────────
def play_beep(freq: int = 880, duration: float = 0.15, volume: float = 0.3):
    """Play a short confirmation beep with fade envelope."""
    t = np.linspace(0, duration, int(24000 * duration), endpoint=False)
    tone = np.sin(2 * np.pi * freq * t).astype(np.float32)
    # Fade in/out to avoid clicks
    fade_len = min(int(0.01 * 24000), len(tone) // 4)
    tone[:fade_len] *= np.linspace(0, 1, fade_len)
    tone[-fade_len:] *= np.linspace(1, 0, fade_len)
    tone *= volume
    out_dev = int(OUTPUT_DEVICE) if OUTPUT_DEVICE else None
    try:
        sd.play(tone, samplerate=24000, device=out_dev, blocking=True)
    except Exception as e:
        log.debug(f"Beep failed: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Gateway API
# ──────────────────────────────────────────────────────────────────────────────
def send_to_gateway(message: str) -> str:
    """Send message to OpenClaw Gateway via OpenAI-compatible chat completions API."""
    url = f"{GATEWAY_URL}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GATEWAY_TOKEN}",
        "Content-Type": "application/json",
        "x-openclaw-agent-id": AGENT_ID,
        "x-openclaw-session-key": state.session_key,
    }
    payload = {
        "model": "default",
        "stream": False,
        "messages": [
            {"role": "user", "content": message},
        ],
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
        return ""
    except requests.exceptions.ConnectionError:
        log.error(f"Cannot connect to gateway at {GATEWAY_URL}")
        return "Ich kann den Server gerade nicht erreichen."
    except requests.exceptions.Timeout:
        log.error("Gateway request timed out")
        return "Die Anfrage hat zu lange gedauert."
    except Exception as e:
        log.error(f"Gateway error: {e}")
        return "Ein Fehler ist aufgetreten."


# ──────────────────────────────────────────────────────────────────────────────
# TTS via edge-tts
# ──────────────────────────────────────────────────────────────────────────────
async def _speak_edge_tts(text: str):
    """Generate speech audio via edge-tts and play it. Supports TTS interrupt."""
    communicate = edge_tts.Communicate(text, TTS_VOICE)
    audio_chunks = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_chunks.append(chunk["data"])
        # Check for interrupt during streaming
        if state.tts_interrupt:
            log.info("TTS interrupted during streaming")
            return

    if not audio_chunks:
        return

    audio_data = b"".join(audio_chunks)
    # edge-tts returns MP3; use a temp file and sounddevice for playback
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(audio_data)
        tmp_path = f.name

    try:
        # Use ffmpeg or a simple player — sounddevice needs raw PCM.
        # Decode MP3 to raw PCM via subprocess ffmpeg, then play via sounddevice
        # for proper device selection and volume control.
        import subprocess, shutil

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            # Decode MP3 → raw PCM float32
            result = subprocess.run(
                [
                    ffmpeg,
                    "-i",
                    tmp_path,
                    "-f",
                    "f32le",
                    "-acodec",
                    "pcm_f32le",
                    "-ar",
                    "24000",
                    "-ac",
                    "1",
                    "-loglevel",
                    "quiet",
                    "-",
                ],
                capture_output=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout:
                pcm = np.frombuffer(result.stdout, dtype=np.float32)
                # Apply volume
                pcm = pcm * (VOLUME / 100.0)
                out_dev = int(OUTPUT_DEVICE) if OUTPUT_DEVICE else None
                # Play in chunks so we can interrupt or pause
                chunk_size = 24000  # 1 second chunks
                for i in range(0, len(pcm), chunk_size):
                    if state.tts_interrupt:
                        sd.stop()
                        log.info("TTS playback interrupted")
                        return
                    # Wait here while paused (blocks until resume)
                    if state.tts_paused:
                        log.info("TTS paused — waiting for 'weiter'")
                        print(
                            f"{Fore.YELLOW}⏸ TTS pausiert — sag 'weiter' zum Fortfahren{Style.RESET_ALL}"
                        )
                        state.tts_resume_event.wait()
                        if state.tts_interrupt:
                            return
                        log.info("TTS resumed")
                        print(f"{Fore.GREEN}▶ TTS fortgesetzt{Style.RESET_ALL}")
                    chunk = pcm[i : i + chunk_size]
                    sd.play(chunk, samplerate=24000, device=out_dev, blocking=True)
            else:
                # Fallback to ffplay
                ffplay = _find_ffplay()
                if ffplay:
                    vol_str = str(VOLUME / 100.0)
                    subprocess.run(
                        [
                            ffplay,
                            "-nodisp",
                            "-autoexit",
                            "-loglevel",
                            "quiet",
                            "-volume",
                            vol_str,
                            tmp_path,
                        ],
                        check=False,
                        timeout=60,
                    )
        else:
            ffplay = _find_ffplay()
            if ffplay:
                subprocess.run(
                    [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", tmp_path],
                    check=False,
                    timeout=60,
                )
            else:
                # PowerShell fallback for Windows
                subprocess.run(
                    [
                        "powershell",
                        "-c",
                        f'(New-Object Media.SoundPlayer "{tmp_path}").PlaySync()',
                    ],
                    check=False,
                    timeout=60,
                )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _find_ffplay() -> str | None:
    """Find ffplay executable."""
    import shutil

    return shutil.which("ffplay")


def delegate_tts_to_peer(text: str, peer_url: str) -> bool:
    """Ask a peer to play TTS. Returns True if peer accepted."""
    try:
        resp = requests.post(
            f"{peer_url}/speak",
            json={"text": text, "from": HOST_NAME},
            timeout=10,
        )
        if resp.status_code == 200:
            log.info(f"TTS delegated to {peer_url}")
            return True
    except Exception as e:
        log.warning(f"TTS delegation to {peer_url} failed: {e}")
    return False


def speak_or_delegate(text: str):
    """Speak locally or delegate TTS to peer with better speakers."""
    if not text.strip():
        return
    # If Follow-Me found a peer with better speakers, delegate
    if state.follow_me_enabled and state.best_speaker_peer:
        if delegate_tts_to_peer(text, state.best_speaker_peer):
            print(
                f"{Fore.MAGENTA}📡 TTS delegated to {state.best_speaker_peer}{Style.RESET_ALL}"
            )
            return
        log.warning("Delegation failed, falling back to local TTS")
    speak(text)


def speak(text: str):
    """Speak text via edge-tts (blocking). Can be interrupted or paused."""
    if not text.strip():
        return
    state.is_speaking = True
    state.tts_interrupt = False
    state.tts_paused = False
    state.tts_resume_event.set()  # ensure not stuck in paused state
    print(f"{Fore.CYAN}🔊 {HOST_NAME}:{Style.RESET_ALL} {text}")
    try:
        if HAS_EDGE_TTS:
            asyncio.run(_speak_edge_tts(text))
        else:
            # Fallback: pyttsx3
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", 170)
            voices = engine.getProperty("voices")
            for v in voices:
                if "german" in v.name.lower() or "de-de" in v.id.lower():
                    engine.setProperty("voice", v.id)
                    break
            engine.say(text)
            engine.runAndWait()
    except Exception as e:
        log.error(f"TTS error: {e}")
    finally:
        state.is_speaking = False


# ──────────────────────────────────────────────────────────────────────────────
# Audio capture callback — also monitors for interrupt during TTS
# ──────────────────────────────────────────────────────────────────────────────
def audio_callback(indata, frames, time_info, status):
    if status:
        log.warning(f"Audio status: {status}")
    # Always capture during TTS for interrupt detection
    if state.listening_enabled:
        if state.is_speaking:
            # During TTS: watch for loud interrupt (someone saying "stopp")
            amp = np.abs(indata).mean()
            if amp > MIC_THRESHOLD * 2:  # louder threshold during playback
                state.audio_queue.put(indata.copy())
        else:
            state.audio_queue.put(indata.copy())


# ──────────────────────────────────────────────────────────────────────────────
# Main voice loop
# ──────────────────────────────────────────────────────────────────────────────
def voice_loop():
    """Main processing loop: wake word → capture → transcribe → gateway → speak.
    Supports multi-turn conversation, TTS interrupt, and intercom."""
    log.info(f"Voice loop started. Wake words: {WAKE_WORDS}")
    log.info(f"Gateway: {GATEWAY_URL} | Agent: {AGENT_ID} | TTS: {TTS_VOICE}")
    log.info(f"Multi-turn timeout: {CONVERSATION_TIMEOUT}s")
    log.info("Listening for wake word... (Ctrl+C to stop)")

    recording = []
    silent_blocks = 0
    is_capturing_speech = False
    mode = "wake"  # 'wake' = listening for wake word, 'command' = capturing command after wake

    # Parameters
    blocks_per_second = SAMPLE_RATE / BLOCK_SIZE
    silence_blocks_limit = int(SILENCE_SECONDS * blocks_per_second)
    min_speech_blocks = int(0.3 * blocks_per_second)  # minimum 0.3s of speech

    # Wake word detection buffer: accumulate ~3 seconds of audio, transcribe, check
    wake_buffer = []
    wake_buffer_max_blocks = int(3.0 * blocks_per_second)
    wake_check_interval = int(1.5 * blocks_per_second)  # check every 1.5s
    wake_block_counter = 0

    # Interrupt detection buffer during TTS
    interrupt_buffer = []
    interrupt_check_blocks = int(1.0 * blocks_per_second)  # check every 1s
    interrupt_block_counter = 0

    while state.running:
        try:
            block = state.audio_queue.get(timeout=1.0)
        except queue.Empty:
            # Check multi-turn conversation timeout
            if (
                state.conversation_mode
                and time.time() - state.last_response_time > CONVERSATION_TIMEOUT
            ):
                state.conversation_mode = False
                print(f"{Fore.YELLOW}💬 Conversation ended (timeout){Style.RESET_ALL}")
                mode = "wake"
            continue

        amplitude = np.abs(block).mean()

        # ── Interrupt / Pause / Resume detection during TTS ──
        if state.is_speaking:
            interrupt_buffer.append(block)
            interrupt_block_counter += 1
            if (
                interrupt_block_counter >= interrupt_check_blocks
                and len(interrupt_buffer) >= min_speech_blocks
            ):
                interrupt_block_counter = 0
                int_audio = np.concatenate(interrupt_buffer, axis=0)
                interrupt_buffer.clear()
                int_text = transcribe(int_audio)
                if int_text:
                    if check_resume_word(int_text) and state.tts_paused:
                        # Resume paused TTS
                        print(f"{Fore.GREEN}▶ Resume: '{int_text}'{Style.RESET_ALL}")
                        state.tts_paused = False
                        state.tts_resume_event.set()
                    elif check_pause_word(int_text) and not state.tts_paused:
                        # Pause TTS playback
                        print(f"{Fore.YELLOW}⏸ Pause: '{int_text}'{Style.RESET_ALL}")
                        state.tts_paused = True
                        state.tts_resume_event.clear()
                        sd.stop()  # stop current chunk immediately
                    elif check_interrupt_word(int_text):
                        # Full interrupt — cancel TTS
                        print(f"{Fore.RED}✋ Interrupt: '{int_text}'{Style.RESET_ALL}")
                        state.tts_paused = False
                        state.tts_resume_event.set()  # unblock if paused
                        state.tts_interrupt = True
                        sd.stop()
            if len(interrupt_buffer) > int(2.0 * blocks_per_second):
                interrupt_buffer = interrupt_buffer[-int(1.0 * blocks_per_second) :]
            continue

        # Check multi-turn conversation timeout
        if state.conversation_mode and mode == "wake":
            if time.time() - state.last_response_time > CONVERSATION_TIMEOUT:
                state.conversation_mode = False
                print(f"{Fore.YELLOW}💬 Conversation ended (timeout){Style.RESET_ALL}")
            else:
                # Still in conversation mode — go directly to command capture
                mode = "command"
                recording.clear()
                silent_blocks = 0
                is_capturing_speech = False

        if mode == "wake":
            # ── OpenWakeWord fast path (if available) ──
            if state.oww_model is not None:
                if oww_check_wake(block):
                    # OWW detected wake word — confirm with Whisper
                    wake_amp = float(np.abs(block).max())
                    if state.follow_me_enabled:
                        i_should_respond = broadcast_wake_claim(wake_amp)
                        if not i_should_respond:
                            print(
                                f"{Fore.MAGENTA}📡 Follow-Me: another device is closer, staying silent{Style.RESET_ALL}"
                            )
                            continue
                    play_beep(freq=880, duration=0.12)
                    print(
                        f"\n{Fore.GREEN}✨ Wake word detected! (OWW){Style.RESET_ALL}"
                    )
                    mode = "command"
                    recording.clear()
                    silent_blocks = 0
                    is_capturing_speech = False
                    print(f"{Fore.YELLOW}👂 Listening for command...{Style.RESET_ALL}")
                continue

            # ── Whisper-based wake word detection (fallback) ──
            # Accumulate audio and periodically transcribe to detect wake word
            if amplitude > MIC_THRESHOLD * 0.5:  # lower threshold for wake detection
                wake_buffer.append(block)
                wake_block_counter += 1

                if len(wake_buffer) > wake_buffer_max_blocks:
                    wake_buffer = wake_buffer[-wake_buffer_max_blocks:]

                # Check for wake word periodically
                if (
                    wake_block_counter >= wake_check_interval
                    and len(wake_buffer) > min_speech_blocks
                ):
                    wake_block_counter = 0
                    audio_np = np.concatenate(wake_buffer, axis=0)
                    text = transcribe(audio_np)

                    if text and check_wake_word_in_text(text):
                        # Wake word detected — measure signal strength
                        wake_amp = float(np.abs(audio_np).max())

                        # Follow-Me: coordinate with peers
                        if state.follow_me_enabled:
                            i_should_respond = broadcast_wake_claim(wake_amp)
                            if not i_should_respond:
                                print(
                                    f"{Fore.MAGENTA}📡 Follow-Me: another device is closer, staying silent{Style.RESET_ALL}"
                                )
                                wake_buffer.clear()
                                wake_block_counter = 0
                                continue

                        # Confirmation beep
                        play_beep(freq=880, duration=0.12)
                        print(f"\n{Fore.GREEN}✨ Wake word detected!{Style.RESET_ALL}")
                        remainder = strip_wake_word(text)

                        if remainder and len(remainder) > 3:
                            # Check for intercom command
                            intercom = check_intercom_command(remainder)
                            if intercom:
                                peer_name, message = intercom
                                print(
                                    f"{Fore.MAGENTA}📢 Intercom → {peer_name}: {message}{Style.RESET_ALL}"
                                )
                                if send_intercom(peer_name, message):
                                    speak(f"Nachricht an {peer_name} gesendet.")
                                else:
                                    speak(f"Konnte {peer_name} nicht erreichen.")
                                wake_buffer.clear()
                                wake_block_counter = 0
                                continue

                            # Local automation commands (skip gateway round-trip)
                            if _handle_local_command(remainder):
                                wake_buffer.clear()
                                wake_block_counter = 0
                                continue

                            # User said wake word + command in one go
                            print(f"{Fore.BLUE}🎤 Du:{Style.RESET_ALL} {remainder}")
                            response = send_to_gateway(remainder)
                            speak_or_delegate(response)
                            # Enter multi-turn conversation mode
                            state.conversation_mode = True
                            state.last_response_time = time.time()
                            wake_buffer.clear()
                            wake_block_counter = 0
                            continue

                        # Switch to command capture mode
                        mode = "command"
                        recording.clear()
                        silent_blocks = 0
                        is_capturing_speech = False
                        wake_buffer.clear()
                        wake_block_counter = 0

                        print(
                            f"{Fore.YELLOW}👂 Listening for command...{Style.RESET_ALL}"
                        )
                        continue
            else:
                wake_block_counter += 1
                if wake_block_counter >= wake_check_interval:
                    wake_block_counter = 0
                    if wake_buffer:
                        # Discard old silent wake buffer
                        wake_buffer = wake_buffer[-(wake_buffer_max_blocks // 2) :]

        elif mode == "command":
            # Capture user's command after wake word (or in multi-turn mode)
            if amplitude > MIC_THRESHOLD:
                if not is_capturing_speech:
                    is_capturing_speech = True
                silent_blocks = 0
                recording.append(block)
            else:
                if is_capturing_speech:
                    silent_blocks += 1
                    recording.append(block)

                    if silent_blocks >= silence_blocks_limit:
                        # End of speech
                        is_capturing_speech = False

                        if len(recording) >= min_speech_blocks:
                            audio_np = np.concatenate(recording, axis=0)
                            print(f"{Fore.GREEN}⚙️  Processing...{Style.RESET_ALL}")
                            text = transcribe(audio_np)

                            if text and len(text.strip()) > 1:
                                # Check for interrupt word while in command mode
                                if check_interrupt_word(text):
                                    print(
                                        f"{Fore.YELLOW}👋 '{text}' — zurück zum Lauschen{Style.RESET_ALL}"
                                    )
                                    state.conversation_mode = False
                                    mode = "wake"
                                    recording.clear()
                                    silent_blocks = 0
                                    continue

                                # Check for intercom command
                                intercom = check_intercom_command(text)
                                if intercom:
                                    peer_name, message = intercom
                                    print(
                                        f"{Fore.MAGENTA}📢 Intercom → {peer_name}: {message}{Style.RESET_ALL}"
                                    )
                                    if send_intercom(peer_name, message):
                                        speak(f"Nachricht an {peer_name} gesendet.")
                                    else:
                                        speak(f"Konnte {peer_name} nicht erreichen.")
                                    state.conversation_mode = True
                                    state.last_response_time = time.time()
                                    mode = "wake"
                                    recording.clear()
                                    silent_blocks = 0
                                    continue

                                # Local automation commands (skip gateway round-trip)
                                if _handle_local_command(text):
                                    state.conversation_mode = True
                                    state.last_response_time = time.time()
                                    mode = "wake"
                                    recording.clear()
                                    silent_blocks = 0
                                    continue

                                print(f"{Fore.BLUE}🎤 Du:{Style.RESET_ALL} {text}")
                                response = send_to_gateway(text)
                                speak_or_delegate(response)
                                # Stay in multi-turn conversation mode
                                state.conversation_mode = True
                                state.last_response_time = time.time()
                            else:
                                print(f"{Fore.RED}(Nichts erkannt){Style.RESET_ALL}")
                        else:
                            print(f"{Fore.RED}(Zu kurz){Style.RESET_ALL}")

                        # Back to wake word mode
                        mode = "wake"
                        recording.clear()
                        silent_blocks = 0
                else:
                    # No speech detected after wake word for a while → timeout
                    silent_blocks += 1
                    if silent_blocks >= silence_blocks_limit * 2:
                        print(
                            f"{Fore.RED}(Timeout — kein Befehl erkannt){Style.RESET_ALL}"
                        )
                        mode = "wake"
                        recording.clear()
                        silent_blocks = 0


# ──────────────────────────────────────────────────────────────────────────────
# System Tray (optional, --tray flag)
# ──────────────────────────────────────────────────────────────────────────────
def _build_tray_menu():
    """Build the full tray menu with settings submenus."""

    def on_quit(icon, item):
        state.running = False
        icon.stop()

    # ── Volume ────────────────────────────────────────────────
    def on_vol_up(icon, item):
        set_volume(VOLUME + 10)

    def on_vol_down(icon, item):
        set_volume(VOLUME - 10)

    def on_mute(icon, item):
        set_volume(0 if VOLUME > 0 else 100)

    def vol_label(item):
        return f"Volume: {VOLUME}%"

    def mute_label(item):
        return "Unmute" if VOLUME == 0 else "Mute"

    # ── Input device submenu ──────────────────────────────────
    def make_input_handler(idx):
        def handler(icon, item):
            switch_input_device(idx)
            icon.menu = _build_tray_menu()
            icon.update_menu()

        return handler

    def is_input_checked(idx):
        current = int(INPUT_DEVICE) if INPUT_DEVICE else sd.default.device[0]
        return idx == current

    input_items = []
    for idx, name in get_input_devices():
        checked_fn = (lambda i: lambda item: is_input_checked(i))(idx)
        input_items.append(
            pystray.MenuItem(
                f"[{idx}] {name}", make_input_handler(idx), checked=checked_fn
            )
        )

    # ── Output device submenu ─────────────────────────────────
    def make_output_handler(idx):
        def handler(icon, item):
            switch_output_device(idx)
            icon.menu = _build_tray_menu()
            icon.update_menu()

        return handler

    def is_output_checked(idx):
        current = int(OUTPUT_DEVICE) if OUTPUT_DEVICE else sd.default.device[1]
        return idx == current

    output_items = []
    for idx, name in get_output_devices():
        checked_fn = (lambda i: lambda item: is_output_checked(i))(idx)
        output_items.append(
            pystray.MenuItem(
                f"[{idx}] {name}", make_output_handler(idx), checked=checked_fn
            )
        )

    # ── Mic threshold submenu ─────────────────────────────────
    def make_threshold_handler(val):
        def handler(icon, item):
            global MIC_THRESHOLD
            MIC_THRESHOLD = val
            log.info(f"Mic threshold set to {val}")
            icon.menu = _build_tray_menu()
            icon.update_menu()

        return handler

    threshold_levels = [
        ("Very sensitive (0.005)", 0.005),
        ("Sensitive (0.010)", 0.010),
        ("Normal (0.015)", 0.015),
        ("Low (0.025)", 0.025),
        ("Very low (0.040)", 0.040),
    ]
    threshold_items = []
    for label, val in threshold_levels:
        checked_fn = (lambda v: lambda item: abs(MIC_THRESHOLD - v) < 0.001)(val)
        threshold_items.append(
            pystray.MenuItem(label, make_threshold_handler(val), checked=checked_fn)
        )

    # ── Listening toggle ──────────────────────────────────────
    def on_toggle_listening(icon, item):
        state.listening_enabled = not state.listening_enabled
        status = "ON" if state.listening_enabled else "OFF"
        log.info(f"Listening {status}")
        icon.menu = _build_tray_menu()
        icon.update_menu()
        # Update tray icon color to reflect state
        _update_tray_icon_color(icon)

    def listening_label(item):
        return "Listening: ON" if state.listening_enabled else "Listening: OFF"

    def is_listening_checked(item):
        return state.listening_enabled

    # ── Mic test ──────────────────────────────────────────────
    def on_mic_test(icon, item):
        dev = int(INPUT_DEVICE) if INPUT_DEVICE else None
        threading.Thread(target=test_microphone, args=(dev, 5), daemon=True).start()

    # ── Detect output ─────────────────────────────────────────
    def on_detect_output(icon, item):
        def _run():
            in_dev = int(INPUT_DEVICE) if INPUT_DEVICE else None
            best = detect_output_device(input_device=in_dev, verbose=True)
            if best is not None:
                switch_output_device(best)
                log.info(f"Auto-selected output device [{best}]")
                icon.menu = _build_tray_menu()
                icon.update_menu()

        threading.Thread(target=_run, daemon=True).start()

    # ── Follow-Me toggle ──────────────────────────────────────
    def on_toggle_follow_me(icon, item):
        state.follow_me_enabled = not state.follow_me_enabled
        status = "ON" if state.follow_me_enabled else "OFF"
        log.info(f"Follow-Me {status}")
        icon.menu = _build_tray_menu()
        icon.update_menu()

    def follow_me_label(item):
        peers_info = f" ({len(PEERS)} peers)" if PEERS else " (no peers)"
        spk = f" | Speaker: {SPEAKER_SCORE:.1f}"
        return (
            f"Follow-Me: {'ON' if state.follow_me_enabled else 'OFF'}{peers_info}{spk}"
        )

    def is_follow_me_checked(item):
        return state.follow_me_enabled

    # ── Speaker score submenu ──────────────────────────────────
    def make_speaker_score_handler(val):
        def handler(icon, item):
            global SPEAKER_SCORE
            SPEAKER_SCORE = val
            log.info(f"Speaker score set to {val}")
            icon.menu = _build_tray_menu()
            icon.update_menu()

        return handler

    speaker_levels = [
        ("No speaker (0.0)", 0.0),
        ("Quiet (0.3)", 0.3),
        ("Normal (0.5)", 0.5),
        ("Good (0.7)", 0.7),
        ("Excellent (1.0)", 1.0),
    ]
    speaker_items = []
    for label, val in speaker_levels:
        checked_fn = (lambda v: lambda item: abs(SPEAKER_SCORE - v) < 0.05)(val)
        speaker_items.append(
            pystray.MenuItem(label, make_speaker_score_handler(val), checked=checked_fn)
        )

    # ── Status line ───────────────────────────────────────────
    def status_label(item):
        in_idx = int(INPUT_DEVICE) if INPUT_DEVICE else sd.default.device[0]
        out_idx = int(OUTPUT_DEVICE) if OUTPUT_DEVICE else sd.default.device[1]
        try:
            in_name = sd.query_devices(in_idx)["name"][:30]
        except Exception:
            in_name = "?"
        try:
            out_name = sd.query_devices(out_idx)["name"][:30]
        except Exception:
            out_name = "?"
        return f"In: {in_name} | Out: {out_name}"

    menu = pystray.Menu(
        pystray.MenuItem(f"Klatsch 🐾 · {HOST_NAME}", None, enabled=False),
        pystray.MenuItem(status_label, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            listening_label, on_toggle_listening, checked=is_listening_checked
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Input Device", pystray.Menu(*input_items)),
        pystray.MenuItem("Output Device", pystray.Menu(*output_items)),
        pystray.MenuItem("Mic Sensitivity", pystray.Menu(*threshold_items)),
        pystray.MenuItem("Test Microphone (5s)", on_mic_test),
        pystray.MenuItem("Detect Best Output (auto)", on_detect_output),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            follow_me_label, on_toggle_follow_me, checked=is_follow_me_checked
        ),
        pystray.MenuItem("Speaker Quality", pystray.Menu(*speaker_items)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Volume +10", on_vol_up),
        pystray.MenuItem("Volume -10", on_vol_down),
        pystray.MenuItem(mute_label, on_mute),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )
    return menu


def _make_tray_image(listening: bool = True):
    """Create tray icon image — green when listening, red when paused."""
    img = Image.new("RGB", (64, 64), color=(30, 30, 30))
    draw = ImageDraw.Draw(img)
    color = (0, 180, 80) if listening else (180, 50, 50)
    draw.ellipse([12, 12, 52, 52], fill=color)
    return img


def _update_tray_icon_color(icon):
    """Update tray icon color based on listening state."""
    icon.icon = _make_tray_image(state.listening_enabled)


def create_tray_icon():
    """Create a system tray icon with settings menus."""
    if not HAS_TRAY:
        return None

    img = _make_tray_image(state.listening_enabled)
    menu = _build_tray_menu()
    tooltip = f"Klatsch · {HOST_NAME}"
    icon = pystray.Icon("klatsch", img, tooltip, menu)
    return icon


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────
def main():
    global INPUT_DEVICE, OUTPUT_DEVICE, VOLUME

    parser = argparse.ArgumentParser(
        description=f"Klatsch · {HOST_NAME} — OpenClaw Local Agent"
    )
    parser.add_argument(
        "--tray", action="store_true", help="Run in background with system tray icon"
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List all audio input/output devices and exit",
    )
    parser.add_argument(
        "--test-mic",
        action="store_true",
        help="Record 5s from mic, show levels, play back, exit",
    )
    parser.add_argument(
        "--test-mic-duration",
        type=int,
        default=5,
        help="Duration for mic test in seconds (default: 5)",
    )
    parser.add_argument(
        "--input-device",
        type=int,
        default=None,
        help="Audio input device index (see --list-devices)",
    )
    parser.add_argument(
        "--output-device",
        type=int,
        default=None,
        help="Audio output device index (see --list-devices)",
    )
    parser.add_argument(
        "--volume",
        type=int,
        default=None,
        help="TTS playback volume 0-100 (default: 100)",
    )
    parser.add_argument(
        "--detect-output",
        action="store_true",
        help="Auto-detect best output device by playing tone and listening with mic",
    )
    args = parser.parse_args()

    # Apply CLI overrides
    if args.input_device is not None:
        INPUT_DEVICE = str(args.input_device)
    if args.output_device is not None:
        OUTPUT_DEVICE = str(args.output_device)
    if args.volume is not None:
        VOLUME = max(0, min(100, args.volume))

    # --list-devices: show and exit
    if args.list_devices:
        list_audio_devices()
        return

    # --test-mic: test and exit
    if args.test_mic:
        dev = int(INPUT_DEVICE) if INPUT_DEVICE else None
        test_microphone(device_index=dev, duration=args.test_mic_duration)
        return

    # --detect-output: auto-detect and exit
    if args.detect_output:
        in_dev = int(INPUT_DEVICE) if INPUT_DEVICE else None
        best = detect_output_device(input_device=in_dev, verbose=True)
        if best is not None:
            print(f"\n  Use: --output-device {best}")
            print(f"  Or:  OUTPUT_DEVICE={best}")
        return

    tray_mode = args.tray

    # Start peer coordination server for Follow-Me (also needed for intercom + notifications)
    start_peer_server()
    if PEERS:
        log.info(f"Follow-Me peers: {PEERS}")
        build_peer_name_map()
    else:
        log.info("Follow-Me: no peers configured (set PEERS env var to enable)")

    banner = f"Klatsch 🐾  ·  {HOST_NAME}"
    pad = len(banner) + 4
    top = '\u256d' + '\u2500' * pad + '\u256e'
    bot = '\u2570' + '\u2500' * pad + '\u256f'
    print(f"{Fore.GREEN}{top}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}\u2502  {banner}  \u2502{Style.RESET_ALL}")
    print(f"{Fore.GREEN}{bot}{Style.RESET_ALL}")

    # Load Whisper
    if not HAS_WHISPER:
        log.error("faster-whisper is required. Install: pip install faster-whisper")
        sys.exit(1)
    load_whisper()

    # Load OpenWakeWord (optional, for lightweight wake detection)
    if HAS_OWW:
        load_oww()
    else:
        log.info(
            "OpenWakeWord not installed — using Whisper-based wake detection (heavier on CPU)"
        )

    if not HAS_EDGE_TTS:
        log.warning(
            "edge-tts not installed. Falling back to pyttsx3. Install: pip install edge-tts"
        )

    # Start audio stream
    in_dev = int(INPUT_DEVICE) if INPUT_DEVICE else None
    in_name = (
        sd.query_devices(in_dev)["name"] if in_dev is not None else "system default"
    )
    out_dev = int(OUTPUT_DEVICE) if OUTPUT_DEVICE else None
    out_name = (
        sd.query_devices(out_dev)["name"] if out_dev is not None else "system default"
    )
    log.info(f"Input device:  [{in_dev or 'default'}] {in_name}")
    log.info(f"Output device: [{out_dev or 'default'}] {out_name}")
    log.info(f"Volume: {VOLUME}%")

    try:
        stream = sd.InputStream(
            device=in_dev,
            callback=audio_callback,
            channels=CHANNELS,
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
        )
        stream.start()
        state.audio_stream = stream
    except Exception as e:
        log.error(f"Cannot open audio input: {e}")
        sys.exit(1)

    # Handle graceful shutdown
    def shutdown_handler(sig, frame):
        print(f"\n{Fore.YELLOW}Shutting down...{Style.RESET_ALL}")
        state.running = False

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    # Start background awareness threads
    threading.Thread(target=presence_watcher, daemon=True).start()
    threading.Thread(target=disk_watcher, daemon=True).start()
    threading.Thread(target=reminder_watcher, daemon=True).start()
    threading.Thread(target=morning_briefing, daemon=True).start()

    if tray_mode and HAS_TRAY:
        icon = create_tray_icon()
        state.tray_icon = icon
        # Run voice loop in background thread, tray in main thread
        voice_thread = threading.Thread(target=voice_loop, daemon=True)
        voice_thread.start()
        icon.run()  # blocks until quit
        state.running = False
    else:
        voice_loop()

    if state.audio_stream:
        state.audio_stream.stop()
        state.audio_stream.close()
    print(f"{Fore.GREEN}Goodbye!{Style.RESET_ALL}")


if __name__ == "__main__":
    main()

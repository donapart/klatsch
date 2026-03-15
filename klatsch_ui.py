#!/usr/bin/env python3
"""
Klatsch 🐾 Settings — Einstellungen / Settings
=================================================
Graphical settings window for Klatsch (tkinter).
Supports German/English, drag & drop files, live config editing.

Launch:
  python klatsch_ui.py              # standalone
  python klatsch_ui.py --lang en    # English UI
  Triggered from tray → "Settings..."
"""

import json
import os
import pathlib
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ──────────────────────────────────────────────────────────────────────────────
# i18n — German/English
# ──────────────────────────────────────────────────────────────────────────────
STRINGS = {
    "de": {
        "title": "Klatsch 🐾 Einstellungen",
        "tab_general": "Allgemein",
        "tab_audio": "Audio",
        "tab_network": "Netzwerk",
        "tab_voice": "Stimme & Sprache",
        "tab_files": "Dateien",
        "tab_about": "Über",
        "gateway_url": "Gateway URL",
        "gateway_token": "Gateway Token",
        "agent_id": "Agent ID",
        "host_name": "Host-Name",
        "language": "Sprache",
        "input_device": "Eingabegerät",
        "output_device": "Ausgabegerät",
        "volume": "Lautstärke",
        "mic_threshold": "Mikrofon-Empfindlichkeit",
        "silence_seconds": "Stille-Erkennung (Sek.)",
        "ducking_enabled": "Audio-Ducking aktiv",
        "ducking_level": "Ducking-Pegel (0.0–1.0)",
        "peer_port": "Peer-Port",
        "peers_config": "Peers (LAN|Tailscale, kommagetrennt)",
        "discovery_enabled": "Auto-Discovery aktiv",
        "discovery_port": "Discovery-Port",
        "discovery_interval": "Discovery-Intervall (Sek.)",
        "speaker_score": "Lautsprecher-Qualität",
        "tts_voice": "TTS-Stimme",
        "wake_words": "Aktivierungswörter (kommagetrennt)",
        "whisper_model": "Whisper-Modell",
        "conversation_timeout": "Gesprächs-Timeout (Sek.)",
        "save": "Speichern",
        "cancel": "Abbrechen",
        "apply_restart": "Übernehmen & Neustart",
        "drop_hint": "Dateien hierher ziehen\noder klicken zum Auswählen",
        "drop_or_click": "Klicken oder Dateien ablegen",
        "file_sent": "Datei gesendet: {}",
        "file_error": "Fehler beim Senden: {}",
        "about_text": (
            "Klatsch 🐾\n\n"
            "OpenClaw Local Agent\n"
            "Sprachassistent, Peer-Koordination,\n"
            "Benachrichtigungen & mehr.\n\n"
            "github.com/donapart/klatsch"
        ),
        "saved_ok": "Einstellungen gespeichert.",
        "saved_restart": "Einstellungen gespeichert.\nKlatsch wird neu gestartet.",
        "no_speaker": "Kein Lautsprecher (0.0)",
        "quiet": "Leise (0.3)",
        "normal": "Normal (0.5)",
        "good": "Gut (0.7)",
        "excellent": "Exzellent (1.0)",
        "very_sensitive": "Sehr empfindlich (0.005)",
        "sensitive": "Empfindlich (0.010)",
        "normal_sens": "Normal (0.015)",
        "low": "Niedrig (0.025)",
        "very_low": "Sehr niedrig (0.040)",
        "select_files": "Dateien auswählen",
        "sending": "Sende...",
        "preview_voice": "▶ Vorschau",
        "preview_text": "Hallo, ich bin Klatsch, dein Sprachassistent.",
        "previewing": "Spielt ab...",
    },
    "en": {
        "title": "Klatsch 🐾 Settings",
        "tab_general": "General",
        "tab_audio": "Audio",
        "tab_network": "Network",
        "tab_voice": "Voice & Language",
        "tab_files": "Files",
        "tab_about": "About",
        "gateway_url": "Gateway URL",
        "gateway_token": "Gateway Token",
        "agent_id": "Agent ID",
        "host_name": "Host Name",
        "language": "Language",
        "input_device": "Input Device",
        "output_device": "Output Device",
        "volume": "Volume",
        "mic_threshold": "Mic Sensitivity",
        "silence_seconds": "Silence Detection (sec)",
        "ducking_enabled": "Audio Ducking Enabled",
        "ducking_level": "Ducking Level (0.0–1.0)",
        "peer_port": "Peer Port",
        "peers_config": "Peers (LAN|Tailscale, comma-separated)",
        "discovery_enabled": "Auto-Discovery Enabled",
        "discovery_port": "Discovery Port",
        "discovery_interval": "Discovery Interval (sec)",
        "speaker_score": "Speaker Quality",
        "tts_voice": "TTS Voice",
        "wake_words": "Wake Words (comma-separated)",
        "whisper_model": "Whisper Model",
        "conversation_timeout": "Conversation Timeout (sec)",
        "save": "Save",
        "cancel": "Cancel",
        "apply_restart": "Apply & Restart",
        "drop_hint": "Drop files here\nor click to select",
        "drop_or_click": "Click or drop files",
        "file_sent": "File sent: {}",
        "file_error": "Error sending: {}",
        "about_text": (
            "Klatsch 🐾\n\n"
            "OpenClaw Local Agent\n"
            "Voice assistant, peer coordination,\n"
            "notifications & more.\n\n"
            "github.com/donapart/klatsch"
        ),
        "saved_ok": "Settings saved.",
        "saved_restart": "Settings saved.\nKlatsch will restart.",
        "no_speaker": "No speaker (0.0)",
        "quiet": "Quiet (0.3)",
        "normal": "Normal (0.5)",
        "good": "Good (0.7)",
        "excellent": "Excellent (1.0)",
        "very_sensitive": "Very sensitive (0.005)",
        "sensitive": "Sensitive (0.010)",
        "normal_sens": "Normal (0.015)",
        "low": "Low (0.025)",
        "very_low": "Very low (0.040)",
        "select_files": "Select Files",
        "sending": "Sending...",
        "preview_voice": "▶ Preview",
        "preview_text": "Hello, I am Klatsch, your voice assistant.",
        "previewing": "Playing...",
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# Config file (persistent settings)
# ──────────────────────────────────────────────────────────────────────────────
CONFIG_DIR = pathlib.Path.home() / ".klatsch"
CONFIG_FILE = CONFIG_DIR / "settings.json"

DEFAULT_CONFIG = {
    "language": "de",
    "gateway_url": "http://192.168.0.67:18789",
    "gateway_token": "opensesame",
    "agent_id": "main",
    "host_name": "",
    "tts_voice": "de-DE-ConradNeural",
    "wake_words": "hey klatsch,klatsch",
    "whisper_model": "base",
    "mic_threshold": 0.015,
    "silence_seconds": 1.5,
    "volume": 100,
    "input_device": "",
    "output_device": "",
    "ducking_enabled": True,
    "ducking_level": 0.25,
    "peer_port": 7790,
    "peers_config": "",
    "discovery_enabled": True,
    "discovery_port": 7791,
    "discovery_interval": 15,
    "speaker_score": 1.0,
    "conversation_timeout": 8,
}


def load_config() -> dict:
    """Load config from JSON file, merge with defaults."""
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            cfg.update(saved)
        except (json.JSONDecodeError, OSError):
            pass
    # Also load from env vars (override file values)
    env_map = {
        "GATEWAY_URL": "gateway_url",
        "GATEWAY_TOKEN": "gateway_token",
        "AGENT_ID": "agent_id",
        "HOST_NAME": "host_name",
        "TTS_VOICE": "tts_voice",
        "WAKE_WORDS": "wake_words",
        "WHISPER_MODEL": "whisper_model",
        "MIC_THRESHOLD": "mic_threshold",
        "SILENCE_SECONDS": "silence_seconds",
        "VOLUME": "volume",
        "INPUT_DEVICE": "input_device",
        "OUTPUT_DEVICE": "output_device",
        "DUCKING_ENABLED": "ducking_enabled",
        "DUCKING_LEVEL": "ducking_level",
        "PEER_PORT": "peer_port",
        "PEERS_CONFIG": "peers_config",
        "DISCOVERY_ENABLED": "discovery_enabled",
        "DISCOVERY_PORT": "discovery_port",
        "DISCOVERY_INTERVAL": "discovery_interval",
        "SPEAKER_SCORE": "speaker_score",
        "CONVERSATION_TIMEOUT": "conversation_timeout",
    }
    for env_key, cfg_key in env_map.items():
        val = os.getenv(env_key)
        if val is not None:
            # Type coerce
            default = DEFAULT_CONFIG[cfg_key]
            if isinstance(default, bool):
                cfg[cfg_key] = val not in ("0", "false", "False", "no")
            elif isinstance(default, int):
                try:
                    cfg[cfg_key] = int(val)
                except ValueError:
                    pass
            elif isinstance(default, float):
                try:
                    cfg[cfg_key] = float(val)
                except ValueError:
                    pass
            else:
                cfg[cfg_key] = val
    return cfg


def save_config(cfg: dict):
    """Save config to JSON file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────────────────────
# Main Settings Window
# ──────────────────────────────────────────────────────────────────────────────
class KlatschSettings:
    def __init__(self, master: tk.Tk | None = None, callback=None):
        """
        callback: optional callable invoked with the saved config dict
                  (used when launched from tray to signal restart).
        """
        self.callback = callback
        self.cfg = load_config()
        self.lang = self.cfg.get("language", "de")
        self.s = STRINGS[self.lang]

        if master is None:
            self.root = tk.Tk()
            self.standalone = True
        else:
            self.root = tk.Toplevel(master)
            self.standalone = False

        self.root.title(self.s["title"])
        self.root.geometry("580x520")
        self.root.resizable(True, True)
        self.root.minsize(480, 420)

        # Window icon
        icon_path = pathlib.Path(__file__).parent / "klatsch.ico"
        if icon_path.exists():
            try:
                self.root.iconbitmap(str(icon_path))
            except tk.TclError:
                pass

        # Style
        style = ttk.Style()
        style.theme_use("clam" if sys.platform != "darwin" else "aqua")

        # Notebook (tabs)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(8, 0))

        self.vars: dict[str, tk.Variable] = {}

        self._build_general_tab()
        self._build_audio_tab()
        self._build_network_tab()
        self._build_voice_tab()
        self._build_files_tab()
        self._build_about_tab()

        # Bottom buttons
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill="x", padx=8, pady=8)
        ttk.Button(btn_frame, text=self.s["cancel"], command=self._on_cancel).pack(
            side="right", padx=(4, 0)
        )
        ttk.Button(btn_frame, text=self.s["save"], command=self._on_save).pack(
            side="right", padx=(4, 0)
        )
        ttk.Button(
            btn_frame, text=self.s["apply_restart"], command=self._on_apply_restart
        ).pack(side="right", padx=(4, 0))

        # Language toggle button (top-right)
        lang_btn = ttk.Button(
            btn_frame,
            text="🇩🇪 DE" if self.lang == "de" else "🇬🇧 EN",
            width=6,
            command=self._toggle_language,
        )
        lang_btn.pack(side="left")

    # ── Helpers ───────────────────────────────────────────────
    def _add_entry(self, parent, label: str, cfg_key: str, row: int, **kw):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=4, pady=3)
        var = tk.StringVar(value=str(self.cfg.get(cfg_key, "")))
        entry = ttk.Entry(parent, textvariable=var, **kw)
        entry.grid(row=row, column=1, sticky="ew", padx=4, pady=3)
        self.vars[cfg_key] = var
        return entry

    def _add_check(self, parent, label: str, cfg_key: str, row: int):
        var = tk.BooleanVar(value=bool(self.cfg.get(cfg_key, False)))
        cb = ttk.Checkbutton(parent, text=label, variable=var)
        cb.grid(row=row, column=0, columnspan=2, sticky="w", padx=4, pady=3)
        self.vars[cfg_key] = var

    def _add_combo(self, parent, label: str, cfg_key: str, values: list, row: int):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=4, pady=3)
        var = tk.StringVar(value=str(self.cfg.get(cfg_key, "")))
        combo = ttk.Combobox(parent, textvariable=var, values=values, state="readonly")
        combo.grid(row=row, column=1, sticky="ew", padx=4, pady=3)
        self.vars[cfg_key] = var

    def _add_scale(self, parent, label: str, cfg_key: str, from_: float, to: float, row: int):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=4, pady=3)
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=1, sticky="ew", padx=4, pady=3)
        var = tk.DoubleVar(value=float(self.cfg.get(cfg_key, from_)))
        val_label = ttk.Label(frame, text=f"{var.get():.2f}", width=6)
        scale = ttk.Scale(
            frame, from_=from_, to=to, variable=var, orient="horizontal",
            command=lambda v: val_label.config(text=f"{float(v):.2f}"),
        )
        scale.pack(side="left", fill="x", expand=True)
        val_label.pack(side="right", padx=(4, 0))
        self.vars[cfg_key] = var

    # ── Tabs ──────────────────────────────────────────────────
    def _build_general_tab(self):
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text=self.s["tab_general"])
        frame.columnconfigure(1, weight=1)

        self._add_entry(frame, self.s["gateway_url"], "gateway_url", 0)
        # Show token masked
        self._add_entry(frame, self.s["gateway_token"], "gateway_token", 1, show="•")
        self._add_entry(frame, self.s["agent_id"], "agent_id", 2)
        self._add_entry(frame, self.s["host_name"], "host_name", 3)

        # Language combo
        ttk.Label(frame, text=self.s["language"]).grid(row=4, column=0, sticky="w", padx=4, pady=3)
        lang_var = tk.StringVar(value=self.lang)
        lang_combo = ttk.Combobox(
            frame, textvariable=lang_var, values=["de", "en"], state="readonly", width=5
        )
        lang_combo.grid(row=4, column=1, sticky="w", padx=4, pady=3)
        self.vars["language"] = lang_var

    def _build_audio_tab(self):
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text=self.s["tab_audio"])
        frame.columnconfigure(1, weight=1)

        # Volume slider (0-100)
        ttk.Label(frame, text=self.s["volume"]).grid(row=0, column=0, sticky="w", padx=4, pady=3)
        vol_frame = ttk.Frame(frame)
        vol_frame.grid(row=0, column=1, sticky="ew", padx=4, pady=3)
        vol_var = tk.IntVar(value=int(self.cfg.get("volume", 100)))
        vol_label = ttk.Label(vol_frame, text=f"{vol_var.get()}%", width=5)
        vol_scale = ttk.Scale(
            vol_frame, from_=0, to=100, variable=vol_var, orient="horizontal",
            command=lambda v: vol_label.config(text=f"{int(float(v))}%"),
        )
        vol_scale.pack(side="left", fill="x", expand=True)
        vol_label.pack(side="right", padx=(4, 0))
        self.vars["volume"] = vol_var

        self._add_entry(frame, self.s["input_device"], "input_device", 1)
        self._add_entry(frame, self.s["output_device"], "output_device", 2)

        # Mic threshold combo
        threshold_opts = [
            self.s["very_sensitive"],
            self.s["sensitive"],
            self.s["normal_sens"],
            self.s["low"],
            self.s["very_low"],
        ]
        threshold_vals = [0.005, 0.010, 0.015, 0.025, 0.040]
        current_thresh = float(self.cfg.get("mic_threshold", 0.015))
        # Find closest match
        closest_label = threshold_opts[2]  # default: normal
        for i, v in enumerate(threshold_vals):
            if abs(current_thresh - v) < 0.002:
                closest_label = threshold_opts[i]
                break
        ttk.Label(frame, text=self.s["mic_threshold"]).grid(row=3, column=0, sticky="w", padx=4, pady=3)
        thresh_var = tk.StringVar(value=closest_label)
        thresh_combo = ttk.Combobox(
            frame, textvariable=thresh_var, values=threshold_opts, state="readonly"
        )
        thresh_combo.grid(row=3, column=1, sticky="ew", padx=4, pady=3)
        self.vars["mic_threshold"] = thresh_var
        self._threshold_map = dict(zip(threshold_opts, threshold_vals))

        self._add_entry(frame, self.s["silence_seconds"], "silence_seconds", 4)

        # Ducking
        self._add_check(frame, self.s["ducking_enabled"], "ducking_enabled", 5)
        self._add_scale(frame, self.s["ducking_level"], "ducking_level", 0.0, 1.0, 6)

    def _build_network_tab(self):
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text=self.s["tab_network"])
        frame.columnconfigure(1, weight=1)

        self._add_entry(frame, self.s["peer_port"], "peer_port", 0)
        self._add_entry(frame, self.s["peers_config"], "peers_config", 1)
        self._add_check(frame, self.s["discovery_enabled"], "discovery_enabled", 2)
        self._add_entry(frame, self.s["discovery_port"], "discovery_port", 3)
        self._add_entry(frame, self.s["discovery_interval"], "discovery_interval", 4)

        # Speaker score combo
        score_opts = [
            self.s["no_speaker"],
            self.s["quiet"],
            self.s["normal"],
            self.s["good"],
            self.s["excellent"],
        ]
        score_vals = [0.0, 0.3, 0.5, 0.7, 1.0]
        current_score = float(self.cfg.get("speaker_score", 1.0))
        closest_label = score_opts[4]
        for i, v in enumerate(score_vals):
            if abs(current_score - v) < 0.05:
                closest_label = score_opts[i]
                break
        self._add_combo(frame, self.s["speaker_score"], "_speaker_score_label", score_opts, 5)
        self.vars["_speaker_score_label"].set(closest_label)
        self._score_map = dict(zip(score_opts, score_vals))

    def _build_voice_tab(self):
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text=self.s["tab_voice"])
        frame.columnconfigure(1, weight=1)

        # TTS voice with presets
        voices = [
            "de-DE-ConradNeural",
            "de-DE-KatjaNeural",
            "de-AT-JonasNeural",
            "de-AT-IngridNeural",
            "de-CH-JanNeural",
            "de-CH-LeniNeural",
            "en-US-GuyNeural",
            "en-US-JennyNeural",
            "en-GB-RyanNeural",
            "en-GB-SoniaNeural",
        ]
        current_voice = str(self.cfg.get("tts_voice", "de-DE-ConradNeural"))
        if current_voice not in voices:
            voices.insert(0, current_voice)
        ttk.Label(frame, text=self.s["tts_voice"]).grid(row=0, column=0, sticky="w", padx=4, pady=3)
        voice_var = tk.StringVar(value=current_voice)
        voice_combo = ttk.Combobox(frame, textvariable=voice_var, values=voices)
        voice_combo.grid(row=0, column=1, sticky="ew", padx=4, pady=3)
        self.vars["tts_voice"] = voice_var

        # Preview button
        preview_btn = ttk.Button(
            frame, text=self.s["preview_voice"], width=12,
            command=lambda: self._preview_tts(voice_var, preview_btn),
        )
        preview_btn.grid(row=0, column=2, padx=(4, 0), pady=3)

        self._add_entry(frame, self.s["wake_words"], "wake_words", 1)

        whisper_models = ["tiny", "base", "small", "medium", "large-v3"]
        self._add_combo(frame, self.s["whisper_model"], "whisper_model", whisper_models, 2)
        self._add_entry(frame, self.s["conversation_timeout"], "conversation_timeout", 3)

    def _build_files_tab(self):
        """Drag & drop area for sending files to Klatsch."""
        frame = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(frame, text=self.s["tab_files"])

        # Drop zone (canvas)
        self.drop_frame = ttk.LabelFrame(frame, text=self.s["drop_or_click"], padding=20)
        self.drop_frame.pack(fill="both", expand=True, padx=10, pady=10)

        drop_label = ttk.Label(
            self.drop_frame,
            text=self.s["drop_hint"],
            anchor="center",
            justify="center",
            font=("Segoe UI", 12),
        )
        drop_label.pack(fill="both", expand=True)

        # Click to select
        drop_label.bind("<Button-1>", lambda e: self._select_files())

        # Status label
        self.file_status = ttk.Label(frame, text="", foreground="gray")
        self.file_status.pack(pady=(0, 10))

        # Try to enable native drag & drop (tkdnd)
        self._setup_dnd()

    def _setup_dnd(self):
        """Try to set up tkdnd for native drag & drop. Falls back gracefully."""
        try:
            # tkdnd2 is available on some systems
            self.root.tk.eval("package require tkdnd")
            self.root.tk.eval(
                f"tkdnd::drop_target register {self.drop_frame.winfo_pathname(self.drop_frame.winfo_id())} *"
            )
            self.drop_frame.bind("<<Drop>>", self._on_drop)
            self._has_dnd = True
        except tk.TclError:
            self._has_dnd = False

    def _on_drop(self, event):
        """Handle dropped files (tkdnd)."""
        files = self.root.tk.splitlist(event.data)
        for f in files:
            self._send_file(f)

    def _select_files(self):
        """Open file dialog to select files."""
        files = filedialog.askopenfilenames(title=self.s["select_files"])
        for f in files:
            self._send_file(f)

    def _send_file(self, filepath: str):
        """Send a file to Klatsch gateway as a message."""
        filepath = filepath.strip("{}")  # tkdnd sometimes wraps in braces
        name = pathlib.Path(filepath).name
        self.file_status.config(text=f"{self.s['sending']} {name}")
        self.root.update_idletasks()

        def _do_send():
            try:
                import urllib.request
                import urllib.error

                gateway = self.cfg.get("gateway_url", "http://192.168.0.67:18789")
                token = self.cfg.get("gateway_token", "opensesame")
                agent = self.cfg.get("agent_id", "main")

                # Read file and send as message with filename
                data = json.dumps({
                    "messages": [{"role": "user", "content": f"[File: {name}] Ich schicke dir die Datei {name}."}],
                    "model": agent,
                }).encode("utf-8")
                req = urllib.request.Request(
                    f"{gateway}/v1/chat/completions",
                    data=data,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {token}",
                    },
                )
                urllib.request.urlopen(req, timeout=30)
                self.root.after(0, lambda: self.file_status.config(
                    text=self.s["file_sent"].format(name), foreground="green"
                ))
            except Exception as e:
                self.root.after(0, lambda: self.file_status.config(
                    text=self.s["file_error"].format(str(e)[:60]), foreground="red"
                ))

        threading.Thread(target=_do_send, daemon=True).start()

    def _build_about_tab(self):
        frame = ttk.Frame(self.notebook, padding=20)
        self.notebook.add(frame, text=self.s["tab_about"])

        # Try to show icon
        icon_path = pathlib.Path(__file__).parent / "klatsch.png"
        if icon_path.exists():
            try:
                from PIL import Image, ImageTk
                img = Image.open(icon_path).resize((96, 96), Image.LANCZOS)
                self._about_img = ImageTk.PhotoImage(img)
                ttk.Label(frame, image=self._about_img).pack(pady=(0, 10))
            except ImportError:
                pass

        ttk.Label(
            frame,
            text=self.s["about_text"],
            justify="center",
            font=("Segoe UI", 11),
        ).pack()

    # ── Actions ───────────────────────────────────────────────
    def _preview_tts(self, voice_var, btn):
        """Play a short TTS preview of the selected voice via edge-tts."""
        voice = voice_var.get()
        text = self.s["preview_text"]
        original_text = btn.cget("text")
        btn.config(text=self.s["previewing"], state="disabled")
        self.root.update_idletasks()

        def _do_preview():
            try:
                import asyncio
                import tempfile
                import shutil, subprocess as sp

                async def _gen():
                    import edge_tts
                    comm = edge_tts.Communicate(text, voice)
                    chunks = []
                    async for chunk in comm.stream():
                        if chunk["type"] == "audio":
                            chunks.append(chunk["data"])
                    return b"".join(chunks)

                audio = asyncio.run(_gen())
                if not audio:
                    return

                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                    f.write(audio)
                    tmp = f.name

                # Play via ffplay (silent) or fallback to system player
                ffplay = shutil.which("ffplay")
                if ffplay:
                    sp.run([ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", tmp],
                           timeout=15, creationflags=getattr(sp, "CREATE_NO_WINDOW", 0))
                else:
                    # Fallback: os.startfile on Windows
                    if sys.platform == "win32":
                        os.startfile(tmp)
                        import time; time.sleep(5)
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("TTS Preview", str(e)))
            finally:
                self.root.after(0, lambda: btn.config(text=original_text, state="normal"))

        threading.Thread(target=_do_preview, daemon=True).start()

    def _collect_config(self) -> dict:
        """Collect current widget values into a config dict."""
        cfg = {}
        for key, var in self.vars.items():
            if key.startswith("_"):
                continue
            val = var.get()
            default = DEFAULT_CONFIG.get(key)
            if isinstance(default, bool):
                cfg[key] = bool(val)
            elif isinstance(default, int):
                try:
                    cfg[key] = int(float(val))
                except (ValueError, TypeError):
                    cfg[key] = default
            elif isinstance(default, float):
                try:
                    cfg[key] = float(val)
                except (ValueError, TypeError):
                    cfg[key] = default
            else:
                cfg[key] = str(val)

        # Resolve mic_threshold from label
        if "mic_threshold" in self.vars:
            label = self.vars["mic_threshold"].get()
            cfg["mic_threshold"] = self._threshold_map.get(label, 0.015)

        # Resolve speaker_score from label
        if "_speaker_score_label" in self.vars:
            label = self.vars["_speaker_score_label"].get()
            cfg["speaker_score"] = self._score_map.get(label, 1.0)

        return cfg

    def _on_save(self):
        cfg = self._collect_config()
        save_config(cfg)
        messagebox.showinfo("Klatsch", self.s["saved_ok"])

    def _on_apply_restart(self):
        cfg = self._collect_config()
        save_config(cfg)
        if self.callback:
            self.callback(cfg)
        messagebox.showinfo("Klatsch", self.s["saved_restart"])
        self.root.destroy()

    def _on_cancel(self):
        self.root.destroy()

    def _toggle_language(self):
        """Switch language and rebuild UI."""
        new_lang = "en" if self.lang == "de" else "de"
        self.cfg["language"] = new_lang
        save_config(self.cfg)
        # Re-launch the window
        self.root.destroy()
        open_settings(lang=new_lang)

    def run(self):
        self.root.mainloop()


def open_settings(lang: str | None = None, callback=None):
    """Open the settings window. Can be called from tray or standalone."""
    cfg = load_config()
    if lang:
        cfg["language"] = lang
    root = tk.Tk()
    root.withdraw()
    app = KlatschSettings.__new__(KlatschSettings)
    app.callback = callback
    app.cfg = cfg
    app.lang = cfg.get("language", "de")
    app.s = STRINGS[app.lang]
    app.standalone = True

    root.deiconify()
    app.root = root
    app.root.title(app.s["title"])
    app.root.geometry("580x520")
    app.root.resizable(True, True)
    app.root.minsize(480, 420)

    icon_path = pathlib.Path(__file__).parent / "klatsch.ico"
    if icon_path.exists():
        try:
            app.root.iconbitmap(str(icon_path))
        except tk.TclError:
            pass

    style = ttk.Style()
    style.theme_use("clam" if sys.platform != "darwin" else "aqua")

    app.notebook = ttk.Notebook(app.root)
    app.notebook.pack(fill="both", expand=True, padx=8, pady=(8, 0))
    app.vars = {}

    app._build_general_tab()
    app._build_audio_tab()
    app._build_network_tab()
    app._build_voice_tab()
    app._build_files_tab()
    app._build_about_tab()

    btn_frame = ttk.Frame(app.root)
    btn_frame.pack(fill="x", padx=8, pady=8)
    ttk.Button(btn_frame, text=app.s["cancel"], command=app._on_cancel).pack(
        side="right", padx=(4, 0)
    )
    ttk.Button(btn_frame, text=app.s["save"], command=app._on_save).pack(
        side="right", padx=(4, 0)
    )
    ttk.Button(
        btn_frame, text=app.s["apply_restart"], command=app._on_apply_restart
    ).pack(side="right", padx=(4, 0))
    lang_btn = ttk.Button(
        btn_frame,
        text="🇩🇪 DE" if app.lang == "de" else "🇬🇧 EN",
        width=6,
        command=app._toggle_language,
    )
    lang_btn.pack(side="left")

    app.root.mainloop()


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Klatsch Settings UI")
    parser.add_argument("--lang", choices=["de", "en"], default=None, help="UI language")
    args = parser.parse_args()

    if args.lang:
        open_settings(lang=args.lang)
    else:
        app = KlatschSettings()
        app.run()

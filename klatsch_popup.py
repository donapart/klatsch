#!/usr/bin/env python3
"""
Klatsch 🐾 Status-Popup
========================
Compact status overlay shown on tray icon left-click.
Fetches live data from the local Klatsch HTTP API.
"""

import json
import os
import pathlib
import sys
import threading
import tkinter as tk
from tkinter import ttk
import urllib.request
import urllib.error

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
_CONFIG_FILE = pathlib.Path.home() / ".klatsch" / "settings.json"
_POLL_MS = 2000  # refresh interval


def _load_cfg():
    cfg = {"peer_port": 7790, "language": "de"}
    if _CONFIG_FILE.exists():
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


# ──────────────────────────────────────────────────────────────────────────────
# i18n
# ──────────────────────────────────────────────────────────────────────────────
_I18N = {
    "de": {
        "title": "Klatsch 🐾",
        "listening": "Mithören",
        "paused": "Pausiert",
        "speaking": "Spricht…",
        "idle": "Bereit",
        "volume": "Lautstärke",
        "peers": "Peers",
        "no_peers": "Keine Peers",
        "presence": "Anwesenheit",
        "present": "Anwesend",
        "away": "Abwesend",
        "follow_me": "Follow-Me",
        "on": "An",
        "off": "Aus",
        "discovery": "Discovery",
        "reminders": "Erinnerungen",
        "conversation": "Konversation",
        "active": "Aktiv",
        "version": "Version",
        "host": "Host",
        "open_dashboard": "Dashboard öffnen",
        "open_settings": "Einstellungen",
        "toggle_listen": "Mithören An/Aus",
        "offline": "Klatsch ist nicht erreichbar",
        "quit": "Beenden",
        "history": "Verlauf",
        "you": "Du",
        "assistant": "Klatsch",
    },
    "en": {
        "title": "Klatsch 🐾",
        "listening": "Listening",
        "paused": "Paused",
        "speaking": "Speaking…",
        "idle": "Ready",
        "volume": "Volume",
        "peers": "Peers",
        "no_peers": "No peers",
        "presence": "Presence",
        "present": "Present",
        "away": "Away",
        "follow_me": "Follow-Me",
        "on": "On",
        "off": "Off",
        "discovery": "Discovery",
        "reminders": "Reminders",
        "conversation": "Conversation",
        "active": "Active",
        "version": "Version",
        "host": "Host",
        "open_dashboard": "Open Dashboard",
        "open_settings": "Settings",
        "toggle_listen": "Toggle Listening",
        "offline": "Klatsch is not reachable",
        "quit": "Quit",
        "history": "History",
        "you": "You",
        "assistant": "Klatsch",
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# Colors & Style (theme-aware)
# ──────────────────────────────────────────────────────────────────────────────
_THEMES = {
    "dark": {
        "bg":      "#1e1e2e",
        "bg_card": "#2a2a3e",
        "fg":      "#e0e0e0",
        "fg_dim":  "#888899",
    },
    "light": {
        "bg":      "#f0f0f5",
        "bg_card": "#e0e0ea",
        "fg":      "#1e1e2e",
        "fg_dim":  "#666677",
    },
}

# Module-level color vars; overwritten in show_popup() from config
_BG      = _THEMES["dark"]["bg"]
_BG_CARD = _THEMES["dark"]["bg_card"]
_FG      = _THEMES["dark"]["fg"]
_FG_DIM  = _THEMES["dark"]["fg_dim"]
_GREEN   = "#50c878"
_RED     = "#e05050"
_YELLOW  = "#f0c040"
_BLUE    = "#5090e0"
_ACCENT  = "#7c6ff0"


# ──────────────────────────────────────────────────────────────────────────────
# Status Popup Window
# ──────────────────────────────────────────────────────────────────────────────
class StatusPopup:
    def __init__(self, port: int = 7790, lang: str = "de", always_on_top: bool = True,
                 theme: str = "dark"):
        self.port = port
        self.s = _I18N.get(lang, _I18N["de"])
        self.base_url = f"http://127.0.0.1:{port}"
        self._alive = True

        # Apply theme colors to module-level vars so all widgets use them
        global _BG, _BG_CARD, _FG, _FG_DIM
        t = _THEMES.get(theme, _THEMES["dark"])
        _BG, _BG_CARD, _FG, _FG_DIM = t["bg"], t["bg_card"], t["fg"], t["fg_dim"]

        self.root = tk.Tk()
        self.root.title("Klatsch")
        self.root.overrideredirect(True)  # borderless
        self.root.attributes("-topmost", always_on_top)
        self.root.configure(bg=_BG)

        # Window icon
        icon_path = pathlib.Path(__file__).parent / "klatsch.ico"
        if icon_path.exists():
            try:
                self.root.iconbitmap(str(icon_path))
            except tk.TclError:
                pass

        # Position: bottom-right above taskbar, then slide in from right
        self._width = 320
        self._height = 540  # taller to fit history section
        self._position_window()

        # Allow dragging — bound after UI build (attached to header)
        self._drag_x = 0
        self._drag_y = 0

        # Build UI
        self._build_ui()

        # Close on Escape or focus loss
        self.root.bind("<Escape>", lambda e: self._close())
        self.root.bind("<FocusOut>", self._on_focus_out)

        # Start polling
        self._poll()

    def _position_window(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self._target_x = sw - self._width - 12
        self._target_y = sh - self._height - 60  # above taskbar
        # Start off-screen to the right, then slide in
        self.root.geometry(f"{self._width}x{self._height}+{sw}+{self._target_y}")
        self.root.after(30, self._slide_in)

    def _slide_in(self):
        """Animate the popup sliding in from the right edge."""
        x = self.root.winfo_x()
        if x > self._target_x:
            x = max(self._target_x, x - 40)
            self.root.geometry(f"+{x}+{self._target_y}")
            self.root.after(16, self._slide_in)

    def _drag_start(self, event):
        self._drag_x = event.x_root - self.root.winfo_x()
        self._drag_y = event.y_root - self.root.winfo_y()

    def _drag_motion(self, event):
        x = event.x_root - self._drag_x
        y = event.y_root - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def _on_focus_out(self, event):
        # Small delay to avoid closing on internal focus changes
        self.root.after(150, self._check_focus)

    def _check_focus(self):
        try:
            if not self.root.focus_get():
                self._close()
        except tk.TclError:
            pass

    def _close(self):
        self._alive = False
        self.root.destroy()

    # ── UI ────────────────────────────────────────────────────
    def _build_ui(self):
        main = tk.Frame(self.root, bg=_BG, padx=12, pady=10)
        main.pack(fill="both", expand=True)

        # Header
        hdr = tk.Frame(main, bg=_BG)
        hdr.pack(fill="x", pady=(0, 8))
        self._title_lbl = tk.Label(
            hdr, text=self.s["title"], font=("Segoe UI", 14, "bold"),
            bg=_BG, fg=_FG, anchor="w",
        )
        self._title_lbl.pack(side="left")
        close_btn = tk.Label(
            hdr, text="  \u2715  ", font=("Segoe UI", 11), bg=_BG, fg=_FG_DIM,
            cursor="hand2",
        )
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda e: self._close())

        # Drag the whole popup by grabbing the header
        hdr.bind("<ButtonPress-1>", self._drag_start)
        hdr.bind("<B1-Motion>", self._drag_motion)
        self._title_lbl.bind("<ButtonPress-1>", self._drag_start)
        self._title_lbl.bind("<B1-Motion>", self._drag_motion)

        # Status indicator (big)
        self._status_frame = tk.Frame(main, bg=_BG_CARD, padx=12, pady=10)
        self._status_frame.pack(fill="x", pady=(0, 6))
        self._status_dot = tk.Label(
            self._status_frame, text="\u25cf", font=("Segoe UI", 18),
            bg=_BG_CARD, fg=_GREEN,
        )
        self._status_dot.pack(side="left", padx=(0, 8))
        status_text_frame = tk.Frame(self._status_frame, bg=_BG_CARD)
        status_text_frame.pack(side="left", fill="x", expand=True)
        self._status_lbl = tk.Label(
            status_text_frame, text=self.s["listening"], font=("Segoe UI", 13, "bold"),
            bg=_BG_CARD, fg=_FG, anchor="w",
        )
        self._status_lbl.pack(anchor="w")
        self._status_sub = tk.Label(
            status_text_frame, text="", font=("Segoe UI", 9),
            bg=_BG_CARD, fg=_FG_DIM, anchor="w",
        )
        self._status_sub.pack(anchor="w")

        # Info grid (cards)
        info_frame = tk.Frame(main, bg=_BG)
        info_frame.pack(fill="x", pady=(0, 6))
        info_frame.columnconfigure(0, weight=1)
        info_frame.columnconfigure(1, weight=1)

        # Volume card
        self._vol_card, self._vol_lbl = self._make_card(
            info_frame, self.s["volume"], "100%", 0, 0
        )
        # Peers card
        self._peers_card, self._peers_lbl = self._make_card(
            info_frame, self.s["peers"], self.s["no_peers"], 0, 1
        )
        # Follow-Me card
        self._fm_card, self._fm_lbl = self._make_card(
            info_frame, self.s["follow_me"], self.s["off"], 1, 0
        )
        # Presence card
        self._pres_card, self._pres_lbl = self._make_card(
            info_frame, self.s["presence"], self.s["away"], 1, 1
        )
        # Discovery card
        self._disc_card, self._disc_lbl = self._make_card(
            info_frame, self.s["discovery"], self.s["off"], 2, 0
        )
        # Reminders card
        self._rem_card, self._rem_lbl = self._make_card(
            info_frame, self.s["reminders"], "0", 2, 1
        )

        # Host & Version
        meta_frame = tk.Frame(main, bg=_BG)
        meta_frame.pack(fill="x", pady=(2, 6))
        self._host_lbl = tk.Label(
            meta_frame, text="", font=("Segoe UI", 9), bg=_BG, fg=_FG_DIM, anchor="w",
        )
        self._host_lbl.pack(side="left")
        self._ver_lbl = tk.Label(
            meta_frame, text="", font=("Segoe UI", 9), bg=_BG, fg=_FG_DIM, anchor="e",
        )
        self._ver_lbl.pack(side="right")

        # Action buttons
        btn_frame = tk.Frame(main, bg=_BG)
        btn_frame.pack(fill="x", pady=(4, 0))
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)
        btn_frame.columnconfigure(2, weight=1)

        self._btn_listen = self._make_btn(
            btn_frame, self.s["toggle_listen"], self._on_toggle_listen, 0
        )
        self._make_btn(
            btn_frame, self.s["open_dashboard"], self._on_dashboard, 1
        )
        self._make_btn(
            btn_frame, self.s["open_settings"], self._on_settings, 2
        )

        # ── Conversation history ──────────────────────────────────────────
        sep = tk.Frame(main, bg=_FG_DIM, height=1)
        sep.pack(fill="x", pady=(8, 4))

        hist_hdr = tk.Frame(main, bg=_BG)
        hist_hdr.pack(fill="x")
        tk.Label(
            hist_hdr, text=self.s["history"], font=("Segoe UI", 9, "bold"),
            bg=_BG, fg=_FG_DIM, anchor="w",
        ).pack(side="left")

        self._hist_frame = tk.Frame(main, bg=_BG)
        self._hist_frame.pack(fill="x", pady=(4, 0))

        # Pre-build 3 entry slots (Q + A pairs)
        self._hist_entries: list[tuple[tk.Label, tk.Label]] = []
        for _ in range(3):
            q_lbl = tk.Label(
                self._hist_frame, text="", font=("Segoe UI", 8, "bold"),
                bg=_BG, fg=_ACCENT, anchor="w", wraplength=280, justify="left",
            )
            q_lbl.pack(fill="x")
            a_lbl = tk.Label(
                self._hist_frame, text="", font=("Segoe UI", 8),
                bg=_BG, fg=_FG, anchor="w", wraplength=280, justify="left",
            )
            a_lbl.pack(fill="x", pady=(0, 4))
            self._hist_entries.append((q_lbl, a_lbl))

    def _make_card(self, parent, title: str, value: str, row: int, col: int):
        card = tk.Frame(parent, bg=_BG_CARD, padx=10, pady=7)
        card.grid(row=row, column=col, sticky="nsew", padx=3, pady=3)
        parent.rowconfigure(row, weight=1)
        tk.Label(
            card, text=title, font=("Segoe UI", 8), bg=_BG_CARD, fg=_FG_DIM, anchor="w",
        ).pack(anchor="w")
        lbl = tk.Label(
            card, text=value, font=("Segoe UI", 12, "bold"), bg=_BG_CARD, fg=_FG, anchor="w",
        )
        lbl.pack(anchor="w")
        return card, lbl

    def _make_btn(self, parent, text: str, command, col: int):
        btn = tk.Label(
            parent, text=text, font=("Segoe UI", 9), bg=_ACCENT, fg="#ffffff",
            padx=8, pady=6, cursor="hand2", anchor="center",
        )
        btn.grid(row=0, column=col, sticky="ew", padx=2)
        btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e: btn.configure(bg="#8b7ff5"))
        btn.bind("<Leave>", lambda e: btn.configure(bg=_ACCENT))
        return btn

    # ── Actions ───────────────────────────────────────────────
    def _on_toggle_listen(self):
        """Toggle listening via POST /toggle-listen (if available) or just refresh."""
        def _do():
            try:
                req = urllib.request.Request(
                    f"{self.base_url}/toggle-listen", method="POST",
                    data=b"", headers={"Content-Type": "application/json"},
                )
                urllib.request.urlopen(req, timeout=2)
            except Exception:
                pass
        threading.Thread(target=_do, daemon=True).start()
        self.root.after(300, self._poll)

    def _on_dashboard(self):
        import webbrowser
        webbrowser.open(f"http://localhost:{self.port}/dashboard")

    def _on_settings(self):
        ui_path = pathlib.Path(__file__).parent / "klatsch_ui.py"
        if ui_path.exists():
            import subprocess
            subprocess.Popen(
                [sys.executable, str(ui_path)],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

    # ── Polling ───────────────────────────────────────────────
    def _poll(self):
        if not self._alive:
            return
        threading.Thread(target=self._fetch_status, daemon=True).start()
        self.root.after(_POLL_MS, self._poll)

    def _fetch_status(self):
        try:
            resp = urllib.request.urlopen(f"{self.base_url}/status", timeout=2)
            data = json.loads(resp.read())
            self.root.after(0, lambda: self._update_ui(data))
        except Exception:
            self.root.after(0, self._show_offline)

    def _show_offline(self):
        self._status_dot.configure(fg=_RED)
        self._status_lbl.configure(text=self.s["offline"])
        self._status_sub.configure(text="")

    def _update_ui(self, d: dict):
        # Main status
        listening = d.get("listening", False)
        speaking = d.get("speaking", False)
        conversation = d.get("conversation_mode", False)

        if speaking:
            self._status_dot.configure(fg=_YELLOW)
            self._status_lbl.configure(text=self.s["speaking"])
        elif listening:
            self._status_dot.configure(fg=_GREEN)
            self._status_lbl.configure(text=self.s["listening"])
        else:
            self._status_dot.configure(fg=_RED)
            self._status_lbl.configure(text=self.s["paused"])

        # Sub-status
        sub_parts = []
        if conversation:
            sub_parts.append(f"{self.s['conversation']}: {self.s['active']}")
        host = d.get("host", "")
        if host:
            sub_parts.append(host)
        self._status_sub.configure(text=" · ".join(sub_parts) if sub_parts else "")

        # Volume
        vol = d.get("volume", 0)
        self._vol_lbl.configure(text=f"{vol}%")

        # Peers
        peers = d.get("peers", [])
        if peers:
            names = [p.get("name", p.get("url", "?")) for p in peers]
            self._peers_lbl.configure(
                text=f"{len(peers)}  " + ", ".join(n[:12] for n in names[:3]),
                fg=_GREEN,
            )
        else:
            self._peers_lbl.configure(text=self.s["no_peers"], fg=_FG_DIM)

        # Follow-Me
        fm = d.get("follow_me", False)
        self._fm_lbl.configure(
            text=self.s["on"] if fm else self.s["off"],
            fg=_GREEN if fm else _FG_DIM,
        )

        # Presence
        pres = d.get("presence", False)
        self._pres_lbl.configure(
            text=self.s["present"] if pres else self.s["away"],
            fg=_GREEN if pres else _FG_DIM,
        )

        # Discovery
        disc = d.get("discovery_enabled", False)
        self._disc_lbl.configure(
            text=self.s["on"] if disc else self.s["off"],
            fg=_BLUE if disc else _FG_DIM,
        )

        # Reminders
        rem = d.get("reminders", 0)
        self._rem_lbl.configure(text=str(rem), fg=_YELLOW if rem > 0 else _FG_DIM)

        # Meta
        self._host_lbl.configure(text=d.get("host", ""))
        ver = d.get("version", "")
        self._ver_lbl.configure(text=f"v{ver}" if ver else "")

        # Conversation history
        history = d.get("history", [])
        for i, (q_lbl, a_lbl) in enumerate(self._hist_entries):
            if i < len(history):
                entry = history[i]
                q_lbl.configure(text=f"{self.s['you']}: {entry.get('q', '')[:80]}")
                a_lbl.configure(text=f"{self.s['assistant']}: {entry.get('a', '')[:160]}")
            else:
                q_lbl.configure(text="")
                a_lbl.configure(text="")


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────
def show_popup(port: int | None = None, lang: str | None = None):
    cfg = _load_cfg()
    p = port or int(cfg.get("peer_port", 7790))
    la = lang or cfg.get("language", "de")
    aot = cfg.get("always_on_top", True)
    if isinstance(aot, str):
        aot = aot not in ("0", "false", "no", "")
    theme = cfg.get("theme", "dark")
    popup = StatusPopup(port=p, lang=la, always_on_top=bool(aot), theme=str(theme))
    popup.root.mainloop()


if __name__ == "__main__":
    show_popup()

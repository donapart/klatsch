#!/usr/bin/env python3
"""
Klatsch 🐾 Drop Widget
========================
Kleines schwebendes Fenster (immer oben) mit Klatsch-Logo.
- Zeigt Klatsch-Status durch Randfarbe (grün / gelb / rot)
- Linksklick → Status-Popup öffnen
- Rechtsklick → Kontextmenü
- Datei-Drop auf das Widget → Datei an Klatsch-Node senden
- Frei verschiebbar; Position wird gespeichert

Start:  python klatsch_drop.py
"""

import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path

try:
    import requests  # type: ignore
except ImportError:
    requests = None  # type: ignore

# ──────────────────────────────────────────────────────────────────────────────
# Config helpers
# ──────────────────────────────────────────────────────────────────────────────
_CFG_DIR = Path.home() / ".klatsch"
_CFG_FILE = _CFG_DIR / "settings.json"
_POS_FILE = _CFG_DIR / "drop_pos.json"


def _load_cfg() -> dict:
    if _CFG_FILE.exists():
        try:
            with open(_CFG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_pos(x: int, y: int):
    _CFG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(_POS_FILE, "w", encoding="utf-8") as f:
            json.dump({"x": x, "y": y}, f)
    except Exception:
        pass


def _load_pos() -> tuple[int, int]:
    if _POS_FILE.exists():
        try:
            with open(_POS_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                return int(d["x"]), int(d["y"])
        except Exception:
            pass
    # Default: bottom-right corner, offset 120px up
    return -1, -1


# ──────────────────────────────────────────────────────────────────────────────
# Colors
# ──────────────────────────────────────────────────────────────────────────────
_BG = "#1e1e2e"
_GREEN = "#a6e3a1"
_YELLOW = "#f9e2af"
_RED = "#f38ba8"
_BLUE = "#89b4fa"
_GREY = "#585b70"

_SIZE = 72        # widget size in pixels
_POLL_MS = 3000   # status poll interval


class DropWidget:
    def __init__(self):
        cfg = _load_cfg()
        self._peer_port = int(cfg.get("peer_port", 7790))
        self._lang = cfg.get("language", "de")
        self._status_url = f"http://localhost:{self._peer_port}/status"
        self._notify_url = f"http://localhost:{self._peer_port}/notify"

        self.root = tk.Tk()
        self.root.title("Klatsch Drop")
        self.root.geometry(f"{_SIZE}x{_SIZE}")
        self.root.resizable(False, False)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=_BG)

        # Transparent click-through is NOT set so we can drag
        self.root.attributes("-alpha", 0.92)

        # ── Canvas for logo + ring ──
        self._canvas = tk.Canvas(
            self.root, width=_SIZE, height=_SIZE, bg=_BG,
            highlightthickness=0, cursor="hand2",
        )
        self._canvas.pack(fill="both", expand=True)

        # Border ring (drawn first so logo is on top)
        pad = 3
        self._ring = self._canvas.create_oval(
            pad, pad, _SIZE - pad, _SIZE - pad,
            outline=_GREEN, width=4, fill=_BG,
        )

        # Logo — try klatsch.png, fall back to text paw
        self._img = None
        logo_path = Path(__file__).resolve().parent / "klatsch.png"
        if logo_path.exists():
            try:
                from PIL import Image, ImageTk  # type: ignore
                img = Image.open(logo_path).convert("RGBA")
                img.thumbnail((_SIZE - 14, _SIZE - 14), Image.LANCZOS)
                self._img = ImageTk.PhotoImage(img)
                self._canvas.create_image(_SIZE // 2, _SIZE // 2, image=self._img)
            except ImportError:
                pass  # PIL not installed → fall through to text

        if self._img is None:
            self._canvas.create_text(
                _SIZE // 2, _SIZE // 2,
                text="🐾", font=("Segoe UI Emoji", 28), fill="white",
            )

        # ── Drag-to-move ──
        self._drag_x = 0
        self._drag_y = 0
        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Button-3>", self._show_menu)

        # File drop — try tkinterdnd2
        self._has_dnd = False
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore  # noqa: F401
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)
            self._has_dnd = True
        except Exception:
            pass  # no dnd support

        # ── Tooltip on hover ──
        self._tooltip: tk.Toplevel | None = None
        self._last_status: str = ""
        self._canvas.bind("<Enter>", self._show_tooltip)
        self._canvas.bind("<Leave>", self._hide_tooltip)

        # ── Context menu ──
        self._menu = tk.Menu(self.root, tearoff=0, bg="#2a2a3e", fg="white",
                             activebackground="#7c6ff0", activeforeground="white",
                             font=("Segoe UI", 10))
        if self._lang == "de":
            self._menu.add_command(label="📊 Status-Popup öffnen", command=self._open_popup)
            self._menu.add_command(label="⚙  Einstellungen",       command=self._open_settings)
            self._menu.add_separator()
            self._menu.add_command(label="🙈 Ausblenden",           command=self.root.withdraw)
            self._menu.add_command(label="✕  Beenden",              command=self.root.destroy)
        else:
            self._menu.add_command(label="📊 Open Status Popup", command=self._open_popup)
            self._menu.add_command(label="⚙  Settings",          command=self._open_settings)
            self._menu.add_separator()
            self._menu.add_command(label="🙈 Hide",               command=self.root.withdraw)
            self._menu.add_command(label="✕  Quit",               command=self.root.destroy)

        # ── Place window ──
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        px, py = _load_pos()
        if px < 0 or py < 0:
            px = sw - _SIZE - 18
            py = sh - _SIZE - 80
        px = max(0, min(px, sw - _SIZE))
        py = max(0, min(py, sh - _SIZE))
        self.root.geometry(f"{_SIZE}x{_SIZE}+{px}+{py}")

        # Start status polling
        self._poll()

    # ── Drag support ──────────────────────────────────────────────────────────
    def _on_press(self, ev):
        self._drag_x = ev.x_root - self.root.winfo_x()
        self._drag_y = ev.y_root - self.root.winfo_y()

    def _on_drag(self, ev):
        x = ev.x_root - self._drag_x
        y = ev.y_root - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def _on_release(self, ev):
        # Click (no drag) → open popup
        moved = abs((ev.x_root - self._drag_x) - self.root.winfo_x()) + \
                abs((ev.y_root - self._drag_y) - self.root.winfo_y())
        _save_pos(self.root.winfo_x(), self.root.winfo_y())
        if moved < 5:
            self._open_popup()

    # ── Status polling + ring color ──────────────────────────────────────────
    def _poll(self):
        threading.Thread(target=self._fetch_status, daemon=True).start()
        self.root.after(_POLL_MS, self._poll)

    def _fetch_status(self):
        if requests is None:
            return
        try:
            r = requests.get(self._status_url, timeout=2)
            if r.status_code == 200:
                data = r.json()
                self.root.after(0, lambda: self._apply_status(data))
            else:
                self.root.after(0, lambda: self._set_ring(_GREY))
        except Exception:
            self.root.after(0, lambda: self._set_ring(_GREY))

    def _apply_status(self, data: dict):
        listening = data.get("listening_enabled", False)
        speaking = data.get("is_speaking", False)
        paused = data.get("tts_paused", False)

        summary = data.get("events", [])
        last = summary[-1]["detail"] if summary else ""
        self._last_status = last

        if speaking:
            self._set_ring(_YELLOW)
        elif paused:
            self._set_ring(_RED)
        elif listening:
            self._set_ring(_GREEN)
        else:
            self._set_ring(_GREY)

    def _set_ring(self, color: str):
        self._canvas.itemconfig(self._ring, outline=color)

    # ── Tooltip ──────────────────────────────────────────────────────────────
    def _show_tooltip(self, ev):
        if self._tooltip:
            return
        tip = tk.Toplevel(self.root)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        x = self.root.winfo_x() + _SIZE + 6
        y = self.root.winfo_y() + _SIZE // 4
        tip.geometry(f"+{x}+{y}")
        label_txt = self._last_status or ("Klatsch 🐾" if not self._lang == "de" else "Klatsch 🐾")
        if not label_txt:
            label_txt = "Klatsch 🐾"
        tk.Label(
            tip, text=label_txt, bg="#2a2a3e", fg="white",
            font=("Segoe UI", 9), padx=8, pady=4, wraplength=220, justify="left",
        ).pack()
        self._tooltip = tip

    def _hide_tooltip(self, ev):
        if self._tooltip:
            self._tooltip.destroy()
            self._tooltip = None

    # ── File drop ────────────────────────────────────────────────────────────
    def _on_drop(self, ev):
        paths = self.root.tk.splitlist(ev.data)
        for p in paths:
            threading.Thread(target=self._send_file, args=(p,), daemon=True).start()

    def _send_file(self, path: str):
        if requests is None:
            return
        try:
            with open(path, "rb") as f:
                name = Path(path).name
                requests.post(
                    f"http://localhost:{self._peer_port}/upload",
                    files={"file": (name, f)},
                    timeout=30,
                )
        except Exception:
            pass

    # ── Context menu ─────────────────────────────────────────────────────────
    def _show_menu(self, ev):
        self._menu.tk_popup(ev.x_root, ev.y_root)

    # ── Actions ──────────────────────────────────────────────────────────────
    def _open_popup(self):
        popup_path = Path(__file__).resolve().parent / "klatsch_popup.py"
        if popup_path.exists():
            subprocess.Popen(
                [sys.executable, str(popup_path)],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

    def _open_settings(self):
        ui_path = Path(__file__).resolve().parent / "klatsch_ui.py"
        if ui_path.exists():
            subprocess.Popen(
                [sys.executable, str(ui_path)],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

    def run(self):
        self.root.mainloop()


# ──────────────────────────────────────────────────────────────────────────────
# Entry
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    DropWidget().run()

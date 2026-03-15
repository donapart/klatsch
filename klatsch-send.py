#!/usr/bin/env python3
"""
klatsch-send.py — Explorer context menu helper for Klatsch 🐾

Accepts file paths from Windows Explorer context menu / "Send To" and
forwards them to the local Klatsch instance via HTTP API.

Actions:
  speak     — Read the file content aloud via TTS
  ask       — Send file content to the AI agent ("What is this?")
  summarize — Ask the AI agent to summarize the file

Usage:
  python klatsch-send.py speak <file> [<file2> ...]
  python klatsch-send.py ask <file>
  python klatsch-send.py summarize <file>
  python klatsch-send.py <file>           # default: ask
"""

import os
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path

KLATSCH_URL = os.getenv("KLATSCH_URL", "http://localhost:7790")
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://192.168.0.67:18789")
GATEWAY_TOKEN = os.getenv("GATEWAY_TOKEN", "opensesame")
AGENT_ID = os.getenv("AGENT_ID", "main")

MAX_FILE_SIZE = 50_000  # 50 KB text limit for AI context


def post_json(url: str, data: dict, timeout: int = 30) -> dict:
    """POST JSON to a URL and return the response."""
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        return {"error": str(e)}


def read_file_text(path: str) -> str | None:
    """Read a text file, return None if binary or too large."""
    p = Path(path)
    if not p.is_file():
        return None
    if p.stat().st_size > MAX_FILE_SIZE:
        return f"[Datei zu groß: {p.stat().st_size:,} Bytes, nur Name gesendet]"
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def action_speak(files: list[str]) -> None:
    """Read file content aloud via Klatsch TTS."""
    for f in files:
        content = read_file_text(f)
        if content:
            name = Path(f).name
            text = f"Datei {name}: {content[:2000]}"
            result = post_json(f"{KLATSCH_URL}/speak", {"text": text})
            if "error" in result:
                print(f"Fehler bei {name}: {result['error']}")
            else:
                print(f"Vorlesen: {name}")
        else:
            print(f"Übersprungen (binär/nicht lesbar): {f}")


def send_to_gateway(message: str) -> str:
    """Send a message to the OpenClaw gateway agent and return the response."""
    url = f"{GATEWAY_URL}/api/v1/agent/{AGENT_ID}/message"
    data = {"message": message, "source": "klatsch-explorer"}
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GATEWAY_TOKEN}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            return result.get("response", result.get("text", str(result)))
    except urllib.error.URLError as e:
        return f"Fehler: {e}"


def action_ask(files: list[str]) -> None:
    """Send file to AI agent with 'what is this?' prompt."""
    for f in files:
        name = Path(f).name
        content = read_file_text(f)
        if content and not content.startswith("[Datei zu groß"):
            prompt = f"Ich sende dir eine Datei aus dem Explorer. Dateiname: {name}\n\nInhalt:\n```\n{content[:8000]}\n```\n\nWas ist das für eine Datei? Beschreibe kurz den Inhalt."
        else:
            prompt = f"Ich habe eine Datei markiert: {f}\nWas kannst du mir über diese Datei sagen?"
        print(f"Sende an Agent: {name}...")
        response = send_to_gateway(prompt)
        # Speak the response via Klatsch
        post_json(f"{KLATSCH_URL}/speak", {"text": response[:1500]})
        print(f"Antwort: {response[:200]}")


def action_summarize(files: list[str]) -> None:
    """Ask AI agent to summarize the file."""
    for f in files:
        name = Path(f).name
        content = read_file_text(f)
        if content and not content.startswith("[Datei zu groß"):
            prompt = f"Fasse diese Datei zusammen. Dateiname: {name}\n\nInhalt:\n```\n{content[:8000]}\n```\n\nGib eine knappe Zusammenfassung auf Deutsch."
        else:
            prompt = f"Fasse zusammen was die Datei {f} enthalten könnte (basierend auf dem Namen und Pfad)."
        print(f"Zusammenfassung: {name}...")
        response = send_to_gateway(prompt)
        post_json(f"{KLATSCH_URL}/speak", {"text": response[:1500]})
        print(f"Zusammenfassung: {response[:200]}")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    # Determine action and files
    actions = {"speak", "ask", "summarize"}
    if args[0].lower() in actions:
        action = args[0].lower()
        files = args[1:]
    else:
        action = "ask"
        files = args

    if not files:
        print("Keine Dateien angegeben.")
        sys.exit(1)

    # Resolve paths
    files = [os.path.abspath(f) for f in files]

    if action == "speak":
        action_speak(files)
    elif action == "ask":
        action_ask(files)
    elif action == "summarize":
        action_summarize(files)


if __name__ == "__main__":
    main()

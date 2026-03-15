# Klatsch 🐾

> **Entwickelt von Dano Schönwald**

Ein lokaler Sprachassistent für Windows, Linux und macOS — kein Cloud-Konto notwendig, vollständig offline-fähig.

Unterstützte Sprachen: Deutsch 🇩🇪 · Englisch 🇬🇧 · Spanisch 🇪🇸 · Französisch 🇫🇷 · Italienisch 🇮🇹 · Polnisch 🇵🇱 · Japanisch 🇯🇵 · Chinesisch 🇨🇳 (und weitere)

---

## Inhaltsverzeichnis

- [Was ist Klatsch?](#was-ist-klatsch)
- [Plattformen](#plattformen)
- [Schnellstart](#schnellstart)
- [Internationalisierung](#internationalisierung)
- [Sprachbefehle](#sprachbefehle)
- [Konfiguration](#konfiguration)
- [Hintergrundwächter](#hintergrundwächter)
- [HTTP-API](#http-api)
- [Windows-Installer (.exe)](#windows-installer-exe)
- [Entwicklung & Mitarbeit](#entwicklung--mitarbeit)

---

## Was ist Klatsch?

Klatsch ist ein Python-basierter Sprachassistent mit:

- **Offline-Transkription** via [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- **Wake-Word-Erkennung** via [OpenWakeWord](https://github.com/dscripka/openWakeWord)
- **Text-to-Speech** via [edge-tts](https://github.com/rany2/edge-tts) (Microsoft Neural Voices, kostenlos)
- **Lokale KI** via [Ollama](https://ollama.ai/) (optional)
- **Peer-to-Peer-Intercom** zwischen mehreren Klatsch-Instanzen im Netzwerk
- **Systemautomatisierung**: Apps öffnen, Fensterfokus, Zwischenablage, Erinnerungen
- **Intercom-Sprachnachrichten** für andere Rechner im Heimnetz

---

## Plattformen

| Plattform | Status | Hinweise |
|-----------|--------|----------|
| Windows 10/11 | ✅ Primär unterstützt | Voll getestet, exe-Build verfügbar |
| Linux (Debian/Ubuntu) | ✅ Getestet | `apt install portaudio19-dev` benötigt |
| macOS 12+ | ⚠️ Experimentell | `brew install portaudio`; TTS-Stimme ggf. anpassen |
| Raspberry Pi (64-bit) | ⚠️ Experimentell | Whisper Tiny-Modell empfohlen |

---

## Schnellstart

### Voraussetzungen

- Python 3.10 oder neuer
- [Git](https://git-scm.com/)
- Mikrofon
- (Optional) [Ollama](https://ollama.ai/) für lokale KI-Antworten

### Installation

```bash
git clone https://github.com/donapart/klatsch.git
cd klatsch
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### Starten

```batch
# Windows (Doppelklick oder Kommandozeile)
start.cmd

# Oder direkt
python klatsch.py
```

---

## Internationalisierung

Klatsch wählt Sprache und TTS-Stimme automatisch per Umgebungsvariable:

```batch
# Windows
set KLATSCH_LANG=de
python klatsch.py

# Linux/macOS
KLATSCH_LANG=en python klatsch.py
```

### Unterstützte Sprachcodes

| Code | Sprache | Standard-TTS-Stimme |
|------|---------|---------------------|
| `de` | Deutsch (Standard) | de-DE-ConradNeural |
| `en` | Englisch | en-US-GuyNeural |
| `es` | Spanisch | es-ES-AlvaroNeural |
| `fr` | Französisch | fr-FR-HenriNeural |
| `it` | Italienisch | it-IT-DiegoNeural |
| `pt` | Portugiesisch | pt-BR-AntonioNeural |
| `nl` | Niederländisch | nl-NL-MaartenNeural |
| `pl` | Polnisch | pl-PL-MarekNeural |
| `ja` | Japanisch | ja-JP-KeitaNeural |
| `zh` | Chinesisch | zh-CN-YunxiNeural |

Die TTS-Stimme kann auch manuell überschrieben werden:

```batch
set TTS_VOICE=de-DE-KatjaNeural
```

---

## Sprachbefehle

Klatsch versteht Befehle auf Deutsch, Englisch und Spanisch:

### App öffnen

| Befehl | Sprache |
|--------|---------|
| „Öffne Chrome" | Deutsch |
| „Open Chrome" | Englisch |
| „Abre Chrome" | Spanisch |

### Zwischenablage

| Befehl | Sprache |
|--------|---------|
| „Was ist in der Zwischenablage?" | Deutsch |
| „Read clipboard" | Englisch |
| „¿Qué hay en el portapapeles?" | Spanisch |

### Erinnerungen

| Befehl | Sprache |
|--------|---------|
| „Erinnere mich in 10 Minuten an das Meeting" | Deutsch |
| „Remind me in 10 minutes about the meeting" | Englisch |
| „Recuérdame en 10 minutos about the meeting" | Spanisch |

### Ollama / Lokale KI

| Befehl | Sprache |
|--------|---------|
| „Frag Ollama: Was ist Quantencomputing?" | Deutsch |
| „Ask Ollama: What is quantum computing?" | Englisch |
| „Pregunta a Ollama: ¿Qué es la computación cuántica?" | Spanisch |

### Fensterfokus

| Befehl | Sprache |
|--------|---------|
| „Fokussiere Discord" | Deutsch |
| „Focus Discord" / „Bring Discord to front" | Englisch |
| „Enfoca Discord" | Spanisch |

### Broadcast an alle Peers

| Befehl | Sprache |
|--------|---------|
| „Sag allen: Das Essen ist fertig!" | Deutsch |
| „Tell everyone: Dinner is ready!" | Englisch |
| „Dile a todos: La cena está lista!" | Spanisch |

### Intercom (Peer-to-Peer)

```
„Sag [Name] [Nachricht]"       z.B. „Sag Max: Kannst du kurz kommen?"
„Tell [Name] [message]"        z.B. „Tell Sarah: Meeting in 5 minutes"
„Dile a [Name] [mensaje]"      z.B. „Dile a Juan: La reunión empezó"
```

---

## Konfiguration

Alle Einstellungen werden als Umgebungsvariablen gesetzt:

```batch
:: Sprache
set KLATSCH_LANG=de

:: Wake-Word-Schwellwert (0.0–1.0, Standard: 0.5)
set WAKE_THRESHOLD=0.5

:: Whisper-Modell (tiny / base / small / medium / large-v3)
set WHISPER_MODEL=base

:: Ollama-URL
set OLLAMA_URL=http://localhost:11434

:: Gateway (OpenClaw oder kompatibel)
set GATEWAY_URL=http://localhost:3000

:: TTS-Stimme überschreiben
set TTS_VOICE=de-DE-ConradNeural

:: Audio-Geräte
set INPUT_DEVICE=0
set OUTPUT_DEVICE=1

:: Peers für Intercom (kommagetrennt)
set PEERS=http://192.168.1.100:7790,http://192.168.1.101:7790
```

---

## Hintergrundwächter

Klatsch startet automatisch mehrere Hintergrundthreads:

| Wächter | Beschreibung |
|---------|--------------|
| `presence_watcher` | Erkennt Mausbewegungen → Anwesenheitsstatus |
| `disk_watcher` | Meldet neue USB-Laufwerke per Sprache |
| `reminder_watcher` | Löst Spracherinnerungen zur eingestellten Zeit aus |
| `morning_briefing` | Tägliches Morgen-Briefing von der KI (06:00–09:00 Uhr) |

---

## HTTP-API

Klatsch läuft als HTTP-Server auf Port **7790** (konfigurierbar via `PEER_PORT`):

| Endpunkt | Methode | Beschreibung |
|----------|---------|--------------|
| `/health` | GET | Statuscheck (gibt Hostname zurück) |
| `/speak` | POST | Text per TTS sprechen lassen |
| `/notify` | POST | Benachrichtigung empfangen |
| `/clipboard` | GET | Zwischenablage lesen |
| `/clipboard` | POST | Zwischenablage setzen |
| `/screenshot` | GET | Screenshot als JPEG |
| `/processes` | GET | Laufende Prozesse |
| `/syshealth` | GET | CPU/RAM/Festplatten-Status |
| `/find-file` | GET | Datei im Dateisystem suchen |
| `/open-app` | POST | App öffnen |
| `/remind` | POST | Erinnerung planen |
| `/broadcast` | POST | Nachricht an alle Peers senden |

---

## Windows-Installer (.exe)

Eine eigenständige `.exe`-Datei kann mit dem enthaltenen Build-Skript erstellt werden:

```powershell
.\build-exe.ps1
```

Das Skript installiert PyInstaller (falls noch nicht vorhanden) und erzeugt `dist\Klatsch.exe`.

---

## Entwicklung & Mitarbeit

Entwickelt von **Dano Schönwald**.

Beiträge sind willkommen! Bitte lies [CONTRIBUTING.md](../CONTRIBUTING.md) vor dem ersten Pull Request.

### Entwicklungsumgebung einrichten

```bash
git clone https://github.com/donapart/klatsch.git
cd klatsch
python -m venv .venv
source .venv/bin/activate  # oder .venv\Scripts\activate auf Windows
pip install -r requirements.txt
python klatsch.py
```

### Lizenz

MIT — Details in [LICENSE](LICENSE).

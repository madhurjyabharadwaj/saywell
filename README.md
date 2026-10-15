# Saywell

Voice dictation for Windows. **Hold a hotkey, speak, let go**, and the cleaned-up text appears wherever your cursor is: email, Slack, a terminal, anywhere.

A small bar sits at the bottom of your screen. It shows a live waveform while you talk. Every dictation is saved to **History**, where you can search it and copy it again later.

| Gesture | What it does |
|---|---|
| Hold **Ctrl + Win** | Records while held; release to transcribe and paste |
| Tap **Space** while holding | Hands-free: keeps recording after you let go; press the hotkey again to finish |
| **Esc** while recording | Cancel |
| **Alt + Shift + Z** | Paste your last transcript again |
| Click the bar | Open Saywell |

Closing the window keeps Saywell running in the system tray. Quit it from the tray icon.

## Install (for people you share it with)

1. Download `Saywell-windows.zip`, unzip it anywhere (e.g. `Documents\Saywell`), and run `Saywell.exe`.
2. Paste a free Groq API key from [console.groq.com/keys](https://console.groq.com/keys) into **Settings**, then click **Save changes**.
3. Click **Add to Desktop and Start menu** in Settings so it opens like any other app.

Windows SmartScreen may warn about an unknown publisher the first time, because the app isn't code-signed. Choose **More info → Run anyway**.

## Develop

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pytest
.\.venv\Scripts\python.exe -m saywell                      # run with a console (logs print here)
.\.venv\Scripts\python.exe -m saywell --install-shortcuts  # Desktop/Start menu icons that run this checkout
.\.venv\Scripts\python.exe -m pytest -q tests
```

Shortcuts made with `--install-shortcuts` run your source code directly, so a code change applies the next time you open Saywell.

### Build the shareable app

```powershell
.\build.ps1
```

This produces `dist\Saywell\Saywell.exe` and `dist\Saywell-windows.zip`. The zip bundles Python and every dependency, so the people you share it with don't need Python installed. Re-run the build whenever you want to share a newer version. A good place to publish the zip is a GitHub Release.

## Where things are stored

Everything lives in `%APPDATA%\Saywell`. **Settings → Open data folder** opens it.

| File | Contents |
|---|---|
| `settings.json` | Settings. API keys are encrypted with Windows DPAPI, so the file can't be used on another account or PC |
| `history.db` | Every dictation (SQLite): raw transcript, cleaned text, app, timings |
| `audio\` | Recordings of dictations that failed (offline, API down). They're deleted once a **Retry** succeeds |
| `saywell.log` | Output when running without a console |

If you used FlowLite, its settings and history are copied over on first launch.

## How it works

| Stage | Module | Notes |
|---|---|---|
| Hotkey | `hotkey.py` | `WH_KEYBOARD_LL` hook and a small state machine; `RegisterHotKey` for paste-last |
| Context | `context.py` | UI Automation reads the focused app and nearby text so formatting matches the destination. Password fields are skipped |
| Audio | `audio.py` | 16 kHz mono via `sounddevice` |
| Speech-to-text | `asr.py` | Any OpenAI-compatible `/audio/transcriptions` endpoint (Groq `whisper-large-v3-turbo` by default) |
| Cleanup | `cleanup.py` | LLM removes filler words and applies spoken corrections (“at 3, no actually 4” → “at 4”). Groq by default; Claude is optional |
| Paste | `inserter.py` | Clipboard swap + `Ctrl+V`, then restores your clipboard. Dictations stay out of Win+V history |
| UI | `overlay.py`, `ui.py` | Qt (PySide6): floating bar, History and Settings window, tray icon |

Advanced options that aren't in Settings (other ASR/LLM providers, models, language, max recording length) can be edited in `settings.json`; restart Saywell afterwards. To use Claude for cleanup, set `"cleanup": {"provider": "anthropic", "model": "claude-haiku-5-5"}` and the `ANTHROPIC_API_KEY` environment variable.

If you also run Wispr Flow, both apps listen for Ctrl + Win. Quit one of them, or pick a different shortcut in Settings.

## License

MIT. See [LICENSE](LICENSE).

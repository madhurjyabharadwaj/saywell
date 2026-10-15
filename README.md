# Saywell

**Why is typing still the slowest part of the working day?**

Saywell is voice dictation for Windows. Hold a hotkey, speak, and finished text lands where your cursor is: Slack, email, a ticket, a doc, a terminal.

[Download for Windows](https://github.com/madhurjyabharadwaj/saywell/releases/latest) · [Case study](https://www.madhurjyabharadwaj.com/work/saywell)

## The problem

Most of a working day is writing: a Slack reply, a ticket, a paragraph in a PRD, a note in a tracker. Almost none of it is hard to compose. It's just slow to type, and typing it pulls you out of whatever you were doing.

Dictation should fix that, and usually it doesn't. You get a transcript with every "um", every false start and every "no, sorry, make that Thursday" left in. Then you have to read it and fix it, which costs back the time you saved.

## What Saywell is built to move

The metric is **time from a thought to finished text in the box you're writing in**, and with it, **the number of fixes you make after dictating**. The goal for fixes is zero: what lands should be what you'd have typed.

Two product decisions follow from that.

**Cleanup is the feature.** Transcription is largely solved. What decides whether dictation is usable is what happens between the transcript and the text box. Saywell strips filler, fixes punctuation and applies spoken corrections, so "move it to 3, no actually 4" arrives as "move it to 4".

**It fits into the work, not beside it.** There's no window to switch to and nothing to copy out of. The text pastes where the cursor already is, because the moment you leave what you were writing, dictation stops being faster than typing.

## How it fits into your day

| Gesture | What it does |
|---|---|
| Hold **your dictation shortcut** | Records while held; release to transcribe and paste |
| Tap **Space** while holding | Hands-free: keeps recording after you let go; press the hotkey again to finish |
| **Esc** while recording | Cancel |
| **Alt + Shift + Z** | Paste your last dictation again |
| Click the bar | Open Saywell |

Three details carry more weight than they look:

- **It reads the app you're in**, so the text matches where it's going: a casual Slack reply, a properly punctuated email.
- **It skips password fields entirely.**
- **It leaves your clipboard alone.** Whatever you had copied is restored after the paste, and dictations stay out of clipboard history.

Every dictation is saved to a local, searchable **History**, so a paragraph you dictated last week is one search away. If a dictation fails because you're offline, the recording is kept so you can retry it.

A small bar at the bottom of the screen shows a live waveform while you talk. Closing the window keeps Saywell running in the system tray.

## Install

1. Download `Saywell-windows.zip` from the [latest release](https://github.com/madhurjyabharadwaj/saywell/releases/latest), unzip it anywhere (e.g. `Documents\Saywell`), and run `Saywell.exe`.
2. Paste a free Groq API key from [console.groq.com/keys](https://console.groq.com/keys) into **Settings**, then click **Save changes**.
3. Click **Add to Desktop and Start menu** in Settings so it opens like any other app.

Python and every dependency are bundled, so there's nothing else to install.

Windows SmartScreen may warn about an unknown publisher the first time, because the app isn't code-signed. Choose **More info → Run anyway**.

Pick the dictation shortcut in Settings; if another app already uses the one you chose, switch to one of the others.

## Privacy and where things are stored

Your history and settings stay on your PC, in `%APPDATA%\Saywell`. **Settings → Open data folder** opens it. Audio and text are sent only to the speech-to-text and cleanup providers you configure (Groq by default).

| File | Contents |
|---|---|
| `settings.json` | Settings. API keys are encrypted with Windows DPAPI, so the file can't be used on another account or PC |
| `history.db` | Every dictation (SQLite): raw transcript, cleaned text, app, timings |
| `audio\` | Recordings of dictations that failed (offline, API down). They're deleted once a **Retry** succeeds |
| `saywell.log` | Output when running without a console |

## How it works

| Stage | Module | Notes |
|---|---|---|
| Hotkey | `hotkey.py` | `WH_KEYBOARD_LL` hook and a small state machine; `RegisterHotKey` for paste-last |
| Context | `context.py` | UI Automation reads the focused app and nearby text so formatting matches the destination. Password fields are skipped |
| Audio | `audio.py` | 16 kHz mono via `sounddevice` |
| Speech-to-text | `asr.py` | Any OpenAI-compatible `/audio/transcriptions` endpoint (Groq `whisper-large-v3-turbo` by default) |
| Cleanup | `cleanup.py` | Removes filler words and applies spoken corrections. Any OpenAI-compatible chat endpoint (Groq by default) or Anthropic |
| Paste | `inserter.py` | Clipboard swap + `Ctrl+V`, then restores your clipboard |
| UI | `overlay.py`, `ui.py` | Qt (PySide6): floating bar, History and Settings window, tray icon |

Advanced options that aren't in Settings (other providers, models, language, max recording length) can be edited in `settings.json`; restart Saywell afterwards. To use Claude for cleanup, set `"cleanup": {"provider": "anthropic", "model": "claude-haiku-5-5"}` and the `ANTHROPIC_API_KEY` environment variable.

## Develop

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pytest
.\.venv\Scripts\python.exe -m saywell                      # run with a console (logs print here)
.\.venv\Scripts\python.exe -m saywell --install-shortcuts  # Desktop/Start menu icons that run this checkout
.\.venv\Scripts\python.exe -m pytest -q tests
```

Shortcuts made with `--install-shortcuts` run your source code directly, so a code change applies the next time you open Saywell.

To build the shareable app, run `.\build.ps1`. It produces `dist\Saywell\Saywell.exe` and `dist\Saywell-windows.zip`, which bundles Python and every dependency. Publish the zip as a GitHub Release.

## License

MIT. See [LICENSE](LICENSE).

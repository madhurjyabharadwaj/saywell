"""Saywell engine: hold a hotkey, speak, release - polished text appears where your cursor is.

Pipeline:
  hotkey hook -> mic capture + context capture -> ASR -> LLM formatting -> paste

The engine has no UI of its own. It drives an overlay through set_mode/set_locked/
flash and reports history changes through a callback; both may be called from
any thread.
"""
import os
import queue
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from . import asr, context, inserter, sounds
from .audio import SAMPLE_RATE, Recorder, to_wav
from .cleanup import OffTranscript, make_cleaner
from .history import History
from .hotkey import HotkeyListener


def smart_space(text: str, ctx: context.AppContext) -> str:
    """Insert a separating space when continuing after a word."""
    b = ctx.before_text
    if text and b and not b[-1].isspace() and b[-1] not in "([{\"'/“‘" and text[0].isalnum():
        return " " + text
    return text


_KEY_NAMES = {"ralt": "Right Alt", "lalt": "Left Alt", "rctrl": "Right Ctrl", "lctrl": "Left Ctrl",
              "rshift": "Right Shift", "lshift": "Left Shift", "rwin": "Right Win", "lwin": "Left Win",
              "esc": "Esc", "capslock": "Caps Lock"}


def pretty_keys(keys: list[str] | None) -> str:
    if not keys:
        return "Off"
    return " + ".join(_KEY_NAMES.get(k.lower(), k.capitalize() if len(k) > 1 else k.upper()) for k in keys)


@dataclass
class Session:
    started: float
    ctx: context.AppContext = field(default_factory=context.AppContext)
    ctx_ready: threading.Event = field(default_factory=threading.Event)


class App:
    def __init__(self, cfg: dict, data_dir: str, overlay, on_history: Callable[[], None] = lambda: None,
                 on_notice: Callable[[str], None] = print):
        self.data_dir = data_dir
        self.audio_dir = os.path.join(data_dir, "audio")
        os.makedirs(self.audio_dir, exist_ok=True)
        self.history = History(os.path.join(data_dir, "history.db"))
        self.overlay = overlay
        self.on_history = on_history
        self.on_notice = on_notice
        self.events: "queue.Queue[str]" = queue.Queue()
        self.session: Session | None = None
        self.paste_lock = threading.Lock()
        self.hotkey: HotkeyListener | None = None
        self._apply(cfg)

    # -- lifecycle ------------------------------------------------------------
    def _apply(self, cfg: dict) -> None:
        self.cfg = cfg
        self.recorder = Recorder(device=cfg["microphone"])
        self.cleaner = None
        if cfg["cleanup"]["enabled"]:
            try:
                self.cleaner = make_cleaner(cfg["cleanup"])
            except Exception as e:  # no key yet: dictation still works, just unformatted
                print(f"[cleanup] disabled: {e}")

    def start(self) -> None:
        threading.Thread(target=self._warm_up, daemon=True).start()
        self._start_hotkey()
        threading.Thread(target=self._controller, name="controller", daemon=True).start()
        print(f"Saywell ready. Hold {pretty_keys(self.cfg['hotkey'])} and speak.", flush=True)

    def _warm_up(self) -> None:
        """Load UI Automation (type library generation) before the first dictation needs it."""
        import comtypes
        comtypes.CoInitialize()
        try:
            ctx = context.capture()
            if any(e.startswith("uia") for e in ctx.errors):
                print(f"[context] UI Automation unavailable: {ctx.errors}", flush=True)
        finally:
            comtypes.CoUninitialize()

    def _start_hotkey(self) -> None:
        self.hotkey = HotkeyListener(self.cfg["hotkey"], self.cfg["lock_key"], self.events.put, self.cfg["min_hold_ms"],
                                     shortcuts={"paste_last": self.cfg.get("paste_last_hotkey")})
        self.hotkey.start()
        if self.hotkey.shortcut_conflicts:
            self.on_notice(f"{pretty_keys(self.cfg['paste_last_hotkey'])} is already used by another app, "
                           "so 'paste last' is off. Pick another shortcut in Settings.")

    def stop(self) -> None:
        if self.hotkey:
            self.hotkey.stop()

    def reconfigure(self, cfg: dict) -> None:
        """Apply new settings (called from the UI thread after Save)."""
        if self.session:
            self._cancel()
        self.stop()
        self._apply(cfg)
        self._start_hotkey()

    def _controller(self) -> None:
        while True:
            ev = self.events.get()
            try:
                {"start": self._start, "stop": self._stop, "cancel": self._cancel, "lock": self._lock,
                 "timeout": self._stop, "paste_last": self.paste_last}[ev]()
            except Exception:
                traceback.print_exc()
                self.overlay.set_mode("idle")
                self.overlay.flash("Mic error")
                self.session = None

    # -- events -----------------------------------------------------------------
    def _start(self) -> None:
        if self.session:
            return
        s = Session(started=time.monotonic())
        self.session = s
        self.recorder.start()
        sounds.play(sounds.START, self.cfg["sounds"])
        self.overlay.set_mode("listening")
        threading.Thread(target=self._capture_context, args=(s,), daemon=True).start()
        threading.Timer(self.cfg["max_recording_s"], self._max_length, args=(s,)).start()

    def _capture_context(self, s: Session) -> None:
        import comtypes
        comtypes.CoInitialize()
        try:
            s.ctx = context.capture()
        finally:
            s.ctx_ready.set()
            comtypes.CoUninitialize()

    def _max_length(self, s: Session) -> None:
        if self.session is s:
            self.hotkey.force_idle()
            self.events.put("timeout")

    def _lock(self) -> None:
        self.overlay.set_locked(True)

    def _cancel(self) -> None:
        if not self.session:
            return
        self.recorder.stop()
        self.session = None
        self.overlay.set_mode("idle")

    def _stop(self) -> None:
        s = self.session
        if not s:
            return
        samples = self.recorder.stop()
        peak = self.recorder.peak
        self.session = None
        sounds.play(sounds.STOP, self.cfg["sounds"])
        self.overlay.set_mode("processing")
        threading.Thread(target=self._process, args=(s, samples, peak), daemon=True).start()

    def paste_last(self) -> None:
        text = self.history.last_text()
        if not text:
            self.overlay.flash("Nothing to paste yet")
            return

        def go():
            with self.paste_lock:
                inserter.paste_text(text.lstrip(), self.cfg["paste_with_shift_insert"], self.cfg["restore_clipboard"])
        threading.Thread(target=go, daemon=True).start()

    # -- pipeline -------------------------------------------------------------
    def _words(self) -> list[str]:
        return list(self.cfg["dictionary"]) + ([self.cfg["user_name"]] if self.cfg["user_name"] else [])

    def _transcribe_and_clean(self, wav: bytes, ctx: context.AppContext) -> tuple[str, str, str, int, int]:
        """Returns (raw, final, status, asr_ms, llm_ms). Raises asr.ASRError if speech-to-text fails."""
        t0 = time.monotonic()
        raw = asr.transcribe(wav, self.cfg["asr"], prompt=", ".join(self._words()))
        asr_ms = int((time.monotonic() - t0) * 1000)
        if not any(ch.isalnum() for ch in raw):  # e.g. "." returned for noise
            return raw, "", "empty", asr_ms, 0
        final, status, llm_ms = raw, "raw", 0
        if self.cleaner:
            t1 = time.monotonic()
            try:
                cleaned = self.cleaner.clean(raw, ctx, self.cfg["dictionary"], self.cfg["user_name"])
                if cleaned is not None:
                    final, status = cleaned, "formatted"
                else:
                    status = "fallback_refusal"
            except OffTranscript as e:
                print(f"[cleanup] answered instead of transcribing; pasting raw transcript: {e}")
                status = "fallback_off_transcript"
            except Exception as e:
                print(f"[cleanup] falling back to raw transcript: {e}")
                status = "fallback_error"
            llm_ms = int((time.monotonic() - t1) * 1000)
        return raw, final, status, asr_ms, llm_ms

    def _save_audio(self, wav: bytes) -> str:
        path = os.path.join(self.audio_dir, time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}.wav")
        with open(path, "wb") as f:
            f.write(wav)
        return path

    def _process(self, s: Session, samples: np.ndarray, peak: float) -> None:
        audio_ms = int(len(samples) * 1000 / SAMPLE_RATE)
        if audio_ms < 200 or peak < self.cfg["silence_rms"]:
            # Whisper hallucinates ("Thank you.") on silence; don't send it.
            self.overlay.set_mode("idle")
            self.overlay.flash("No speech heard")
            return
        wav = to_wav(samples)
        ctx = context.AppContext()
        try:
            s.ctx_ready.wait(1.0)
            ctx = s.ctx
            raw, final, status, asr_ms, llm_ms = self._transcribe_and_clean(wav, ctx)
            if status == "empty":
                self.overlay.set_mode("idle")
                self.overlay.flash("No speech heard")
                return
            final = smart_space(final, ctx)
            if final.strip():
                with self.paste_lock:
                    inserter.paste_text(final, self.cfg["paste_with_shift_insert"], self.cfg["restore_clipboard"])
            self.history.add(app=ctx.exe, window_title=ctx.title, raw_text=raw, final_text=final, status=status,
                             audio_ms=audio_ms, asr_ms=asr_ms, llm_ms=llm_ms)
            print(f"[{ctx.exe or '?'}] {audio_ms}ms audio | asr {asr_ms}ms | llm {llm_ms}ms | {status}: {final!r}", flush=True)
            self.overlay.set_mode("idle")
        except Exception as e:
            # Never lose a dictation: keep the recording so it can be retried from History.
            if not isinstance(e, asr.ASRError):
                traceback.print_exc()
            print(f"[saved for retry] {e}", flush=True)
            path = self._save_audio(wav)
            self.history.add(app=ctx.exe, window_title=ctx.title, raw_text="", final_text="", status="failed",
                             audio_ms=audio_ms, audio_path=path, error=str(e)[:500])
            self.overlay.set_mode("idle")
            self.overlay.flash("Saved - retry in History")
        finally:
            self.on_history()

    def retry(self, row_id: int) -> str:
        """Re-run a failed dictation from its saved audio. Returns the text (copied, not pasted)."""
        row = self.history.get(row_id)
        if not row or not row.get("audio_path") or not os.path.exists(row["audio_path"]):
            raise RuntimeError("The recording for this dictation is gone")
        with open(row["audio_path"], "rb") as f:
            wav = f.read()
        ctx = context.AppContext(exe=row.get("app") or "", title=row.get("window_title") or "")
        try:
            raw, final, status, asr_ms, llm_ms = self._transcribe_and_clean(wav, ctx)
        except Exception as e:
            self.history.update(row_id, error=str(e)[:500])
            self.on_history()
            raise
        if status == "empty":
            final = ""
        self.history.update(row_id, raw_text=raw, final_text=final, status=status if final else "empty",
                            asr_ms=asr_ms, llm_ms=llm_ms, audio_path=None, error=None)
        try:
            os.remove(row["audio_path"])
        except OSError:
            pass
        self.on_history()
        return final


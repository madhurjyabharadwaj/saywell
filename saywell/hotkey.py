"""Global push-to-talk hotkey via a low-level keyboard hook (WH_KEYBOARD_LL).

Mirrors the Wispr Flow helper's approach: the hook only tracks key state and
emits events; all real work happens on other threads.

Gestures
  hold chord           -> "start"; release any chord key -> "stop"
  chord + lock key     -> "lock" (hands-free; recording continues after release)
  chord again (locked) -> "stop"
  Esc while recording  -> "cancel"
  other key during hold-> "cancel" (user was pressing some other shortcut)

Plain shortcuts (e.g. Alt+Shift+Z for "paste last") go through RegisterHotKey on
the same thread, so Windows reports a conflict if another app already owns them.
"""
import ctypes
import threading
import time
from ctypes import wintypes
from typing import Callable

from . import win32 as w

_NAMED = {
    "ctrl": {0x11, 0xA2, 0xA3}, "lctrl": {0xA2}, "rctrl": {0xA3},
    "alt": {0x12, 0xA4, 0xA5}, "lalt": {0xA4}, "ralt": {0xA5},
    "shift": {0x10, 0xA0, 0xA1}, "lshift": {0xA0}, "rshift": {0xA1},
    "win": {0x5B, 0x5C}, "lwin": {0x5B}, "rwin": {0x5C},
    "space": {0x20}, "esc": {0x1B}, "tab": {0x09}, "capslock": {0x14},
    "enter": {0x0D}, "backspace": {0x08},
}
_WIN_VKS = {0x5B, 0x5C}
VK_ESCAPE = 0x1B
_MOD_FLAGS = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312


def parse_key(name: str) -> frozenset[int]:
    n = name.strip().lower()
    if n in _NAMED:
        return frozenset(_NAMED[n])
    if len(n) == 1 and n.isalnum():
        return frozenset({ord(n.upper())})
    if n.startswith("f") and n[1:].isdigit() and 1 <= int(n[1:]) <= 24:
        return frozenset({0x70 + int(n[1:]) - 1})
    raise ValueError(f"Unknown key name: {name!r}")


def parse_shortcut(keys: list[str]) -> tuple[int, int]:
    """["alt", "shift", "z"] -> (MOD_ALT|MOD_SHIFT, VK_Z) for RegisterHotKey."""
    mods = 0
    for k in keys[:-1]:
        if k.lower() not in _MOD_FLAGS:
            raise ValueError(f"{k!r} is not a modifier (use ctrl, alt, shift or win)")
        mods |= _MOD_FLAGS[k.lower()]
    return mods, min(parse_key(keys[-1]))


class HotkeyListener:
    IDLE, HOLD, LOCKED = "idle", "hold", "locked"

    def __init__(self, chord: list[str], lock_key: str, on_event: Callable[[str], None], min_hold_ms: int = 250,
                 shortcuts: dict[str, list[str]] | None = None):
        self.chord = [parse_key(k) for k in chord]
        self.chord_vks = frozenset().union(*self.chord)
        self.lock_vks = parse_key(lock_key)
        self.uses_win = bool(self.chord_vks & _WIN_VKS)
        self.on_event = on_event
        self.min_hold = min_hold_ms / 1000
        self.state = self.IDLE
        self.pressed: set[int] = set()
        self.chord_was = False
        self.start_t = 0.0
        self._thread_id = None
        self._hook = None
        self._proc = w.HOOKPROC(self._hook_proc)  # keep a reference so it isn't GC'd
        self.shortcuts = {name: parse_shortcut(keys) for name, keys in (shortcuts or {}).items() if keys}
        self.shortcut_conflicts: list[str] = []  # names Windows refused (already taken by another app)

    # -- public -------------------------------------------------------------
    def start(self) -> None:
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), name="hotkey-hook", daemon=True)
        self._thread.start()
        ready.wait(5)
        if not self._hook:
            raise OSError("Failed to install keyboard hook")

    def stop(self) -> None:
        if self._thread_id:
            w.user32.PostThreadMessageW(self._thread_id, w.WM_QUIT, 0, 0)
            self._thread.join(2)  # so a replacement listener can re-register the same shortcuts

    def force_idle(self) -> None:
        """Called by the app when it ends a recording on its own (e.g. max length)."""
        self.state = self.IDLE

    # -- hook thread --------------------------------------------------------
    def _run(self, ready: threading.Event) -> None:
        self._thread_id = w.kernel32.GetCurrentThreadId()
        self._hook = w.user32.SetWindowsHookExW(w.WH_KEYBOARD_LL, self._proc, w.kernel32.GetModuleHandleW(None), 0)
        ids = {}
        for i, (name, (mods, vk)) in enumerate(self.shortcuts.items(), start=1):
            if w.user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
                ids[i] = name
            else:
                self.shortcut_conflicts.append(name)
        ready.set()
        msg = wintypes.MSG()
        while w.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in ids:
                self._emit(ids[msg.wParam])
        for i in ids:
            w.user32.UnregisterHotKey(None, i)
        w.user32.UnhookWindowsHookEx(self._hook)

    def _emit(self, ev: str) -> None:
        # on_event must not block: Windows silently removes hooks that take too long.
        self.on_event(ev)

    def _mask_win(self) -> None:
        if self.uses_win:
            w.send_keys((w.VK_MASK, False), (w.VK_MASK, True))

    def _prune_stale(self, current: int) -> None:
        # Key-ups can be missed (UAC prompt, lock screen); trust the async state for the rest.
        for vk in list(self.pressed):
            if vk != current and not w.is_down(vk):
                self.pressed.discard(vk)

    def _hook_proc(self, n_code, w_param, l_param):
        swallow = False
        if n_code == 0:
            kb = ctypes.cast(l_param, ctypes.POINTER(w.KBDLLHOOKSTRUCT)).contents
            if not kb.flags & w.LLKHF_INJECTED:
                down = w_param in (w.WM_KEYDOWN, w.WM_SYSKEYDOWN)
                try:
                    swallow = self._on_key(kb.vkCode, down)
                except Exception:  # never let an exception escape a hook
                    swallow = False
        if swallow:
            return 1
        return w.user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _on_key(self, vk: int, down: bool) -> bool:
        if down:
            self._prune_stale(vk)
            self.pressed.add(vk)
        else:
            self.pressed.discard(vk)
        chord_now = all(spec & self.pressed for spec in self.chord)
        rising = chord_now and not self.chord_was
        self.chord_was = chord_now
        swallow = False

        if self.state == self.IDLE:
            if down and rising:
                self.state = self.HOLD
                self.start_t = time.monotonic()
                self._mask_win()
                self._emit("start")
        elif self.state == self.HOLD:
            if down and vk in self.lock_vks:
                self.state = self.LOCKED
                self._emit("lock")
                swallow = True
            elif down and vk == VK_ESCAPE:
                self.state = self.IDLE
                self._emit("cancel")
                swallow = True
            elif down and vk not in self.chord_vks:
                self.state = self.IDLE
                self._emit("cancel")
            elif not down and not chord_now:
                self.state = self.IDLE
                held = time.monotonic() - self.start_t
                self._emit("stop" if held >= self.min_hold else "cancel")
        elif self.state == self.LOCKED:
            if down and vk == VK_ESCAPE:
                self.state = self.IDLE
                self._emit("cancel")
                swallow = True
            elif down and rising:
                self.state = self.IDLE
                self._mask_win()
                self._emit("stop")
        return swallow

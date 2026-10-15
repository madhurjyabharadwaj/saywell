"""Insert text into the focused app: clipboard swap + synthetic Ctrl+V.

Same strategy as Wispr's Windows helper (OpenClipboard/SetClipboardData,
SendInput, RestoreOriginalClipboard, optional Shift+Insert): snapshot the
clipboard, put our text on it, paste, then put the user's clipboard back.
"""
import ctypes
import time

from . import win32 as w

# Handle-based (non-HGLOBAL) formats can't be copied byte-for-byte; skip them.
_SKIP_FORMATS = {2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E}
_MODIFIERS = (w.VK_LWIN, w.VK_RWIN, 0xA4, 0xA5, 0xA0, 0xA1)  # win, alt, shift


def _open_clipboard(retries: int = 20) -> bool:
    for _ in range(retries):
        if w.user32.OpenClipboard(None):
            return True
        time.sleep(0.02)
    return False


def _hglobal_from_bytes(data: bytes):
    h = w.kernel32.GlobalAlloc(w.GMEM_MOVEABLE, max(len(data), 1))
    p = w.kernel32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    w.kernel32.GlobalUnlock(h)
    return h


def snapshot() -> list[tuple[int, bytes]]:
    saved = []
    if not _open_clipboard():
        return saved
    try:
        fmt = 0
        while True:
            fmt = w.user32.EnumClipboardFormats(fmt)
            if not fmt:
                break
            if fmt in _SKIP_FORMATS:
                continue
            h = w.user32.GetClipboardData(fmt)
            if not h:
                continue
            size = w.kernel32.GlobalSize(h)
            p = w.kernel32.GlobalLock(h)
            if not p:
                continue
            try:
                saved.append((fmt, ctypes.string_at(p, size)))
            finally:
                w.kernel32.GlobalUnlock(h)
    finally:
        w.user32.CloseClipboard()
    return saved


def _set(formats: list[tuple[int, bytes]]) -> None:
    if not _open_clipboard():
        raise OSError("Could not open clipboard")
    try:
        w.user32.EmptyClipboard()
        for fmt, data in formats:
            w.user32.SetClipboardData(fmt, _hglobal_from_bytes(data))
    finally:
        w.user32.CloseClipboard()


def _text_formats(text: str) -> list[tuple[int, bytes]]:
    fmts = [(w.CF_UNICODETEXT, (text + "\0").encode("utf-16-le"))]
    # Keep dictations out of Win+V clipboard history, cloud sync and clipboard managers.
    zero = (0).to_bytes(4, "little")
    for name in ("ExcludeClipboardContentFromMonitorProcessing", "CanIncludeInClipboardHistory",
                 "CanUploadToCloudClipboard"):
        fmts.append((w.user32.RegisterClipboardFormatW(name), zero))
    return fmts


def wait_for_modifiers_released(timeout: float = 2.0) -> None:
    # If Win is still held, Ctrl+V becomes Win+Ctrl+V; wait for the user to let go.
    end = time.monotonic() + timeout
    while time.monotonic() < end and any(w.is_down(vk) for vk in _MODIFIERS):
        time.sleep(0.01)


def paste_text(text: str, use_shift_insert: bool = False, restore: bool = True, restore_delay: float = 0.3) -> None:
    saved = snapshot() if restore else []
    _set(_text_formats(text))
    seq_after_set = w.user32.GetClipboardSequenceNumber()
    wait_for_modifiers_released()
    if use_shift_insert:
        w.send_chord(w.VK_SHIFT, w.VK_INSERT)
    else:
        w.send_chord(w.VK_CONTROL, w.VK_V)
    if not restore:
        return
    time.sleep(restore_delay)  # target apps read the clipboard asynchronously
    # Only restore if nobody else wrote to the clipboard in the meantime.
    if w.user32.GetClipboardSequenceNumber() == seq_after_set:
        if saved:
            _set(saved)
        elif _open_clipboard():
            w.user32.EmptyClipboard()
            w.user32.CloseClipboard()

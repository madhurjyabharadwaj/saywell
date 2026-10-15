"""Capture what the user is dictating into: foreground app + focused text field.

This context (app name, textbox before/after/selected text, capped at 500 chars)
goes with each request so the formatter can match casing, spacing and style.
We read it through UI Automation.
"""
import ctypes
import os
from dataclasses import dataclass, field

from . import win32 as w

MAX_TEXTBOX_CHARS = 500

UIA_ValuePatternId = 10002
UIA_TextPatternId = 10014
TPRE_Start, TPRE_End = 0, 1


@dataclass
class AppContext:
    exe: str = ""
    title: str = ""
    window_class: str = ""
    before_text: str = ""
    after_text: str = ""
    selected_text: str = ""
    is_password: bool = False
    has_textbox: bool = False
    errors: list[str] = field(default_factory=list)


def _foreground(ctx: AppContext) -> None:
    hwnd = w.user32.GetForegroundWindow()
    if not hwnd:
        return
    buf = ctypes.create_unicode_buffer(512)
    w.user32.GetWindowTextW(hwnd, buf, 512)
    ctx.title = buf.value
    w.user32.GetClassNameW(hwnd, buf, 512)
    ctx.window_class = buf.value
    pid = w.wintypes.DWORD()
    w.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = w.kernel32.OpenProcess(w.PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if h:
        try:
            size = w.wintypes.DWORD(1024)
            path = ctypes.create_unicode_buffer(1024)
            if w.kernel32.QueryFullProcessImageNameW(h, 0, path, ctypes.byref(size)):
                ctx.exe = os.path.basename(path.value)
        finally:
            w.kernel32.CloseHandle(h)


_uia = None
_UIA = None


def _automation():
    global _uia, _UIA
    if _uia is None:
        import comtypes.client
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA
        _UIA = UIA
        _uia = comtypes.client.CreateObject(UIA.CUIAutomation, interface=UIA.IUIAutomation)
    return _uia, _UIA


def _textbox(ctx: AppContext) -> None:
    uia, UIA = _automation()
    el = uia.GetFocusedElement()
    if el is None:
        return
    ctx.is_password = bool(el.CurrentIsPassword)
    if ctx.is_password:
        return  # never read secrets
    tp = el.GetCurrentPattern(UIA_TextPatternId)
    if tp:
        text = tp.QueryInterface(UIA.IUIAutomationTextPattern)
        doc = text.DocumentRange
        sels = text.GetSelection()
        ctx.has_textbox = True
        if sels and sels.Length > 0:
            sel = sels.GetElement(0)
            ctx.selected_text = sel.GetText(MAX_TEXTBOX_CHARS)
            before = doc.Clone()
            before.MoveEndpointByRange(TPRE_End, sel, TPRE_Start)
            after = doc.Clone()
            after.MoveEndpointByRange(TPRE_Start, sel, TPRE_End)
            ctx.before_text = before.GetText(-1)[-MAX_TEXTBOX_CHARS:]
            ctx.after_text = after.GetText(MAX_TEXTBOX_CHARS)
        else:
            ctx.before_text = doc.GetText(-1)[-MAX_TEXTBOX_CHARS:]
        return
    vp = el.GetCurrentPattern(UIA_ValuePatternId)
    if vp:
        value = vp.QueryInterface(UIA.IUIAutomationValuePattern)
        if not value.CurrentIsReadOnly:
            ctx.has_textbox = True
            # No caret info from ValuePattern; assume the caret is at the end.
            ctx.before_text = (value.CurrentValue or "")[-MAX_TEXTBOX_CHARS:]


def capture() -> AppContext:
    """Call from a COM-initialized thread. Every step is best effort."""
    ctx = AppContext()
    try:
        _foreground(ctx)
    except Exception as e:
        ctx.errors.append(f"foreground: {e}")
    try:
        _textbox(ctx)
    except Exception as e:
        ctx.errors.append(f"uia: {e}")
    return ctx

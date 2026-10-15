"""API keys at rest, encrypted with Windows DPAPI (tied to the current Windows user).

settings.json only ever holds the encrypted blob, so copying the file to another
account or machine doesn't leak the key.
"""
import base64
import ctypes
import os
from ctypes import wintypes

_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_ENTROPY = b"Saywell API key"


class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


_crypt32.CryptProtectData.argtypes = [ctypes.POINTER(_BLOB), wintypes.LPCWSTR, ctypes.POINTER(_BLOB),
                                      ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB)]
_crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(_BLOB), ctypes.c_void_p, ctypes.POINTER(_BLOB),
                                        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB)]
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _blob(data: bytes) -> _BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _call(fn, data: bytes, *mid) -> bytes:
    out = _BLOB()
    ent = _blob(_ENTROPY)
    if not fn(ctypes.byref(_blob(data)), *mid, ctypes.byref(ent), None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
        raise OSError(ctypes.get_last_error(), "DPAPI call failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        _kernel32.LocalFree(out.pbData)


def protect(plain: str) -> str:
    if not plain:
        return ""
    return "dpapi:" + base64.b64encode(_call(_crypt32.CryptProtectData, plain.encode(), "Saywell")).decode()


def unprotect(stored: str) -> str:
    if not stored:
        return ""
    if not stored.startswith("dpapi:"):
        return stored  # hand-edited plain key in settings.json
    try:
        return _call(_crypt32.CryptUnprotectData, base64.b64decode(stored[6:]), None).decode()
    except OSError:
        return ""  # encrypted by another Windows user


def get_api_key(section: dict) -> str:
    """A key saved in Settings wins; otherwise fall back to the configured environment variable."""
    return unprotect(section.get("api_key", "")) or os.environ.get(section.get("api_key_env", ""), "")

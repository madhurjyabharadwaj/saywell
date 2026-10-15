"""Settings: defaults, load/save, and where Saywell keeps its files.

Everything lives in %APPDATA%\\Saywell so the packaged .exe and a source checkout
behave the same:
  settings.json   user settings (API keys DPAPI-encrypted)
  history.db      every dictation
  audio\\          recordings kept until a failed dictation is retried
  saywell.log     output when running without a console
"""
import json
import os
import shutil
import sys

APP_NAME = "Saywell"
VERSION = "0.2.0"

DEFAULT_CONFIG = {
    "hotkey": ["ctrl", "win"],
    "lock_key": "space",
    "paste_last_hotkey": ["alt", "shift", "z"],
    "min_hold_ms": 250,
    "max_recording_s": 360,
    "silence_rms": 0.004,
    "sounds": True,
    "show_bar": True,
    "paste_with_shift_insert": False,
    "restore_clipboard": True,
    "microphone": None,
    "user_name": "",
    "dictionary": [],
    "asr": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "api_key": "",
        "model": "whisper-large-v3-turbo",
        "language": "",
        "timeout_s": 30,
    },
    "cleanup": {
        "enabled": True,
        "provider": "openai_compatible",    # or "anthropic" (Claude)
        "model": "openai/gpt-oss-120b",
        "effort": "low",
        "base_url": "https://api.groq.com/openai/v1",  # openai_compatible only
        "api_key_env": "GROQ_API_KEY",
        "api_key": "",
        "style": "",
        "timeout_s": 20,
    },
}


def data_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME)


def settings_path() -> str:
    return os.path.join(data_dir(), "settings.json")


def source_root() -> str | None:
    """The repo folder when running from source; None inside the packaged .exe."""
    if getattr(sys, "frozen", False):
        return None
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def asset(name: str) -> str:
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    if getattr(sys, "_MEIPASS", None):
        return os.path.join(base, "saywell", "assets", name)
    return os.path.join(base, "assets", name)


def load_config(path: str) -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def save_config(cfg: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, path)


def migrate_from_flowlite() -> None:
    """One-time carry-over from the FlowLite days: repo config.json and the old history."""
    d = data_dir()
    os.makedirs(d, exist_ok=True)
    root = source_root()
    legacy_cfg = os.path.join(root, "config.json") if root else None
    if not os.path.exists(settings_path()) and legacy_cfg and os.path.exists(legacy_cfg):
        save_config(load_config(legacy_cfg), settings_path())
    old_db = os.path.join(os.path.dirname(d), "FlowLite", "history.db")
    new_db = os.path.join(d, "history.db")
    if not os.path.exists(new_db) and os.path.exists(old_db):
        shutil.copy2(old_db, new_db)

"""Offline checks that don't need a microphone, speech or API keys."""
import time

import os
import sqlite3

import numpy as np

from saywell import app, asr, config, context, history, hotkey, inserter, keystore


def make_listener():
    events = []
    hk = hotkey.HotkeyListener(["ctrl", "win"], "space", events.append, min_hold_ms=50)
    hk._mask_win = lambda: events.append("mask")  # don't inject real keys in tests
    hk._prune_stale = lambda vk: None             # don't consult physical key state
    return hk, events


CTRL, WIN, SPACE, ESC, A = 0xA2, 0x5B, 0x20, 0x1B, 0x41


def test_hold_to_talk():
    hk, ev = make_listener()
    hk._on_key(CTRL, True)
    assert ev == []
    hk._on_key(WIN, True)
    assert ev == ["mask", "start"]
    hk._on_key(WIN, True)  # auto-repeat must not retrigger
    time.sleep(0.06)
    hk._on_key(WIN, False)
    assert ev == ["mask", "start", "stop"]


def test_short_tap_cancels():
    hk, ev = make_listener()
    hk._on_key(CTRL, True); hk._on_key(WIN, True); hk._on_key(CTRL, False)
    assert ev[-1] == "cancel"


def test_hands_free_lock_and_stop():
    hk, ev = make_listener()
    hk._on_key(CTRL, True); hk._on_key(WIN, True)
    assert hk._on_key(SPACE, True) is True        # space swallowed
    hk._on_key(SPACE, False); hk._on_key(WIN, False); hk._on_key(CTRL, False)
    assert ev == ["mask", "start", "lock"]         # still recording after release
    hk._on_key(CTRL, True); hk._on_key(WIN, True)
    assert ev[-1] == "stop"


def test_escape_and_other_key_cancel():
    hk, ev = make_listener()
    hk._on_key(CTRL, True); hk._on_key(WIN, True)
    assert hk._on_key(ESC, True) is True
    assert ev[-1] == "cancel"
    hk, ev = make_listener()
    hk._on_key(CTRL, True); hk._on_key(WIN, True)
    assert hk._on_key(A, True) is False            # Ctrl+Win+A belongs to someone else
    assert ev[-1] == "cancel"


def test_smart_space():
    c = context.AppContext(before_text="Hello")
    assert app.smart_space("world", c) == " world"
    assert app.smart_space(", world", c) == ", world"
    assert app.smart_space("world", context.AppContext(before_text="Hello ")) == "world"
    assert app.smart_space("world", context.AppContext()) == "world"


def test_clipboard_roundtrip_restores_user_clipboard():
    original = inserter.snapshot()
    try:
        inserter._set(inserter._text_formats("saywell-test"))
        snap = dict(inserter.snapshot())
        assert snap[13].decode("utf-16-le").rstrip("\0") == "saywell-test"
    finally:
        if original:
            inserter._set(original)
    if original:
        assert dict(inserter.snapshot()).get(13) == dict(original).get(13)


def test_context_capture_runs():
    ctx = context.capture()
    assert isinstance(ctx.exe, str)
    print("context:", ctx.exe, repr(ctx.title[:40]), "textbox:", ctx.has_textbox, ctx.errors)


def test_config_merge(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"cleanup": {"model": "claude-haiku-5-5"}, "dictionary": ["X"]}')
    cfg = config.load_config(str(p))
    assert cfg["cleanup"]["model"] == "claude-haiku-5-5"
    assert cfg["cleanup"]["effort"] == "low"
    assert cfg["dictionary"] == ["X"]


def test_paste_last_shortcut_parsing():
    assert hotkey.parse_shortcut(["alt", "shift", "z"]) == (0x1 | 0x4, ord("Z"))
    assert hotkey.parse_shortcut(["ctrl", "alt", "v"]) == (0x2 | 0x1, ord("V"))


def test_api_key_is_encrypted_at_rest(monkeypatch):
    enc = keystore.protect("gsk_secret123")
    assert enc.startswith("dpapi:") and "gsk_secret123" not in enc
    assert keystore.unprotect(enc) == "gsk_secret123"
    monkeypatch.setenv("SAYWELL_TEST_KEY", "from-env")
    assert keystore.get_api_key({"api_key": enc, "api_key_env": "SAYWELL_TEST_KEY"}) == "gsk_secret123"
    assert keystore.get_api_key({"api_key": "", "api_key_env": "SAYWELL_TEST_KEY"}) == "from-env"


def test_history_upgrades_old_flowlite_db(tmp_path):
    path = str(tmp_path / "h.db")
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE history (id INTEGER PRIMARY KEY, ts REAL NOT NULL, app TEXT, window_title TEXT, "
                "raw_text TEXT, final_text TEXT, status TEXT, audio_ms INTEGER, asr_ms INTEGER, llm_ms INTEGER)")
    old.execute("INSERT INTO history (ts, final_text, status) VALUES (1, 'hello there', 'formatted')")
    old.commit()
    old.close()
    h = history.History(path)
    rid = h.add(final_text="", status="failed", audio_path="x.wav", error="offline")
    assert h.get(rid)["audio_path"] == "x.wav"
    assert h.last_text() == "hello there"  # failed rows never get pasted
    assert [r["final_text"] for r in h.recent("hello")] == ["hello there"]
    assert h.recent("100%") == []
    assert h.stats() == (1, 2)


class _FakeOverlay:
    def __init__(self):
        self.flashes = []

    def set_mode(self, m): pass
    def set_locked(self, v): pass
    def flash(self, t): self.flashes.append(t)


def test_failed_dictation_is_kept_and_retryable(tmp_path, monkeypatch):
    cfg = config.load_config(str(tmp_path / "none.json"))
    cfg["cleanup"]["enabled"] = False
    ov = _FakeOverlay()
    eng = app.App(cfg, str(tmp_path), ov)
    speech = (np.sin(np.linspace(0, 2000, 16000)) * 8000).astype(np.int16)

    def offline(*a, **k):
        raise asr.ASRError("ASR network error: offline")
    monkeypatch.setattr(asr, "transcribe", offline)
    s = app.Session(started=0)
    s.ctx_ready.set()
    eng._process(s, speech, peak=0.2)
    row = eng.history.recent()[0]
    assert row["status"] == "failed" and os.path.exists(row["audio_path"])
    assert ov.flashes[-1].startswith("Saved")

    monkeypatch.setattr(asr, "transcribe", lambda *a, **k: "back online")
    assert eng.retry(row["id"]) == "back online"
    row = eng.history.get(row["id"])
    assert row["status"] == "raw" and row["final_text"] == "back online" and row["audio_path"] is None

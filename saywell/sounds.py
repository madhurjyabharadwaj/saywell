"""Short start/stop chirps, synthesized so no audio assets are needed."""
import io
import threading
import wave
import winsound

import numpy as np


def _chirp(f0: float, f1: float, ms: int = 70, vol: float = 0.18) -> bytes:
    sr = 22050
    t = np.linspace(0, ms / 1000, int(sr * ms / 1000), endpoint=False)
    freq = np.linspace(f0, f1, t.size)
    wave_ = np.sin(2 * np.pi * np.cumsum(freq) / sr)
    env = np.minimum(1, np.minimum(t / 0.008, (t[-1] - t) / 0.03))
    pcm = (wave_ * env * vol * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


START = _chirp(660, 990)
STOP = _chirp(880, 560)


def play(sound: bytes, enabled: bool = True) -> None:
    if enabled:
        # winsound can't combine SND_MEMORY with SND_ASYNC, so play on a thread.
        threading.Thread(target=winsound.PlaySound, args=(sound, winsound.SND_MEMORY), daemon=True).start()

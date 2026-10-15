"""Microphone capture: 16 kHz mono int16, with a live level for the overlay."""
import io
import threading
import wave

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000


class Recorder:
    def __init__(self, device=None):
        self.device = device
        self._stream = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self.level = 0.0  # smoothed RMS 0..1, read by the overlay
        self.peak = 0.0

    def start(self) -> None:
        with self._lock:
            self._chunks = []
        self.level = self.peak = 0.0
        self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                      device=self.device, blocksize=SAMPLE_RATE // 50, callback=self._cb)
        self._stream.start()

    def _cb(self, indata, frames, t, status) -> None:
        block = indata[:, 0].copy()
        with self._lock:
            self._chunks.append(block)
        rms = float(np.sqrt(np.mean((block.astype(np.float32) / 32768.0) ** 2)))
        self.peak = max(self.peak, rms)
        self.level = 0.6 * self.level + 0.4 * rms

    def stop(self) -> np.ndarray:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self.level = 0.0
        with self._lock:
            return np.concatenate(self._chunks) if self._chunks else np.zeros(0, dtype=np.int16)


def to_wav(samples: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(samples.astype(np.int16).tobytes())
    return buf.getvalue()

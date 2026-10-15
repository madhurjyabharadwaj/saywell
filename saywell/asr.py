"""Speech-to-text via any OpenAI-compatible /audio/transcriptions endpoint
(Groq, OpenAI, a local faster-whisper server, ...)."""
import json
import urllib.error
import urllib.request
import uuid

from .keystore import get_api_key


class ASRError(RuntimeError):
    pass


def _multipart(fields: dict[str, str], file_bytes: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
                  f"Content-Type: audio/wav\r\n\r\n").encode() + file_bytes + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def transcribe(wav: bytes, cfg: dict, prompt: str = "") -> str:
    key = get_api_key(cfg)
    if not key:
        raise ASRError("No API key - add one in Saywell > Settings")
    fields = {"model": cfg["model"], "response_format": "json", "temperature": "0"}
    if prompt:
        fields["prompt"] = prompt[:800]  # Whisper-style prompts are capped at ~224 tokens
    if cfg.get("language"):
        fields["language"] = cfg["language"]
    body, ctype = _multipart(fields, wav)
    req = urllib.request.Request(cfg["base_url"].rstrip("/") + "/audio/transcriptions", data=body,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": ctype,
                                          "User-Agent": "Saywell/0.2"})  # Cloudflare blocks urllib's default UA
    try:
        with urllib.request.urlopen(req, timeout=cfg.get("timeout_s", 30)) as r:
            return json.load(r).get("text", "").strip()
    except urllib.error.HTTPError as e:
        raise ASRError(f"ASR HTTP {e.code}: {e.read()[:300]!r}") from e
    except urllib.error.URLError as e:
        raise ASRError(f"ASR network error: {e.reason}") from e

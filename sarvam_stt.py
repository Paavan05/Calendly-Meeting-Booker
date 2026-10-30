import os

import requests

URL = "https://api.sarvam.ai/speech-to-text"


def transcribe(audio_bytes: bytes) -> str:
    key = os.getenv("SARVAM_API_KEY")
    if not key:
        raise RuntimeError("SARVAM_API_KEY is missing in .env")
    r = requests.post(
        URL,
        headers={"api-subscription-key": key},
        files={"file": ("speech.wav", audio_bytes, "audio/wav")},
        data={"model": "saarika:v2.5", "language_code": "unknown"},  # auto-detect Hindi/English
        timeout=60,
    )
    if not r.ok:
        raise RuntimeError(f"Sarvam {r.status_code}: {r.text[:200]}")
    return r.json().get("transcript", "").strip()
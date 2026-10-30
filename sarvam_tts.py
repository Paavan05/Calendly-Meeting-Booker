import base64
import os

import requests

URL = "https://api.sarvam.ai/text-to-speech"


def tts(text: str, lang: str = "en-IN") -> bytes:
    key = os.getenv("SARVAM_API_KEY")
    if not key:
        raise RuntimeError("SARVAM_API_KEY is missing in .env")
    r = requests.post(
        URL,
        headers={"api-subscription-key": key, "Content-Type": "application/json"},
        json={
            "text": text,
            "target_language_code": lang,  # "en-IN" or "hi-IN"
            "model": os.getenv("SARVAM_TTS_MODEL", "bulbul:v3"),
            "speaker": os.getenv("SARVAM_TTS_SPEAKER", "shubh"),
        },
        timeout=60,
    )
    if not r.ok:
        raise RuntimeError(f"Sarvam TTS {r.status_code}: {r.text[:200]}")
    return base64.b64decode("".join(r.json()["audios"]))
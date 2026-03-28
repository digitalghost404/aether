from __future__ import annotations

import sys

import numpy as np


class SpeechToText:
    def __init__(self, model_size: str = "small"):
        self._model_size = model_size
        self._model = None

    def _ensure_model(self) -> bool:
        if self._model is not None:
            return True
        try:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self._model_size, device="cuda", compute_type="float16")
            print(f"[aether] VOX: whisper model loaded ({self._model_size})", file=sys.stderr)
            return True
        except Exception as e:
            print(f"[aether] VOX: whisper model failed: {e}", file=sys.stderr)
            return False

    def transcribe(self, audio: np.ndarray, sr: int = 16000) -> str | None:
        if not self._ensure_model():
            return None
        try:
            segments, _ = self._model.transcribe(audio, language="en")
            text = " ".join(seg.text.strip() for seg in segments).strip()
            return text if text else None
        except Exception as e:
            print(f"[aether] VOX: transcription failed: {e}", file=sys.stderr)
            return None

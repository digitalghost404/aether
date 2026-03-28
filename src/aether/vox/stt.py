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
        from faster_whisper import WhisperModel
        # Try GPU first, fall back to CPU. Test with a short silent clip
        # because WhisperModel constructor may succeed but transcribe() fails
        # if CUDA libraries are missing.
        test_audio = np.zeros(16000, dtype=np.float32)  # 1s silence
        for device, compute in [("cuda", "float16"), ("cpu", "int8")]:
            try:
                model = WhisperModel(self._model_size, device=device, compute_type=compute)
                # Smoke test — catches missing libcublas etc.
                list(model.transcribe(test_audio, language="en")[0])
                self._model = model
                print(f"[aether] VOX: whisper model loaded ({self._model_size}, {device})", file=sys.stderr)
                return True
            except Exception as e:
                print(f"[aether] VOX: whisper {device} failed: {e}", file=sys.stderr)
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

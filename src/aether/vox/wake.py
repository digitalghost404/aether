from __future__ import annotations

import sys

import numpy as np


class WakeWordDetector:
    def __init__(self, wake_word: str = "aether"):
        self._wake_word = wake_word
        self._model = None
        self._threshold = 0.5

    def load(self) -> bool:
        try:
            from openwakeword.model import Model
            # Load default models — wake_word selects which model to check in detect()
            self._model = Model()
            available = list(self._model.models.keys())
            if self._wake_word not in available:
                print(f"[aether] VOX: wake word '{self._wake_word}' not in available models: {available}", file=sys.stderr)
                print(f"[aether] VOX: using first available: {available[0]}", file=sys.stderr)
                self._wake_word = available[0]
            print(f"[aether] VOX: wake word model loaded ({self._wake_word})", file=sys.stderr)
            return True
        except Exception as e:
            print(f"[aether] VOX: wake word model failed to load: {e}", file=sys.stderr)
            return False

    def detect(self, audio_chunk: np.ndarray) -> bool:
        if self._model is None:
            return False
        int16_audio = (audio_chunk * 32767).astype(np.int16)
        prediction = self._model.predict(int16_audio)
        for key, score in prediction.items():
            if score >= self._threshold:
                self._model.reset()
                return True
        return False

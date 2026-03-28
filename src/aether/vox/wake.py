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
            self._model = Model(
                wakeword_models=[self._wake_word],
                inference_framework="onnx",
            )
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

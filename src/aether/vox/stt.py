from __future__ import annotations

import ctypes
import sys
from pathlib import Path

import numpy as np

# Pre-load pip-installed NVIDIA libraries so ctranslate2's dlopen can find them.
# The pip nvidia-cublas-cu12 / nvidia-cudnn-cu12 packages install .so files under
# site-packages/nvidia/*/lib/ which aren't on the default library search path.
def _preload_nvidia_libs() -> None:
    import importlib.util
    spec = importlib.util.find_spec("nvidia")
    if spec is None or spec.submodule_search_locations is None:
        return
    nvidia_root = Path(list(spec.submodule_search_locations)[0])
    for lib_name in ["cublas/lib/libcublas.so.12", "cudnn/lib/libcudnn.so.9",
                     "cuda_nvrtc/lib/libnvrtc.so.12"]:
        lib_path = nvidia_root / lib_name
        if lib_path.exists():
            try:
                ctypes.CDLL(str(lib_path), mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass

_preload_nvidia_libs()


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

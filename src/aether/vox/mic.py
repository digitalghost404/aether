from __future__ import annotations

import asyncio
import subprocess
import sys

import numpy as np


SAMPLE_RATE = 16000
CHUNK_DURATION = 0.5
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_DURATION)


class MicCapture:
    def __init__(self, source: str):
        self._source = source
        self._proc: subprocess.Popen | None = None

    async def start(self) -> bool:
        try:
            self._proc = subprocess.Popen(
                [
                    "pw-cat", "--record",
                    "--target", self._source,
                    "--format", "f32",
                    "--rate", str(SAMPLE_RATE),
                    "--channels", "1",
                    "-",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            print(f"[aether] VOX: mic capture started ({self._source})", file=sys.stderr)
            return True
        except FileNotFoundError:
            print("[aether] VOX: pw-cat not found", file=sys.stderr)
            return False
        except Exception as e:
            print(f"[aether] VOX: mic capture failed: {e}", file=sys.stderr)
            return False

    async def read_chunk(self) -> np.ndarray | None:
        if self._proc is None or self._proc.stdout is None:
            return None
        raw = await asyncio.to_thread(
            self._proc.stdout.read, CHUNK_SAMPLES * 4
        )
        if not raw:
            return None
        samples = np.frombuffer(raw, dtype=np.float32)
        clean = samples[np.isfinite(samples)]
        return clean if len(clean) > 0 else None

    async def read_seconds(self, seconds: float, silence_timeout: float = 1.5) -> np.ndarray:
        chunks = []
        total_samples = int(SAMPLE_RATE * seconds)
        collected = 0
        silence_samples = 0
        silence_limit = int(SAMPLE_RATE * silence_timeout)

        while collected < total_samples:
            chunk = await self.read_chunk()
            if chunk is None:
                break
            chunks.append(chunk)
            collected += len(chunk)
            energy = float(np.sqrt(np.mean(chunk ** 2)))
            if energy < 0.005:
                silence_samples += len(chunk)
                if silence_samples >= silence_limit:
                    break
            else:
                silence_samples = 0

        return np.concatenate(chunks) if chunks else np.array([], dtype=np.float32)

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            self._proc.wait()
        self._proc = None

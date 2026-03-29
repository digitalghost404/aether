from __future__ import annotations

import asyncio
import sys
import time
from typing import Callable

import cv2
import numpy as np


class Camera:
    def __init__(self, camera_index: int = 0, frame_interval_ms: int = 333):
        self._camera_index = camera_index
        self._frame_interval = frame_interval_ms / 1000.0
        self._cap: cv2.VideoCapture | None = None

    def _open(self) -> bool:
        if self._cap is not None and self._cap.isOpened():
            return True
        self._cap = cv2.VideoCapture(self._camera_index)
        if not self._cap.isOpened():
            self._cap = None
            return False
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        return True

    def _read_frame(self) -> np.ndarray | None:
        if self._cap is None:
            return None
        ret, frame = self._cap.read()
        if not ret:
            return None
        return frame

    async def run(self, process_frame: Callable[[np.ndarray], None]) -> None:
        retry_delay = 5.0

        while True:
            if not self._open():
                print(
                    f"[aether] Camera {self._camera_index} not available. Retrying in {retry_delay}s...",
                    file=sys.stderr,
                )
                await asyncio.sleep(retry_delay)
                continue

            frame = await asyncio.to_thread(self._read_frame)

            if frame is None:
                print("[aether] Camera read failed. Reconnecting...", file=sys.stderr)
                self._cap = None
                await asyncio.sleep(retry_delay)
                continue

            process_frame(frame)
            await asyncio.sleep(self._frame_interval)

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

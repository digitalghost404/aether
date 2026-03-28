from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from dataclasses import dataclass

import numpy as np

from aether.config import PartyConfig
from aether.lighting.ramp import ColorState


SAMPLE_RATE = 22050
CHUNK_DURATION = 0.05  # 50ms chunks for beat-resolution detection
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_DURATION)


@dataclass
class AnalysisResult:
    energy: float
    is_onset: bool
    bpm: float | None


class BeatAnalyzer:
    def __init__(self, sr: int = SAMPLE_RATE):
        self._sr = sr
        self._energy_history: list[float] = []
        self._onset_threshold = 1.5
        self._audio_buffer: list[np.ndarray] = []

    def feed(self, samples: np.ndarray) -> AnalysisResult:
        import librosa

        # Filter out NaN/Inf from PipeWire stream (first chunk often has garbage)
        clean = samples[np.isfinite(samples)]
        if len(clean) == 0:
            return AnalysisResult(energy=0.0, is_onset=False, bpm=None)

        energy = float(np.sqrt(np.mean(clean ** 2)))
        self._energy_history.append(energy)
        if len(self._energy_history) > 30:
            self._energy_history.pop(0)

        avg = np.mean(self._energy_history) if self._energy_history else 0.0
        is_onset = energy > avg * self._onset_threshold and energy > 0.01

        self._audio_buffer.append(clean)
        bpm = None
        total_samples = sum(len(b) for b in self._audio_buffer)
        if total_samples >= self._sr * 4:
            full_audio = np.concatenate(self._audio_buffer)
            try:
                tempo, _ = librosa.beat.beat_track(y=full_audio, sr=self._sr)
                bpm = float(np.asarray(tempo).flat[0])
            except Exception:
                pass
            keep_samples = self._sr * 8
            if len(full_audio) > keep_samples:
                self._audio_buffer = [full_audio[-keep_samples:]]

        return AnalysisResult(energy=energy, is_onset=is_onset, bpm=bpm)


class DJMode:
    def __init__(
        self,
        config: PartyConfig,
        mixer,
        mqtt,
        cancel: asyncio.Event,
        pause: asyncio.Event,
    ):
        self._config = config
        self._mixer = mixer
        self._mqtt = mqtt
        self._cancel = cancel
        self._pause = pause
        self._analyzer = BeatAnalyzer()
        self._palette_index = 0
        self._accent_high = False
        self._beats_since_shift = 0
        self._current_base_color: tuple[int, int, int] = tuple(config.palette[0]) if config.palette else (128, 0, 255)
        self._last_sound_time = time.monotonic()

    def _next_palette_color(self) -> tuple[int, int, int]:
        palette = self._config.palette
        color = tuple(palette[self._palette_index])
        self._palette_index = (self._palette_index + 1) % len(palette)
        return color

    def _toggle_accent(self) -> int:
        self._accent_high = not self._accent_high
        if self._accent_high:
            return self._config.accent_brightness_high
        return self._config.accent_brightness_low

    def _apply_base_color(self, r: int, g: int, b: int, brightness: int = 80) -> None:
        color = ColorState(r=r, g=g, b=b, brightness=brightness)
        for zone in ("wall_left", "wall_right", "monitor", "bedroom"):
            self._mixer.submit("party", zone, color, priority=1)
        if self._config.desk_accent:
            self._mixer.submit("party", "desk", color, priority=1)
        if self._config.tower_beat_sync:
            self._mixer.submit("party", "tower", color, priority=1)
        self._mixer.resolve()

    def _apply_accent(self, brightness: int) -> None:
        r, g, b = self._current_base_color
        accent = ColorState(r=r, g=g, b=b, brightness=brightness)
        self._mixer.submit("party", self._config.accent_zone, accent, priority=1)
        if self._config.tower_beat_sync:
            self._mixer.submit("party", "tower", accent, priority=1)
        self._mixer.resolve()

    async def run(self) -> None:
        proc = None
        try:
            proc = subprocess.Popen(
                [
                    "pw-cat", "--record",
                    "--target", "@DEFAULT_AUDIO_SINK@",
                    "--format", "f32",
                    "--rate", str(SAMPLE_RATE),
                    "--channels", "1",
                    "-",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            print("[aether] PARTY: PipeWire audio tap started", file=sys.stderr)
        except FileNotFoundError:
            print("[aether] PARTY: pw-cat not found. Is PipeWire installed?", file=sys.stderr)
            return
        except Exception as e:
            print(f"[aether] PARTY: failed to start audio tap: {e}", file=sys.stderr)
            return

        r, g, b = self._current_base_color
        self._apply_base_color(r, g, b)
        self._apply_accent(self._config.accent_brightness_low)
        self._last_sound_time = time.monotonic()

        try:
            while not self._cancel.is_set():
                if self._pause.is_set():
                    await asyncio.sleep(0.5)
                    continue

                raw = await asyncio.to_thread(
                    proc.stdout.read, CHUNK_SAMPLES * 4
                )
                if not raw:
                    break

                samples = np.frombuffer(raw, dtype=np.float32)
                if len(samples) == 0:
                    continue

                result = self._analyzer.feed(samples)

                if result.energy > 0.01:
                    self._last_sound_time = time.monotonic()
                elif time.monotonic() - self._last_sound_time > self._config.silence_timeout_sec:
                    print("[aether] PARTY: silence timeout, exiting", file=sys.stderr)
                    return

                if result.is_onset:
                    br = self._toggle_accent()
                    self._apply_accent(br)
                    self._beats_since_shift += 1

                if self._beats_since_shift >= self._config.base_shift_beats:
                    self._beats_since_shift = 0
                    self._current_base_color = self._next_palette_color()
                    r, g, b = self._current_base_color
                    self._apply_base_color(r, g, b)

        finally:
            self._mixer.release_all("party")
            self._mixer.resolve()
            if proc and proc.poll() is None:
                proc.terminate()
                proc.wait()
            print("[aether] PARTY: ended", file=sys.stderr)

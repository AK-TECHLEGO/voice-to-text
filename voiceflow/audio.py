"""Microphone capture."""

from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd


class Recorder:
    """Records mono float32 audio from the microphone into memory."""

    def __init__(self, sample_rate: int = 16000, device: int | str | None = None,
                 max_duration: float = 300.0):
        self.sample_rate = sample_rate
        self.device = device
        self.max_duration = max_duration
        self._stream: sd.InputStream | None = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._peak = 0.0
        self._level = 0.0
        self._overflowed = False

    @property
    def recording(self) -> bool:
        return self._stream is not None

    @property
    def peak(self) -> float:
        """Loudest sample seen so far, 0.0-1.0. Used to warn about a dead mic."""
        return self._peak

    @property
    def level(self) -> float:
        """Smoothed loudness of the last few blocks, for the waveform display."""
        return self._level

    def _callback(self, indata, frames, time_info, status):  # noqa: ARG002
        with self._lock:
            if self._frames_recorded() >= self.max_duration * self.sample_rate:
                self._overflowed = True
                return
            self._chunks.append(indata[:, 0].copy())
            block_peak = float(np.abs(indata).max()) if frames else 0.0
            if block_peak > self._peak:
                self._peak = block_peak
            if frames:
                rms = float(np.sqrt(np.mean(np.square(indata))))
                # Attack fast so speech shows instantly, decay slowly so the
                # bars fall smoothly instead of flickering.
                self._level = max(rms, self._level * 0.75)

    def _frames_recorded(self) -> int:
        return sum(len(c) for c in self._chunks)

    def start(self) -> None:
        if self._stream is not None:
            return
        with self._lock:
            self._chunks = []
            self._peak = 0.0
            self._level = 0.0
            self._overflowed = False
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=self.device,
            blocksize=1024,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        """Stop recording and return everything captured (may be empty)."""
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()
        with self._lock:
            chunks, self._chunks = self._chunks, []
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks).astype(np.float32)

    def duration(self, audio: np.ndarray) -> float:
        return len(audio) / float(self.sample_rate)


def list_devices() -> str:
    """Human-readable table of input devices, for --list-devices."""
    lines = ["Input devices (use the number or a name fragment as \"input_device\"):", ""]
    try:
        default_in = sd.default.device[0]
    except Exception:
        default_in = None
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] < 1:
            continue
        marker = " (default)" if idx == default_in else ""
        api = sd.query_hostapis(dev["hostapi"])["name"]
        lines.append(f"  [{idx:>2}] {dev['name']}  -  {api}{marker}")
    return "\n".join(lines)

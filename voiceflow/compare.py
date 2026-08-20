"""Try every model on one recording of your own voice.

Accuracy arguments are unresolvable in the abstract - it depends on your
microphone, your accent, and the words you use. So record once, run everything
against that same audio, and read the results.

    run.bat --compare              record 8 seconds, then compare
    run.bat --compare sample.wav   reuse an earlier recording
"""

from __future__ import annotations

import time
import wave
from pathlib import Path
from typing import Any

import numpy as np

from . import config
from .audio import Recorder, normalize
from .transcribe import Transcriber

SAMPLE = config.ROOT / "sample.wav"

# Ordered smallest to largest. Ones you have not downloaded are fetched.
CANDIDATES = ["base.en", "small.en", "medium.en", "distil-large-v3"]


def _save_wav(path: Path, audio: np.ndarray, rate: int) -> None:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def _load_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0, rate


def record(cfg: dict[str, Any], seconds: float) -> np.ndarray:
    rec = Recorder(cfg["sample_rate"], cfg["input_device"], cfg["max_duration"])
    print(f"\nRecording {seconds:.0f} seconds. Speak normally, now.")
    rec.start()
    for left in range(int(seconds), 0, -1):
        print(f"  {left}... ", end="", flush=True)
        time.sleep(1.0)
    audio = rec.stop()
    print("\ndone.")
    print(f"  captured {len(audio) / cfg['sample_rate']:.1f}s, "
          f"peak level {rec.peak:.3f}")
    if rec.peak < 0.02:
        print("  NOTE: that is a very quiet recording. Move closer to the mic, or")
        print("        raise the level in Windows sound settings. Normalisation")
        print("        helps, but it cannot add detail that was never captured.")
    return audio


def run(cfg: dict[str, Any], source: str | None, seconds: float = 8.0) -> int:
    if source:
        path = Path(source)
        if not path.exists():
            print(f"no such file: {path}")
            return 1
        audio, rate = _load_wav(path)
        print(f"Using {path} ({len(audio) / rate:.1f}s)")
    else:
        audio = record(cfg, seconds)
        rate = cfg["sample_rate"]
        if len(audio) < rate:
            print("Nothing recorded. Check your microphone with --list-devices.")
            return 1
        _save_wav(SAMPLE, audio, rate)
        print(f"  saved to {SAMPLE}")
        print("  re-run against exactly this audio with:  "
              f"run.bat --compare {SAMPLE.name}")

    duration = len(audio) / rate
    raw_peak = float(np.abs(audio).max())
    print(f"\npeak before normalising {raw_peak:.3f}, "
          f"after {float(np.abs(normalize(audio)).max()):.3f}\n")

    print("=" * 72)
    for name in CANDIDATES:
        trial = dict(cfg)
        trial["model"] = name
        try:
            tr = Transcriber(trial)
            t0 = time.perf_counter()
            tr.load()
            load = time.perf_counter() - t0
            t0 = time.perf_counter()
            text = tr.transcribe(audio)
            took = time.perf_counter() - t0
        except Exception as exc:
            print(f"\n{name:<18} FAILED: {exc}")
            continue
        print(f"\n{name:<18} {took:5.1f}s  ({duration / took:4.1f}x realtime, "
              f"loaded in {load:.1f}s)")
        print(f"  {text.strip() or '(nothing recognised)'}")
    print("\n" + "=" * 72)
    print("Pick whichever line reads best, then set it in config.json:")
    print('    "model": "medium.en"')
    print("\nIf they are all wrong in the same way, it is the audio, not the model.")
    print("Try a different microphone with --list-devices, or add the words it")
    print('keeps missing to "initial_prompt" in config.json.')
    return 0

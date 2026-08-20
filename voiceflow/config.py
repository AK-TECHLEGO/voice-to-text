"""Configuration loading, with defaults written to disk on first run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config.json"

DEFAULTS: dict[str, Any] = {
    # --- speech model -------------------------------------------------
    # tiny.en | base.en | small.en | medium.en | large-v3 | distil-large-v3
    # English-only (.en) models are faster and more accurate for English.
    "model": "small.en",
    # null = auto-detect language, or an ISO code such as "en", "hi", "ta".
    "language": "en",
    "device": "cpu",           # "cpu" or "cuda"
    "compute_type": "int8",    # cpu: int8 | int8_float32 ; cuda: float16
    # CPU cores used for inference. 0 = pick a sensible number for this
    # machine. Benchmarking here showed 8 beat both 4 and 16, and that going
    # wider than half the cores never helped.
    "cpu_threads": 0,
    "beam_size": 1,            # 1 = greedy = fastest. 5 = slower, slightly better.
    "vad_filter": True,        # drop silence before transcribing
    # Quiet microphones transcribe badly. Scale the recording up before
    # sending it to Whisper.
    "normalize_audio": True,
    # Nudges spelling of names/jargon you use often, e.g.
    # "Transcript of a developer talking about Python, Supabase and Vercel."
    "initial_prompt": None,
    "model_dir": "models",     # models are downloaded here on first use

    # --- hotkey -------------------------------------------------------
    # Combine with "+", e.g. "ctrl_r", "f9", "ctrl+alt+space", "caps_lock".
    # "ctrl" matches either ctrl key; "ctrl_r" matches only the right one.
    "hotkey": "ctrl+win",
    # "hold"   = push-to-talk, records while the key is held (recommended)
    # "toggle" = tap once to start, tap again to stop
    "mode": "hold",
    # Hands-free recording for long passages: press this, let go of everything,
    # talk as long as you like, then tap the stop key. Set to null to disable.
    "long_hotkey": "ctrl+win+space",
    # Pressed on its own to end a hands-free recording. VoiceFlow swallows this
    # keypress so it does not also type into whatever you are dictating into.
    "long_stop_key": "space",

    # --- audio --------------------------------------------------------
    "input_device": None,      # null = system default. See --list-devices.
    "sample_rate": 16000,
    "min_duration": 0.35,      # ignore accidental taps shorter than this (s)
    "max_duration": 300,       # hard stop after this many seconds

    # --- output -------------------------------------------------------
    "output": "paste",         # "paste" (clipboard + Ctrl+V) or "type"
    "restore_clipboard": True,
    "trailing_space": True,    # so back-to-back dictations don't run together
    "capitalize_first": True,
    "strip_hallucinations": True,
    "log_transcripts": True,   # append to transcripts.log

    # --- feedback -----------------------------------------------------
    "sound_feedback": True,    # short beeps on start / stop / error
    "tray_icon": True,
    # Floating pill showing the live waveform while you speak. It is built
    # so it can never take focus, so the paste still lands in your app.
    "overlay": True,
}


def load(path: str | Path | None = None) -> dict[str, Any]:
    """Read config.json, filling in any missing keys from DEFAULTS."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    cfg = dict(DEFAULTS)

    if cfg_path.exists():
        with cfg_path.open("r", encoding="utf-8") as fh:
            user = json.load(fh)
        unknown = set(user) - set(DEFAULTS)
        if unknown:
            print(f"[config] ignoring unknown keys: {', '.join(sorted(unknown))}")
        cfg.update({k: v for k, v in user.items() if k in DEFAULTS})
    else:
        write_defaults(cfg_path)
        print(f"[config] wrote starter config to {cfg_path}")

    cfg["_path"] = str(cfg_path)
    return cfg


def write_defaults(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(DEFAULTS, fh, indent=2)
        fh.write("\n")


def model_dir(cfg: dict[str, Any]) -> str:
    d = Path(cfg["model_dir"])
    if not d.is_absolute():
        d = ROOT / d
    d.mkdir(parents=True, exist_ok=True)
    return str(d)

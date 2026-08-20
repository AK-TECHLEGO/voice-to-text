"""Audible cues, played off-thread so they never delay recording."""

from __future__ import annotations

import threading

try:
    import winsound
except ImportError:  # non-Windows
    winsound = None  # type: ignore[assignment]

_TONES = {
    "start": [(880, 60)],
    "stop": [(660, 55)],
    "done": [(1046, 45)],
    "error": [(400, 90), (300, 120)],
}


def play(name: str, enabled: bool = True) -> None:
    if not enabled or winsound is None:
        return
    tones = _TONES.get(name)
    if not tones:
        return

    def _run() -> None:
        try:
            for freq, ms in tones:
                winsound.Beep(freq, ms)
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()

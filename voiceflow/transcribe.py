"""Local speech-to-text via faster-whisper (CTranslate2)."""

from __future__ import annotations

import os
import re
import time
from typing import Any

import numpy as np

from . import config

# Whisper reliably invents these when fed silence or noise. Dropping a result
# that consists of nothing else is the single biggest quality win for dictation.
_HALLUCINATIONS = {
    "thank you.", "thanks for watching!", "thanks for watching.",
    "thank you for watching.", "thank you for watching!",
    "you", "you.", "bye.", "bye!", ".", "...", "。",
    "please subscribe.", "subtitles by the amara.org community",
    "amara.org", "transcription by castingwords", "[blank_audio]",
    "[silence]", "[music]", "(upbeat music)", "so.", "okay.",
}


def resolve_threads(configured: int) -> int:
    """0 means auto: half the logical cores, capped at 8 and floored at 2."""
    if configured and configured > 0:
        return configured
    return max(2, min(8, (os.cpu_count() or 4) // 2))


class Transcriber:
    """Wraps a WhisperModel; loads lazily so startup stays fast."""

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self._model = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        from faster_whisper import WhisperModel  # imported late: ~1s of import time

        name = self.cfg["model"]
        started = time.perf_counter()
        threads = resolve_threads(self.cfg["cpu_threads"])
        print(f"[model] loading {name} on {self.cfg['device']} "
              f"({self.cfg['compute_type']}, {threads} threads)... "
              f"first run downloads it, please wait")
        self._model = WhisperModel(
            name,
            device=self.cfg["device"],
            compute_type=self.cfg["compute_type"],
            cpu_threads=resolve_threads(self.cfg["cpu_threads"]),
            download_root=config.model_dir(self.cfg),
        )
        print(f"[model] ready in {time.perf_counter() - started:.1f}s")

    def transcribe(self, audio: np.ndarray) -> str:
        self.load()
        assert self._model is not None

        segments, _info = self._model.transcribe(
            audio,
            language=self.cfg["language"],
            beam_size=self.cfg["beam_size"],
            vad_filter=self.cfg["vad_filter"],
            initial_prompt=self.cfg["initial_prompt"],
            condition_on_previous_text=False,  # avoids repeat-loop artefacts
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return self._clean(text)

    def _clean(self, text: str) -> str:
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return ""

        if self.cfg["strip_hallucinations"]:
            stripped = text.lower().strip(" \"'")
            if stripped in _HALLUCINATIONS:
                return ""

        if self.cfg["capitalize_first"]:
            text = text[0].upper() + text[1:]

        if self.cfg["trailing_space"]:
            text += " "
        return text

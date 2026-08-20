"""Ties hotkey -> microphone -> whisper -> keyboard together."""

from __future__ import annotations

import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from . import config, feedback, output
from .audio import Recorder
from .hotkeys import HotkeyListener
from .overlay import Overlay
from .transcribe import Transcriber
from .tray import Tray

LOG_PATH = config.ROOT / "transcripts.log"


class VoiceFlow:
    def __init__(self, cfg: dict[str, Any], use_tray: bool = True):
        self.cfg = cfg
        self.recorder = Recorder(
            sample_rate=cfg["sample_rate"],
            device=cfg["input_device"],
            max_duration=cfg["max_duration"],
        )
        self.transcriber = Transcriber(cfg)
        self.hotkeys = HotkeyListener(
            cfg["hotkey"], cfg["mode"], self._start_recording, self._stop_recording,
            long_spec=cfg["long_hotkey"], stop_key=cfg["long_stop_key"],
            on_latch=self._on_latched,
        )

        self._jobs: queue.Queue[np.ndarray | None] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._stopping = threading.Event()
        self._started_at = 0.0

        self.tray = None
        self._want_tray = use_tray and cfg["tray_icon"]

        self.overlay = Overlay(cfg) if cfg["overlay"] else None
        if self.overlay is not None and not self.overlay.available:
            self.overlay = None
        if self.overlay is not None:
            self.overlay.bind_level(lambda: self.recorder.level)
            self.overlay.set_hint(
                f"hands-free - tap {cfg['long_stop_key'].upper()} to stop")

    # --- state display ------------------------------------------------
    def _tooltip(self, state: str) -> str:
        return f"VoiceFlow - {state}  ({self.cfg['hotkey']}, {self.cfg['mode']})"

    def _set_state(self, state: str, message: str | None = None) -> None:
        if message:
            print(message, flush=True)
        if self.tray is not None:
            self.tray.set_state(state, self._tooltip(state))
        if self.overlay is not None:
            if state == "recording":
                self.overlay.show_recording(latched=self.hotkeys.latched)
            elif state == "working":
                self.overlay.show_working()
            elif state == "idle":
                self.overlay.hide()

    # --- recording ----------------------------------------------------
    def _on_latched(self) -> None:
        stop = self.cfg["long_stop_key"].upper()
        self._set_state("recording", f"[rec] hands-free - tap {stop} to stop")

    def _start_recording(self) -> None:
        if self.recorder.recording:
            return
        try:
            self.recorder.start()
        except Exception as exc:
            feedback.play("error", self.cfg["sound_feedback"])
            self._set_state("error", f"[mic] could not open input device: {exc}")
            return
        self._started_at = time.perf_counter()
        feedback.play("start", self.cfg["sound_feedback"])
        self._set_state("recording", "\n[rec] listening...")

    def _stop_recording(self) -> None:
        if not self.recorder.recording:
            return
        audio = self.recorder.stop()
        seconds = self.recorder.duration(audio)
        feedback.play("stop", self.cfg["sound_feedback"])

        if seconds < self.cfg["min_duration"]:
            self._set_state("idle", f"[rec] {seconds:.2f}s - too short, ignored")
            return
        if self.recorder.peak < 0.002:
            feedback.play("error", self.cfg["sound_feedback"])
            self._set_state("idle", "[mic] silence captured - check your input device "
                                    "(run with --list-devices)")
            if self.overlay is not None:
                self.overlay.show_error("no sound from the microphone")
            return

        self._set_state("working", f"[rec] {seconds:.1f}s captured - transcribing...")
        self._jobs.put(audio)

    # --- transcription worker ------------------------------------------
    def _work(self) -> None:
        while True:
            audio = self._jobs.get()
            if audio is None:
                return
            try:
                started = time.perf_counter()
                text = self.transcriber.transcribe(audio)
                elapsed = time.perf_counter() - started
            except Exception as exc:
                feedback.play("error", self.cfg["sound_feedback"])
                self._set_state("error", f"[whisper] failed: {exc}")
                if self.overlay is not None:
                    self.overlay.show_error("transcription failed")
                continue

            if not text.strip():
                self._set_state("idle", f"[whisper] nothing recognised ({elapsed:.1f}s)")
                if self.overlay is not None:
                    self.overlay.show_error("nothing heard")
                continue

            try:
                output.deliver(text, self.cfg)
            except Exception as exc:
                self._set_state("error", f"[output] could not insert text: {exc}")
                print(f"         transcript was: {text.strip()}")
                continue

            feedback.play("done", self.cfg["sound_feedback"])
            self._set_state("idle", f"[out] {text.strip()}\n      ({elapsed:.1f}s)")
            self._log(text.strip())

    def _log(self, text: str) -> None:
        if not self.cfg["log_transcripts"]:
            return
        try:
            with LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now().isoformat(timespec='seconds')}\t{text}\n")
        except Exception:
            pass

    # --- config reload (tray menu) ---------------------------------------
    def _reload_config(self) -> None:
        try:
            fresh = config.load(self.cfg.get("_path"))
        except Exception as exc:
            print(f"[config] reload failed: {exc}")
            return
        model_changed = fresh["model"] != self.cfg["model"]
        hotkey_changed = (fresh["hotkey"], fresh["mode"]) != (self.cfg["hotkey"], self.cfg["mode"])
        self.cfg.update(fresh)
        self.transcriber.cfg = self.cfg
        if model_changed:
            print("[config] model changed - restart VoiceFlow to load it")
        if hotkey_changed:
            print("[config] hotkey changed - restart VoiceFlow to apply it")
        print("[config] reloaded")

    # --- lifecycle ------------------------------------------------------
    def run(self) -> None:
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._worker.start()

        # Load the model up front so the first dictation isn't a 30s surprise.
        self.transcriber.load()

        self.hotkeys.start()
        self._banner()

        # pystray and Tk each want a message loop. The overlay must be on the
        # main thread, so the tray icon is built and run on its own thread.
        if self._want_tray:
            threading.Thread(target=self._run_tray, daemon=True).start()

        if self.overlay is not None:
            try:
                self.overlay.run()   # blocks on the Tk loop until stop()
            except KeyboardInterrupt:
                pass
        else:
            try:
                while not self._stopping.wait(0.5):
                    pass
            except KeyboardInterrupt:
                pass
        self.shutdown()

    def _run_tray(self) -> None:
        """Build and run the tray icon on this thread; pystray needs that."""
        try:
            self.tray = Tray(
                self._tooltip("idle"),
                on_quit=self.shutdown,
                extra_items=[("Reload config", self._reload_config)],
            )
            if self.tray.available:
                self.tray.set_state("idle", self._tooltip("idle"))
                self.tray.run()
        except Exception as exc:
            print(f"[tray] unavailable: {exc}")
            self.tray = None

    def _banner(self) -> None:
        verb = "Hold" if self.cfg["mode"] == "hold" else "Tap"
        print()
        print("  VoiceFlow - local speech to text")
        print("  " + "-" * 44)
        print(f"  {verb}  {self.cfg['hotkey'].upper()}  to dictate into any window.")
        print(f"  model: {self.cfg['model']}   output: {self.cfg['output']}")
        print("  Ctrl+C here (or Quit in the tray) to exit.")
        print()
        print("  If pressing that key does nothing, your keyboard may report it")
        print("  under another name. Stop this, then run:  run.bat --debug-keys")
        print("  Press the key you want, and put the name it prints into")
        print("  config.json as \"hotkey\" (or try:  run.bat --hotkey f9).")
        print()

    def shutdown(self) -> None:
        if self._stopping.is_set():
            return
        self._stopping.set()
        self.hotkeys.stop()
        if self.recorder.recording:
            self.recorder.stop()
        self._jobs.put(None)
        if self.tray is not None:
            self.tray.stop()
        if self.overlay is not None:
            self.overlay.stop()
        print("[exit] stopped")


def self_test(cfg: dict[str, Any], seconds: float = 5.0) -> int:
    """Record for a few seconds and print the transcript. Verifies the pipeline."""
    rec = Recorder(cfg["sample_rate"], cfg["input_device"], cfg["max_duration"])
    tr = Transcriber(cfg)
    tr.load()

    print(f"\n[test] recording {seconds:.0f}s - say something now...")
    rec.start()
    time.sleep(seconds)
    audio = rec.stop()
    print(f"[test] captured {rec.duration(audio):.1f}s, peak level {rec.peak:.3f}")

    if rec.peak < 0.002:
        print("[test] FAILED: microphone produced silence. "
              "Check Windows mic privacy settings and --list-devices.")
        return 1

    started = time.perf_counter()
    text = tr.transcribe(audio)
    print(f"[test] transcribed in {time.perf_counter() - started:.1f}s")
    print(f"[test] result: {text.strip() or '(nothing recognised)'}")
    return 0 if text.strip() else 1

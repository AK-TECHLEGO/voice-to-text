"""Delivering the transcript into whatever window has focus."""

from __future__ import annotations

import time
from typing import Any

import pyperclip
from pynput.keyboard import Controller, Key

_keyboard = Controller()


def deliver(text: str, cfg: dict[str, Any]) -> None:
    if not text:
        return
    if cfg["output"] == "type":
        _type(text)
    else:
        _paste(text, restore=cfg["restore_clipboard"])


def _paste(text: str, restore: bool = True) -> None:
    """Clipboard + Ctrl+V. Instant regardless of length, and unicode-safe."""
    previous = None
    if restore:
        try:
            previous = pyperclip.paste()
        except Exception:
            previous = None

    pyperclip.copy(text)
    time.sleep(0.03)  # let the clipboard settle before the target app reads it

    with _keyboard.pressed(Key.ctrl):
        _keyboard.press("v")
        _keyboard.release("v")

    if restore and previous is not None:
        time.sleep(0.25)  # give the target app time to actually read the clipboard
        try:
            pyperclip.copy(previous)
        except Exception:
            pass


def _type(text: str) -> None:
    """Synthesise keystrokes. Slower, but works where paste is blocked."""
    _keyboard.type(text)

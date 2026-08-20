"""System-tray indicator. Optional - the app runs headless without it."""

from __future__ import annotations

from typing import Callable

_COLORS = {
    "loading": (150, 150, 150),
    "idle": (70, 140, 220),
    "recording": (220, 70, 70),
    "working": (230, 170, 50),
    "error": (120, 40, 40),
}


def _icon_image(state: str):
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, size - 4, size - 4), fill=_COLORS.get(state, _COLORS["idle"]))
    # A little microphone glyph so it reads as a dictation app in the tray.
    draw.rounded_rectangle((26, 16, 38, 36), radius=6, fill=(255, 255, 255, 235))
    draw.arc((20, 26, 44, 46), start=0, end=180, fill=(255, 255, 255, 235), width=4)
    draw.line((32, 44, 32, 50), fill=(255, 255, 255, 235), width=4)
    return img


class Tray:
    """Thin wrapper so app.py doesn't care whether pystray is installed."""

    def __init__(self, title: str, on_quit: Callable[[], None],
                 extra_items: list[tuple[str, Callable[[], None]]] | None = None):
        self.available = False
        self._icon = None
        try:
            import pystray
        except ImportError:
            return

        items = [pystray.MenuItem(label, (lambda f: lambda *_: f())(fn))
                 for label, fn in (extra_items or [])]
        items.append(pystray.MenuItem("Quit", lambda *_: (self.stop(), on_quit())))

        self._icon = pystray.Icon(
            "voiceflow", _icon_image("loading"), title, pystray.Menu(*items)
        )
        self.available = True

    def set_state(self, state: str, tooltip: str | None = None) -> None:
        if self._icon is None:
            return
        try:
            self._icon.icon = _icon_image(state)
            if tooltip:
                self._icon.title = tooltip
        except Exception:
            pass

    def run(self) -> None:
        """Blocks. Must be called from the main thread on Windows."""
        if self._icon is not None:
            self._icon.run()

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass

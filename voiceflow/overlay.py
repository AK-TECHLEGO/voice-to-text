"""A floating status pill, like Whisper Flow's.

The hard requirement is that this window must NEVER take focus. VoiceFlow types
into whatever window you were already using, so if the pill stole focus the
transcript would land in the pill instead of your editor. Two things guarantee
that on Windows:

  * WS_EX_NOACTIVATE  - showing or clicking the window does not activate it
  * SW_SHOWNOACTIVATE - shown without being made foreground

The process is also made DPI-aware before Tk starts, otherwise Windows scales
the window up on a non-100% display and the pill renders blurry.

Tkinter is not thread-safe, so the rest of the app talks to the overlay through
a queue that the Tk event loop drains.
"""

from __future__ import annotations

import ctypes
import queue
import sys
import time
from typing import Any

# --- Win32 constants -------------------------------------------------------
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
SW_HIDE = 0
SW_SHOWNOACTIVATE = 4
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010

# --- look, in design units at 96 DPI; multiplied by the display scale ------
WIDTH, HEIGHT = 300, 68
MARGIN_BOTTOM = 90          # clear of the taskbar
CHROMA = "#ff00fe"          # made fully transparent, so the pill looks rounded
BG = "#16181d"
FG = "#e8eaf0"
DIM = "#8b91a1"
REC = "#ef4444"
BUSY = "#f2b134"
OK = "#4a8fdc"
BARS = 22
FACE = "Segoe UI"


def _make_dpi_aware() -> float:
    """Opt into real pixels and return the display scale (1.25 at 125%)."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor v2
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        return ctypes.windll.user32.GetDpiForSystem() / 96.0
    except Exception:
        return 1.0


class Overlay:
    """Non-focusing status pill. Call run() on the main thread."""

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self._cmds: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._root = None
        self._canvas = None
        self._hwnd = 0
        self._s = 1.0
        self._w, self._h = WIDTH, HEIGHT
        self._state = "hidden"
        self._text = ""
        self._level_fn = None          # callable returning 0.0-1.0
        self._history = [0.0] * BARS
        self._hide_at = 0.0
        self._visible = False
        self._hint = "hands-free - tap SPACE to stop"
        self.available = sys.platform == "win32"

    # --- API used by the rest of the app (any thread) -------------------
    def bind_level(self, fn) -> None:
        self._level_fn = fn

    def set_hint(self, text: str) -> None:
        self._hint = text

    def show_recording(self, latched: bool = False) -> None:
        self._cmds.put(("state", "latched" if latched else "recording"))

    def show_working(self) -> None:
        self._cmds.put(("state", "working"))

    def show_text(self, text: str) -> None:
        self._cmds.put(("text", text))

    def show_error(self, text: str) -> None:
        self._cmds.put(("error", text))

    def hide(self) -> None:
        self._cmds.put(("state", "hidden"))

    def stop(self) -> None:
        self._cmds.put(("stop", None))

    # --- helpers ----------------------------------------------------------
    def _px(self, n: float) -> int:
        return int(round(n * self._s))

    def _font(self, size: int, bold: bool = False):
        # Negative size means pixels, which keeps text the right size whatever
        # Tk decides its own scaling factor is.
        return (FACE, -self._px(size), "bold") if bold else (FACE, -self._px(size))

    # --- window ---------------------------------------------------------
    def _build(self) -> None:
        self._s = _make_dpi_aware()
        import tkinter as tk

        self._w, self._h = self._px(WIDTH), self._px(HEIGHT)

        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.configure(bg=CHROMA)
        try:
            root.attributes("-transparentcolor", CHROMA)
        except tk.TclError:
            pass                      # falls back to a square window
        root.attributes("-topmost", True)

        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x = (sw - self._w) // 2
        y = sh - self._h - self._px(MARGIN_BOTTOM)
        root.geometry(f"{self._w}x{self._h}+{x}+{y}")

        canvas = tk.Canvas(root, width=self._w, height=self._h, bg=CHROMA,
                           highlightthickness=0, bd=0)
        canvas.pack()

        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        ctypes.windll.user32.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

        self._root, self._canvas, self._hwnd = root, canvas, hwnd

    def _set_visible(self, visible: bool) -> None:
        if visible == self._visible:
            return
        self._visible = visible
        ctypes.windll.user32.ShowWindow(
            self._hwnd, SW_SHOWNOACTIVATE if visible else SW_HIDE)
        if visible:
            # Re-assert topmost without ever activating the window.
            ctypes.windll.user32.SetWindowPos(
                self._hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    # --- drawing ---------------------------------------------------------
    def _rounded(self, x0, y0, x1, y1, r, fill) -> None:
        c = self._canvas
        c.create_oval(x0, y0, x0 + 2 * r, y1, fill=fill, outline=fill)
        c.create_oval(x1 - 2 * r, y0, x1, y1, fill=fill, outline=fill)
        c.create_rectangle(x0 + r, y0, x1 - r, y1, fill=fill, outline=fill)

    def _dot(self, colour) -> None:
        cx, cy, r = self._px(29), self._h // 2, self._px(5)
        self._canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                 fill=colour, outline=colour)

    def _draw(self) -> None:
        self._canvas.delete("all")
        self._rounded(1, 1, self._w - 1, self._h - 1, self._h // 2, BG)
        if self._state in ("recording", "latched"):
            self._draw_recording()
        elif self._state == "working":
            self._draw_working()
        elif self._state in ("text", "error"):
            self._draw_text()

    def _draw_recording(self) -> None:
        self._dot(REC)
        hands_free = self._state == "latched"
        # Shift the waveform up to make room for the hint line.
        mid = self._h // 2 - (self._px(7) if hands_free else 0)
        scale = 0.24 if hands_free else 0.32
        left, right = self._px(48), self._w - self._px(26)
        step = (right - left) / float(BARS)
        for i, lvl in enumerate(self._history):
            h = max(self._px(1.5), min(1.0, lvl * 9.0) * (self._h * scale))
            x = left + i * step
            self._canvas.create_rectangle(x, mid - h, x + step * 0.55, mid + h,
                                          fill=OK, outline=OK)
        if hands_free:
            self._canvas.create_text(self._px(48), self._h // 2 + self._px(16),
                                     anchor="w", fill=DIM, font=self._font(8),
                                     text=self._hint)

    def _draw_working(self) -> None:
        self._dot(BUSY)
        dots = int(time.time() * 3) % 4
        self._canvas.create_text(self._px(48), self._h // 2, anchor="w", fill=FG,
                                 font=self._font(12),
                                 text="Transcribing" + "." * dots)

    def _draw_text(self) -> None:
        mid = self._h // 2
        self._dot(REC if self._state == "error" else OK)
        text = self._text if len(self._text) <= 34 else self._text[:33] + "..."
        self._canvas.create_text(self._px(48), mid - self._px(9), anchor="w",
                                 fill=FG, font=self._font(11), text=text)
        self._canvas.create_text(self._px(48), mid + self._px(11), anchor="w",
                                 fill=DIM, font=self._font(8),
                                 text="pasted" if self._state == "text" else "error")

    # --- loop ------------------------------------------------------------
    def _tick(self) -> None:
        while True:
            try:
                kind, payload = self._cmds.get_nowait()
            except queue.Empty:
                break
            if kind == "stop":
                self._root.quit()
                return
            if kind == "state":
                self._state = payload
                self._hide_at = 0.0
                if payload in ("recording", "latched"):
                    self._history = [0.0] * BARS
            elif kind in ("text", "error"):
                self._state = kind
                self._text = payload
                self._hide_at = time.time() + (2.5 if kind == "error" else 1.6)

        if self._state == "recording" and self._level_fn is not None:
            self._history = self._history[1:] + [self._level_fn()]

        if self._hide_at and time.time() >= self._hide_at:
            self._state = "hidden"
            self._hide_at = 0.0

        self._set_visible(self._state != "hidden")
        if self._visible:
            self._draw()

        self._root.after(40, self._tick)

    def run(self) -> None:
        """Blocks on the Tk event loop. Main thread only."""
        self._build()
        self._root.after(40, self._tick)
        try:
            self._root.mainloop()
        finally:
            try:
                self._root.destroy()
            except Exception:
                pass

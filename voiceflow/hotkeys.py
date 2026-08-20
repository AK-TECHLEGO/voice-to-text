"""Global hotkey handling.

Three ways to dictate:

  hold      hold Ctrl+Win, speak, let go            - short bursts
  toggle    tap the hotkey on, tap it off           - if you prefer
  latched   Ctrl+Win+Space, let go of everything,   - long passages
            speak as long as you like, tap Space

Two Windows details shape this file.

First, Windows removes a low-level keyboard hook whose callback overruns
LowLevelHooksTimeout (300 ms by default), and opening an audio stream takes
about 200 ms. So the key callbacks only queue work; a pump thread runs it.

Second, the Space that stops a latched recording must not also type a space
into whatever you are dictating into. Suppressing one key needs
win32_event_filter, which runs inside the hook itself - so that function does
the least possible work and hands off to the pump.
"""

from __future__ import annotations

import ctypes
import queue
import threading
from typing import Callable

from pynput import keyboard
from pynput.keyboard import Key, KeyCode

# Tokens that should match either the left or the right physical key.
_SIDED = {"ctrl", "alt", "shift", "cmd"}
_ALIASES = {"win": "cmd", "windows": "cmd", "super": "cmd", "control": "ctrl",
            "esc": "esc", "return": "enter"}

# Virtual key codes for the modifier tokens. Ctrl/alt/shift have a combined
# code that matches either side; the Windows key does not.
_MOD_VKS = {
    "ctrl": (0x11,),
    "alt": (0x12,),
    "shift": (0x10,),
    "cmd": (0x5B, 0x5C),
}

WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105


def _canon(key) -> str:
    """Canonical lowercase name for a key event, e.g. 'ctrl_r', 'f9', 'a'."""
    if isinstance(key, KeyCode):
        if key.char:
            return key.char.lower()
        return f"vk{key.vk}"
    return getattr(key, "name", str(key)).lower()


def parse(spec: str) -> list[str]:
    """'ctrl+alt+space' -> ['ctrl', 'alt', 'space']. Raises on nonsense."""
    tokens = [t.strip().lower() for t in spec.split("+") if t.strip()]
    if not tokens:
        raise ValueError("hotkey is empty")

    known = {k.name for k in Key}
    resolved = []
    for tok in tokens:
        tok = _ALIASES.get(tok, tok)
        if tok in _SIDED or tok in known or len(tok) == 1:
            resolved.append(tok)
        else:
            raise ValueError(
                f"unknown key {tok!r} in hotkey {spec!r}. "
                f"Use a single character, one of {sorted(_SIDED)}, "
                f"or a named key such as f9, space, caps_lock, insert."
            )
    return resolved


def _satisfies(token: str, pressed: set[str]) -> bool:
    if token in _SIDED:
        return any(p == token or p.startswith(token + "_") for p in pressed)
    return token in pressed


def vk_for(token: str) -> int | None:
    """Virtual key code for a non-modifier token, for the suppression filter."""
    token = _ALIASES.get(token, token)
    if len(token) == 1:
        return ord(token.upper())
    key = getattr(Key, token, None)
    if key is None:
        return None
    value = key.value
    return getattr(value, "vk", None)


def _held_now(vks: tuple[int, ...]) -> bool:
    """Is any of these keys physically down right now?

    Asked of Windows rather than of our own bookkeeping, because the filter
    runs on the hook thread while the bookkeeping is updated on another.
    """
    state = ctypes.windll.user32.GetAsyncKeyState
    return any(state(vk) & 0x8000 for vk in vks)


class HotkeyListener:
    """Calls on_start/on_stop as the configured keys are held, tapped or latched."""

    def __init__(self, spec: str, mode: str,
                 on_start: Callable[[], None], on_stop: Callable[[], None],
                 long_spec: str | None = None, stop_key: str = "space",
                 on_latch: Callable[[], None] | None = None):
        self.tokens = parse(spec)
        self.spec = spec
        if mode not in ("hold", "toggle"):
            raise ValueError(f"mode must be 'hold' or 'toggle', got {mode!r}")
        self.mode = mode
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_latch = on_latch

        # --- latched (hands-free) recording -----------------------------
        self.long_spec = long_spec
        self._long_mod_vks: list[tuple[int, ...]] = []
        self._trigger_vk: int | None = None
        self._stop_vk: int | None = None
        if long_spec:
            long_tokens = parse(long_spec)
            mods = [t for t in long_tokens if t in _SIDED]
            rest = [t for t in long_tokens if t not in _SIDED]
            if len(rest) != 1:
                raise ValueError(
                    f"long_hotkey {long_spec!r} must be modifiers plus exactly one "
                    f"other key, for example 'ctrl+win+space'")
            self._long_mod_vks = [_MOD_VKS[m] for m in mods]
            self._trigger_vk = vk_for(rest[0])
            self._stop_vk = vk_for(stop_key)
            if self._trigger_vk is None or self._stop_vk is None:
                raise ValueError(
                    f"cannot use {long_spec!r} / {stop_key!r} for hands-free "
                    f"recording: no virtual key code for that key")

        self._actions: queue.Queue[Callable[[], None] | None] = queue.Queue()
        self._pump: threading.Thread | None = None
        self._pressed: set[str] = set()
        self._combo_down = False   # the hold combination is currently held
        self._active = False       # we are currently recording
        self._latched = False      # recording continues with no keys held
        self._suppress_up: set[int] = set()
        self._listener: keyboard.Listener | None = None

    @property
    def latched(self) -> bool:
        return self._latched

    # --- lifecycle ----------------------------------------------------
    def start(self) -> None:
        self._pump = threading.Thread(target=self._drain, daemon=True)
        self._pump.start()
        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release,
            win32_event_filter=self._filter,
        )
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        self._actions.put(None)

    def _drain(self) -> None:
        """Runs the start/stop callbacks off the hook thread, in order."""
        while True:
            action = self._actions.get()
            if action is None:
                return
            try:
                action()
            except Exception as exc:
                print(f"[hotkey] {getattr(action, '__name__', action)} failed: {exc}")

    # --- the suppression filter, on the hook thread --------------------
    def _filter(self, msg, data):
        """Runs inside the Windows hook. Must stay trivial and fast.

        Returning False hides the event from our own callbacks; calling
        suppress_event() hides it from every other application too, and raises.
        """
        if self._trigger_vk is None:
            return True

        vk = data.vkCode
        listener = self._listener
        if listener is None:
            return True

        if msg in (WM_KEYUP, WM_SYSKEYUP) and vk in self._suppress_up:
            self._suppress_up.discard(vk)
            listener.suppress_event()

        if msg in (WM_KEYDOWN, WM_SYSKEYDOWN):
            if self._latched and vk == self._stop_vk:
                self._suppress_up.add(vk)
                self._stop_latched()
                listener.suppress_event()
            elif (not self._latched and vk == self._trigger_vk
                    and all(_held_now(m) for m in self._long_mod_vks)):
                self._suppress_up.add(vk)
                self._latch()
                listener.suppress_event()
        return True

    # --- events, on the listener's message-loop thread -----------------
    def _held(self, tokens: list[str]) -> bool:
        return all(_satisfies(t, self._pressed) for t in tokens)

    def _on_press(self, key) -> None:
        self._pressed.add(_canon(key))
        if self._latched:
            return                      # only the stop key matters now
        if self._combo_down or not self._held(self.tokens):
            return  # already down, or not our combination - ignore key repeat
        self._combo_down = True

        if self.mode == "hold":
            self._activate()
        else:
            self._deactivate() if self._active else self._activate()

    def _on_release(self, key) -> None:
        self._pressed.discard(_canon(key))
        if self._latched:
            # Letting go of Ctrl+Win must not end a hands-free recording.
            if not self._held(self.tokens):
                self._combo_down = False
            return
        if not self._combo_down or self._held(self.tokens):
            return
        self._combo_down = False

        if self.mode == "hold" and self._active:
            self._deactivate()

    # --- state transitions ---------------------------------------------
    def _activate(self) -> None:
        self._active = True
        self._actions.put(self.on_start)

    def _deactivate(self) -> None:
        self._active = False
        self._actions.put(self.on_stop)

    def _latch(self) -> None:
        """Hands-free: keep recording after every key is released."""
        self._latched = True
        if not self._active:
            self._activate()
        if self.on_latch is not None:
            self._actions.put(self.on_latch)

    def _stop_latched(self) -> None:
        self._latched = False
        self._combo_down = False
        if self._active:
            self._deactivate()


def watch() -> None:
    """Print the name of every key pressed, so you can find one that works.

    Use the printed name as the "hotkey" value in config.json.
    """
    print()
    print("Press any key to see the name VoiceFlow knows it by.")
    print("Put that name in config.json as the \"hotkey\" value.")
    print("Press Ctrl+C here to stop.")
    print()

    def on_press(key):
        print(f"  pressed: {_canon(key)}", flush=True)

    listener = keyboard.Listener(on_press=on_press)
    listener.start()
    try:
        while listener.running:
            listener.join(0.3)
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()

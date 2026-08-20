"""One running copy at a time.

Every running copy listens to the same microphone and pastes its own
transcript, so two copies paste the same sentence twice. Because
run-background.bat starts a windowless process, duplicates are invisible and
easy to accumulate - hence a hard lock rather than a warning.

A named mutex does the locking (race-free, and released automatically if the
process is killed). A PID file alongside it exists only so --stop can find the
running copy.
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

from . import config

MUTEX_NAME = "Global\\VoiceFlow.SingleInstance.v1"
PID_PATH = config.ROOT / ".voiceflow.pid"

ERROR_ALREADY_EXISTS = 183

_handle = None          # kept alive for the process lifetime


def acquire() -> bool:
    """True if we got the lock; False if another copy already holds it."""
    global _handle
    kernel32 = ctypes.windll.kernel32
    _handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not _handle:
        return True                       # cannot lock; do not block startup
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return False
    try:
        PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass
    return True


def release() -> None:
    global _handle
    try:
        if PID_PATH.exists() and PID_PATH.read_text(encoding="utf-8").strip() == str(os.getpid()):
            PID_PATH.unlink()
    except Exception:
        pass
    if _handle:
        ctypes.windll.kernel32.CloseHandle(_handle)
        _handle = None


def running_pid() -> int | None:
    """PID of the running copy, or None."""
    try:
        pid = int(Path(PID_PATH).read_text(encoding="utf-8").strip())
    except Exception:
        return None
    return pid if _alive(pid) else None


def _alive(pid: int) -> bool:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    exit_code = ctypes.c_ulong()
    kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
    kernel32.CloseHandle(handle)
    return exit_code.value == 259          # STILL_ACTIVE


def stop_running() -> int:
    """Terminate the running copy. Returns its PID, or 0 if none was found."""
    pid = running_pid()
    if pid is None:
        return 0
    PROCESS_TERMINATE = 0x0001
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        return 0
    kernel32.TerminateProcess(handle, 0)
    kernel32.CloseHandle(handle)
    try:
        PID_PATH.unlink()
    except Exception:
        pass
    return pid


ALREADY_RUNNING = (
    "VoiceFlow is already running.\n\n"
    "Every running copy types its own transcript, so two copies paste the "
    "same sentence twice.\n\n"
    "Quit it from the tray icon, or run:  run.bat --stop"
)


def report_already_running() -> None:
    """Tell the user, on the console or in a box if there is no console.

    run-background.bat uses pythonw, which has no console at all - without the
    message box a rejected launch would look like nothing happened, and the
    obvious response is to click again.
    """
    print(ALREADY_RUNNING)
    if _output_is_visible():
        return
    MB_OK, MB_ICONWARNING, MB_TOPMOST = 0x0, 0x30, 0x40000
    ctypes.windll.user32.MessageBoxW(
        0, ALREADY_RUNNING, "VoiceFlow", MB_OK | MB_ICONWARNING | MB_TOPMOST)


def _output_is_visible() -> bool:
    """Whether the printed message will actually reach a human.

    Checking for a console is not enough: pythonw.exe inherits its parent's
    console handle, so GetConsoleWindow() is non-zero even though nothing it
    prints is ever displayed. Under pythonw sys.stdout is None, and that is the
    reliable signal.
    """
    if sys.stdout is None:
        return False
    return bool(ctypes.windll.kernel32.GetConsoleWindow())

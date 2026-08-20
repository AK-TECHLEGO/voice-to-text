"""VoiceFlow - local push-to-talk dictation. Entry point.

  python main.py                 start dictating
  python main.py --test          record 5s and print the transcript
  python main.py --list-devices  show microphones
"""

from __future__ import annotations

import argparse
import sys

from voiceflow import config
from voiceflow.app import VoiceFlow, self_test


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="voiceflow",
        description="Local speech-to-text. Hold a hotkey, speak, "
                    "and the text appears in whatever window has focus.",
    )
    p.add_argument("--config", metavar="PATH", help="alternate config.json")
    p.add_argument("--model", help="override the model for this run "
                                   "(tiny.en, base.en, small.en, medium.en, large-v3)")
    p.add_argument("--hotkey", help="override the hotkey, e.g. f9 or ctrl+alt+space")
    p.add_argument("--mode", choices=("hold", "toggle"), help="override the trigger mode")
    p.add_argument("--device", help="override the input device (index or name fragment)")
    p.add_argument("--language", help="override the language code, or 'auto'")
    p.add_argument("--no-tray", action="store_true", help="run without a tray icon")
    p.add_argument("--no-overlay", action="store_true", help="run without the floating pill")
    p.add_argument("--test", nargs="?", type=float, const=5.0, metavar="SECONDS",
                   help="record for N seconds, print the transcript, and exit")
    p.add_argument("--list-devices", action="store_true", help="list microphones and exit")
    p.add_argument("--debug-keys", action="store_true",
                   help="print the name of every key you press, to find a working hotkey")
    p.add_argument("--compare", nargs="?", const="", metavar="WAV",
                   help="record your voice once and transcribe it with every "
                        "model, so you can see which is worth the wait")
    p.add_argument("--stop", action="store_true",
                   help="stop the copy of VoiceFlow that is already running")
    p.add_argument("--allow-multiple", action="store_true",
                   help="skip the single-instance lock (each copy pastes its own text)")
    return p.parse_args()


def apply_overrides(cfg: dict, args: argparse.Namespace) -> None:
    if args.model:
        cfg["model"] = args.model
    if args.hotkey:
        cfg["hotkey"] = args.hotkey
    if args.mode:
        cfg["mode"] = args.mode
    if args.language:
        cfg["language"] = None if args.language == "auto" else args.language
    if args.device is not None:
        cfg["input_device"] = int(args.device) if args.device.isdigit() else args.device


def main() -> int:
    # Console output must appear immediately, even when piped to a file.
    try:
        sys.stdout.reconfigure(line_buffering=True, errors="replace")
    except Exception:
        pass
    args = parse_args()

    from voiceflow import single

    if args.stop:
        pid = single.stop_running()
        print(f"stopped VoiceFlow (pid {pid})" if pid else "VoiceFlow was not running")
        return 0

    if args.debug_keys:
        from voiceflow.hotkeys import watch
        watch()
        return 0

    if args.list_devices:
        from voiceflow.audio import list_devices
        print(list_devices())
        return 0

    cfg = config.load(args.config)
    apply_overrides(cfg, args)

    if args.compare is not None:
        from voiceflow.compare import run as compare_run
        return compare_run(cfg, args.compare or None)

    if args.test is not None:
        return self_test(cfg, args.test)

    if args.no_overlay:
        cfg["overlay"] = False
    if not args.allow_multiple and not single.acquire():
        single.report_already_running()
        return 1

    app = VoiceFlow(cfg, use_tray=not args.no_tray)
    try:
        app.run()
    except KeyboardInterrupt:
        app.shutdown()
    finally:
        single.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())

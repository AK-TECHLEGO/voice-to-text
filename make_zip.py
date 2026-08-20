r"""Build the zip you send to someone else.

Only source goes in - about 25 KB. install.bat fetches the packages and the
speech model on the other machine, so nothing here needs to carry 800 MB.

    python make_zip.py            -> ..\VoiceFlow-setup.zip
    python make_zip.py out.zip
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from voiceflow import config as _config

ROOT = Path(__file__).resolve().parent

FILES = ["START-HERE.txt", "README.md", "install.bat", "run.bat",
         "run-background.bat", "requirements.txt", "main.py", "make_zip.py"]

# Settings that describe this machine rather than the app. Reset to defaults so
# the recipient gets a clean install instead of your microphone index.
MACHINE_SPECIFIC = {"input_device": None, "cpu_threads": 0}


def build(out: Path) -> None:
    # config.json is git-ignored, so a fresh clone has none. Either way the
    # recipient should get the defaults, not whatever this machine is set to.
    cfg = dict(_config.DEFAULTS)
    local = ROOT / "config.json"
    if local.exists():
        cfg.update(json.loads(local.read_text(encoding="utf-8")))
    cfg.update(MACHINE_SPECIFIC)
    cfg.pop("_path", None)
    clean_cfg = json.dumps(cfg, indent=2) + "\n"

    members = [ROOT / name for name in FILES]
    members += sorted((ROOT / "voiceflow").glob("*.py"))

    missing = [m.name for m in members if not m.exists()]
    if missing:
        raise SystemExit("missing files: " + ", ".join(missing))

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in members:
            arc = "VoiceFlow/" + str(f.relative_to(ROOT)).replace("\\", "/")
            z.write(f, arc)
        z.writestr("VoiceFlow/config.json", clean_cfg)

    size_kb = out.stat().st_size / 1024
    print(f"{out}  ({len(members) + 1} files, {size_kb:.0f} KB)")
    print("Send that one file. They unzip it and run install.bat.")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "VoiceFlow-setup.zip"
    build(target.resolve())

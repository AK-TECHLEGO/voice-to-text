"""VoiceFlow - local push-to-talk dictation using Whisper."""

import os

# Set before huggingface_hub is imported; we do not need symlinked caches.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

__version__ = "1.0.0"

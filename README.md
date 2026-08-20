# VoiceFlow

A local Whisper Flow alternative for Windows. Hold a key, speak, release — your
words appear in whatever window has focus. Nothing leaves your machine: the
speech model runs on your own CPU.

## Install

Double-click **`install.bat`**. It checks for Python, creates a private
environment, installs the dependencies, downloads the speech model into
`models/`, and puts a shortcut on the Desktop. About 800 MB, once.

Requires Python 3.11 or newer. If it is missing, `install.bat` opens the
download page and explains what to tick.

## Giving it to someone else

Run `make-zip.bat` to build `VoiceFlow-setup.zip` next to this folder. It
contains only the source - about 25 KB - because `install.bat` fetches the
packages and the model on the other machine.

Send them the zip. They unzip it somewhere permanent, run `install.bat`, and
that is it. `START-HERE.txt` inside the zip walks a non-developer through it.

## Use

Double-click **`run.bat`**.

Hold **Ctrl + Windows**, speak, release. The transcript is pasted into the
active window.

For anything longer, use hands-free mode: press **Ctrl + Windows + Space**,
let go of every key, talk for as long as you like, then tap **Space** on its
own to stop. That Space is swallowed, so it does not type a space into what you
are dictating into.

A pill appears at the bottom of the screen while you talk, showing a live
waveform, then "Transcribing", then the text it pasted. In hands-free mode it
also reminds you which key stops it. It is built so it can
never take focus - your cursor stays exactly where it was, which is why the
paste lands in your editor and not in the pill. A beep confirms the start and end of recording, and the tray icon turns
red while it is listening.

`run-background.bat` starts it with no console window — tray icon only.

## Configuration

Edit `config.json` (created on first run) and restart.

| Setting | What it does |
|---|---|
| `model` | `tiny.en`, `base.en`, `small.en` (default), `medium.en`, `large-v3`. Bigger = more accurate, slower. |
| `language` | `"en"`, or `null` to auto-detect, or e.g. `"hi"`, `"ta"`, `"te"`. Drop the `.en` from the model name for non-English. |
| `hotkey` | `"ctrl_r"`, `"f9"`, `"caps_lock"`, `"ctrl+alt+space"`, … |
| `mode` | `"hold"` = push-to-talk. `"toggle"` = tap to start, tap to stop. |
| `long_hotkey` | Starts a hands-free recording that survives releasing the keys. `null` disables it. |
| `long_stop_key` | Tapped alone to end a hands-free recording. Swallowed, so it is not typed. |
| `output` | `"paste"` (clipboard + Ctrl+V, instant) or `"type"` (synthesised keystrokes, for apps that block paste). |
| `input_device` | `null` for the system default, or a device number from `--list-devices`. |
| `initial_prompt` | Free text that nudges spelling of names and jargon you use often. |
| `beam_size` | `1` is fastest. `5` is a little more accurate and noticeably slower. |
| `cpu_threads` | Cores used for inference. `8` benchmarked fastest on this machine; 16 was no better. |
| `sound_feedback` | Set to `false` to silence the beeps. |
| `overlay` | The floating pill. `false` for tray-icon-only. |

## Command line

```
run.bat --list-devices        show microphones
run.bat --test                record 5 seconds and print the transcript
run.bat --model base.en       try a different model without editing config
run.bat --hotkey f9 --mode toggle
run.bat --language auto       auto-detect the spoken language
run.bat --no-tray
run.bat --no-overlay          hide the floating pill
run.bat --stop                stop the running copy
run.bat --allow-multiple      bypass the single-instance lock (rarely wanted)
```

## Choosing a model

Measured on this machine (16 cores, CPU, `int8`). "Realtime factor" is how much
faster than the audio's own length it transcribes.

| Model | Size | Accuracy | Speed |
|---|---|---|---|
| `tiny.en` | 75 MB | rough | fastest |
| `base.en` | 145 MB | decent | very fast |
| `small.en` | 500 MB | good — the default | fast enough for dictation |
| `medium.en` | 1.5 GB | very good | slow on CPU |
| `large-v3` | 3 GB | best, multilingual | too slow on CPU |

## Troubleshooting

**Nothing is typed.** The target app may block synthetic paste. Set
`"output": "type"` in `config.json`.

**"silence captured".** Wrong microphone. Run `run.bat --list-devices` and set
`input_device` to the right number. Also check Windows Settings → Privacy →
Microphone.

**The hotkey does nothing.** Find out what your keyboard actually reports:

```
run.bat --debug-keys
```

Press the key you want. It prints the name VoiceFlow knows it by - put that
into `config.json` as `hotkey`. Not every keyboard has every key, and some
laptop keys are behind `Fn`.

**The hotkey does nothing in some apps.** Apps running as administrator ignore
input from non-elevated processes. Run `run.bat` as administrator too.

**The first fraction of a second gets cut off.** Measured at about 0.4s between
pressing the key and audio actually being captured, most of it spent opening the
microphone. Start speaking a moment after pressing rather than at the same
instant.

**The same sentence is pasted several times.** More than one copy is running -
each one hears you and pastes its own transcript. This is now blocked, but if
you see it, run `run.bat --stop`, or check Task Manager for stray
`pythonw.exe`. Note that Python 3.14's venv launcher means one running copy
shows as two processes: a small stub and the real app.

**The pill does not appear.** Run `run.bat --no-overlay` to confirm the rest
still works, and check the console for a Tk error. The pill needs Windows.

**First run is slow.** The model is downloading. Subsequent starts load it from
`models/` in a few seconds.

**Transcripts** are appended to `transcripts.log`. Set `log_transcripts` to
`false` to stop that.

## How it works

Ending a hands-free recording with Space must not also type a space. Only
`win32_event_filter` can suppress a single key, and it runs inside the hook
itself - so it does nothing but set a flag and hand off to the pump thread.

Windows silently removes a low-level keyboard hook whose callback runs longer
than 300 ms, and opening an audio stream takes about 200 ms. So the key
callbacks only queue work onto a pump thread and return immediately - otherwise
the hotkey stops responding after the first press.

The pill uses `WS_EX_NOACTIVATE` plus `SW_SHOWNOACTIVATE` so Windows never
makes it the foreground window, and it sets per-monitor DPI awareness before Tk
starts - without that it renders blurry on a scaled display (yours is at 125%).
Tk owns the main thread, so the tray icon runs on its own thread.

`voiceflow/hotkeys.py` watches the keyboard globally → `voiceflow/audio.py`
captures 16 kHz mono from the mic → `voiceflow/transcribe.py` runs
faster-whisper (CTranslate2) on it → `voiceflow/output.py` puts the text in the
clipboard and sends Ctrl+V. `voiceflow/app.py` wires those together and runs
transcription on a worker thread so the hotkey never blocks.

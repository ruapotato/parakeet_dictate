"""
Parakeet Dictate - local, CPU-only dictation for Windows.

Trigger (keyboard hotkey or a mic button that sends a keystroke) -> speak ->
release/toggle -> Parakeet TDT 0.6B (INT8 ONNX) transcribes on-device -> text
is post-processed (filler stripping, macro expansion) -> pasted at the cursor.

No cloud, no GPU. Settings live in the user's Documents folder so they roam.
"""

import sys
import time
import threading
from collections import deque
import tkinter as tk
from tkinter import ttk

import settings as settings_mod
import postprocess
import mic_hid

# Heavy modules (numpy, sounddevice, keyboard, pyperclip, onnx_asr) are imported
# lazily in _startup() so the loading window can appear instantly instead of
# waiting on onnxruntime's slow import. These names are filled in then.
np = None
sd = None
keyboard = None
pyperclip = None

SAMPLE_RATE = 16000
BLOCKSIZE = 1600
MODEL_NAME = "nemo-parakeet-tdt-0.6b-v3"
MIN_SECONDS = 0.3
MAX_SECONDS = 28
PREROLL_SECONDS = 0.5
PREROLL_SAMPLES = int(SAMPLE_RATE * PREROLL_SECONDS)

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
SETTINGS = settings_mod.load()
model = None
model_ready = threading.Event()

_lock = threading.Lock()
_recording = False
_capture = []
_ring = deque()
_ring_samples = 0
_key_is_down = False
_input_hook = None
_mic_reader = None
_stream = None
status_var = None


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------
def _audio_cb(indata, frames_count, time_info, status):
    global _ring_samples
    # PortAudio reports 'input overflow' while warming up at startup; it is
    # benign, so we don't surface it to the user.
    chunk = indata.copy()
    with _lock:
        if _recording:
            _capture.append(chunk)
        else:
            _ring.append(chunk)
            _ring_samples += len(chunk)
            while _ring_samples > PREROLL_SAMPLES and len(_ring) > 1:
                _ring_samples -= len(_ring.popleft())


def start_recording():
    global _recording, _capture
    if not model_ready.is_set():
        return
    with _lock:
        if _recording:
            return
        _capture = list(_ring)
        _recording = True
    _set_status("Listening...")


def stop_and_transcribe():
    global _recording, _capture, _ring_samples
    with _lock:
        if not _recording:
            return
        _recording = False
        frames = _capture
        _capture = []
        _ring.clear()
        _ring_samples = 0
    if not frames:
        _set_status("Ready")
        return

    audio = np.concatenate(frames, axis=0).flatten().astype(np.float32)
    dur = len(audio) / SAMPLE_RATE
    if dur < MIN_SECONDS:
        _set_status("Ready")
        return

    _set_status("Transcribing...")
    try:
        raw = model.recognize(audio, sample_rate=SAMPLE_RATE)
    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        _set_status("Ready")
        return

    text = postprocess.apply((raw or "").strip(), SETTINGS)
    print(f'  raw="{raw}"  ->  out="{text}"')
    if text:
        if SETTINGS.get("trailing_space", True):
            text = text + " "
        inject(text)
    _set_status("Ready")


def inject(text):
    try:
        saved = pyperclip.paste()
    except Exception:
        saved = None
    try:
        pyperclip.copy(text)
        time.sleep(0.03)
        keyboard.send("ctrl+v")
        time.sleep(0.05)
    finally:
        if saved is not None:
            try:
                pyperclip.copy(saved)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Input handling (configurable key, hold or toggle)
# ---------------------------------------------------------------------------
def _trigger_press():
    """Shared press action for hold vs toggle behavior."""
    behavior = SETTINGS["input"].get("hold_or_toggle", "hold")
    if behavior == "hold":
        start_recording()
    else:  # toggle
        if _recording:
            stop_and_transcribe()
        else:
            start_recording()


def _trigger_release():
    if SETTINGS["input"].get("hold_or_toggle", "hold") == "hold":
        stop_and_transcribe()


def install_input():
    global _input_hook, _mic_reader, _key_is_down
    # tear down any existing sources
    if _input_hook is not None:
        try:
            keyboard.unhook(_input_hook)
        except Exception:
            pass
        _input_hook = None
    if _mic_reader is not None:
        try:
            _mic_reader.stop()
        except Exception:
            pass
        _mic_reader = None
    _key_is_down = False

    inp = SETTINGS["input"]
    mode = inp.get("mode", "hotkey")

    if mode == "mic_button" and inp.get("mic"):
        mic = inp["mic"]
        _mic_reader = mic_hid.MicButtonReader(
            mic["vid"], mic["pid"], mic,
            on_press=_trigger_press, on_release=_trigger_release)
        if _mic_reader.start():
            return
        # fall back to keyboard if the device could not be opened
        print("[input] mic unavailable; falling back to keyboard hotkey")
        _mic_reader = None

    key = inp.get("hotkey", "right ctrl")

    def handler(event):
        global _key_is_down
        if event.name != key:
            return
        if event.event_type == keyboard.KEY_DOWN:
            if not _key_is_down:
                _key_is_down = True
                _trigger_press()
        elif event.event_type == keyboard.KEY_UP:
            _key_is_down = False
            _trigger_release()

    _input_hook = keyboard.hook(handler)


# ---------------------------------------------------------------------------
# Model load (background)
# ---------------------------------------------------------------------------
def load_model_bg():
    global model
    import onnx_asr
    _set_status("Loading model (first run downloads ~640 MB)...")
    model = onnx_asr.load_model(MODEL_NAME, quantization="int8",
                                providers=["CPUExecutionProvider"])
    model.recognize(np.zeros(SAMPLE_RATE, dtype=np.float32), sample_rate=SAMPLE_RATE)
    model_ready.set()
    _set_status("Ready")


# ---------------------------------------------------------------------------
# Small control window
# ---------------------------------------------------------------------------
def _set_status(msg):
    if status_var is not None:
        try:
            status_var.set(msg)
        except Exception:
            pass


def on_settings_saved(new_data):
    global SETTINGS
    SETTINGS = new_data
    install_input()  # re-apply key / mode changes immediately
    _set_status("Settings saved. Ready")


def _startup():
    """All blocking init runs here (off the UI thread) so the loading window
    appears instantly instead of waiting on the audio device to open."""
    global _stream, np, sd, keyboard, pyperclip
    try:
        _set_status("Loading components...")
        import numpy as _np; np = _np
        import sounddevice as _sd; sd = _sd
        import keyboard as _kb; keyboard = _kb
        import pyperclip as _pc; pyperclip = _pc
        _set_status("Starting audio...")
        _stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                 dtype="float32", blocksize=BLOCKSIZE,
                                 callback=_audio_cb)
        _stream.start()
        install_input()
    except Exception as e:
        print(f"[startup] init failed: {e}")
    load_model_bg()


def _shutdown_stream():
    global _stream
    if _stream is not None:
        try:
            _stream.stop(); _stream.close()
        except Exception:
            pass
        _stream = None


def main():
    global status_var
    root = tk.Tk()
    root.title("Parakeet Dictate")
    root.geometry("360x170")

    # --- loading view -----------------------------------------------------
    loading = ttk.Frame(root)
    loading.pack(fill="both", expand=True)
    ttk.Label(loading, text="Loading Parakeet Dictate",
              font=("Segoe UI", 12)).pack(pady=(28, 6))
    load_msg = ttk.Label(loading, foreground="#555",
                         text="Please stand by...")
    load_msg.pack()
    bar = ttk.Progressbar(loading, mode="indeterminate", length=240)
    bar.pack(pady=16)
    bar.start(12)

    status_var = tk.StringVar(value="Starting...")

    def poll_loading():
        load_msg.config(text=status_var.get())
        if model_ready.is_set():
            bar.stop()
            loading.destroy()
            build_main_view(root)
        else:
            root.after(200, poll_loading)

    # paint the window first, then kick off blocking init in the background
    threading.Thread(target=_startup, daemon=True).start()
    root.after(200, poll_loading)

    try:
        root.mainloop()
    finally:
        _shutdown_stream()


def build_main_view(root):
    """Shown only after the model has finished loading."""
    frame = ttk.Frame(root)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, textvariable=status_var,
              font=("Segoe UI", 11)).pack(pady=(18, 4))
    hint = ttk.Label(frame, foreground="#555", text="")
    hint.pack()

    def open_settings():
        from settings_gui import SettingsWindow
        SettingsWindow(root, SETTINGS, on_settings_saved)

    ttk.Button(frame, text="Edit Settings", command=open_settings).pack(pady=8)

    def refresh_hint():
        inp = SETTINGS["input"]
        if inp.get("mode") == "mic_button" and inp.get("mic"):
            mic = inp["mic"]
            src = f'{mic.get("product", "mic")} ({mic_hid.describe(mic)})'
        else:
            src = f'key: {inp["hotkey"]}'
        hint.config(text=f'{inp["hold_or_toggle"]}  -  {src}')
        root.after(1000, refresh_hint)
    refresh_hint()
    _set_status("Ready")


if __name__ == "__main__":
    main()

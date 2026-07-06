"""
Parakeet Dictate - local, CPU-only dictation for Windows.

Trigger (keyboard hotkey or a mic button that sends a keystroke) -> speak ->
release/toggle -> Parakeet TDT 0.6B (INT8 ONNX) transcribes on-device -> text
is post-processed (filler stripping, macro expansion) -> pasted at the cursor.

No cloud, no GPU. Settings live in the user's Documents folder so they roam.
"""

import sys
import time
import queue
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
# Model-download progress, published by the huggingface_hub tqdm hook and read
# by the loading window's poll loop. None = no active large download (either not
# started yet, or already cached); otherwise (done_bytes, total_bytes).
_download_progress = None
# Ignore huggingface_hub's tiny config/vocab downloads so only the ~640 MB model
# file drives the progress bar.
_MODEL_FILE_MIN_BYTES = 10 * 1024 * 1024
_recording = False
_capture = []
_ring = deque()
_ring_samples = 0
_key_is_down = False
_input_hook = None
_mic_reader = None
_stream = None
status_var = None

# --- continuous dictation (VAD segmentation) ---
_vadmod = None                 # lazily-imported vad module
_vad = None                    # SileroVAD instance
_segmenter = None              # vad.Segmenter instance
_continuous = False            # is the current hold using continuous mode?
_next_mid_sentence = False     # suppress capitalization after a forced mid-cut
_seg_queue = None              # audio chunks -> continuous worker thread
_seg_thread = None
_FLUSH = object()              # sentinel: end of hold, flush the tail segment


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------
def _audio_cb(indata, frames_count, time_info, status):
    global _ring_samples
    # PortAudio reports 'input overflow' while warming up at startup; it is
    # benign, so we don't surface it to the user.
    chunk = indata.copy()
    # Continuous mode: hand audio straight to the segmenter thread and keep the
    # PortAudio callback featherweight (no heavy work under the lock).
    if _continuous and _recording:
        _seg_queue.put(chunk)
        return
    with _lock:
        if _recording:
            _capture.append(chunk)
        else:
            _ring.append(chunk)
            _ring_samples += len(chunk)
            while _ring_samples > PREROLL_SAMPLES and len(_ring) > 1:
                _ring_samples -= len(_ring.popleft())


def _recognize_and_inject(audio, mid_sentence=False):
    """Shared tail of both paths: recognize -> post-process -> inject."""
    if audio is None or len(audio) / SAMPLE_RATE < MIN_SECONDS:
        return
    try:
        raw = model.recognize(audio, sample_rate=SAMPLE_RATE)
    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        return
    text = postprocess.apply((raw or "").strip(), SETTINGS, mid_sentence=mid_sentence)
    # PHI guard: transcripts are only echoed when debug logging is enabled, so
    # nothing patient-identifying lands in a captured console log by default.
    if SETTINGS.get("debug"):
        print(f'  raw="{raw}"  ->  out="{text}"')
    if text:
        if SETTINGS.get("trailing_space", True):
            text = text + " "
        inject(text)


def start_recording():
    global _recording, _capture, _continuous, _next_mid_sentence, _ring_samples
    if not model_ready.is_set():
        return
    use_continuous = bool(SETTINGS.get("continuous", {}).get("enabled")) and \
        _segmenter is not None
    with _lock:
        if _recording:
            return
        _continuous = use_continuous
        if use_continuous:
            _segmenter.reset()
            _next_mid_sentence = False
            # Seed the segmenter with pre-speech audio *before* flipping the
            # recording flag, so live chunks can't be queued ahead of preroll.
            for ch in _ring:
                _seg_queue.put(ch)
            _ring.clear()
            _ring_samples = 0
        else:
            _capture = list(_ring)
        _recording = True
    _set_status("Listening...")


def stop_and_transcribe():
    global _recording, _capture, _ring_samples
    if _continuous:
        with _lock:
            if not _recording:
                return
            _recording = False
        _set_status("Transcribing...")
        _seg_queue.put(_FLUSH)   # worker flushes the tail and resets to Ready
        return

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
    _set_status("Transcribing...")
    _recognize_and_inject(audio)
    _set_status("Ready")


# ---------------------------------------------------------------------------
# Continuous dictation worker
# ---------------------------------------------------------------------------
def _handle_segment(res):
    global _next_mid_sentence
    if res is None:
        return
    seg, forced = res
    _recognize_and_inject(seg, mid_sentence=_next_mid_sentence)
    _next_mid_sentence = bool(forced)


def _continuous_worker():
    """Re-slice queued audio into 512-sample frames, run the segmenter, and
    transcribe+inject each completed segment in order (single thread = correct
    insertion order and serialized model access)."""
    accum = None
    while True:
        item = _seg_queue.get()
        if item is None:
            return
        if item is _FLUSH:
            if _segmenter is not None:
                _handle_segment(_segmenter.flush())
            accum = None
            _set_status("Ready")
            continue
        if _segmenter is None:
            continue
        n = _vadmod.FRAME_SAMPLES
        data = item.reshape(-1).astype(np.float32)
        accum = data if accum is None else np.concatenate([accum, data])
        while len(accum) >= n:
            frame = accum[:n]
            accum = accum[n:]
            _handle_segment(_segmenter.push(frame))


def _build_segmenter():
    c = SETTINGS.get("continuous", {})
    return _vadmod.Segmenter(
        _vad,
        threshold=c.get("threshold", 0.5),
        min_silence_ms=c.get("min_silence_ms", 700),
        max_segment_s=c.get("max_segment_s", 20))


def _load_vad_bg():
    """Load the Silero VAD (downloads ~2 MB once) and build the segmenter."""
    global _vadmod, _vad, _segmenter
    try:
        if _vadmod is None:
            import vad as _vadmod_local
            _vadmod = _vadmod_local
        if _vad is None:
            _vad = _vadmod.SileroVAD()
        _segmenter = _build_segmenter()
    except Exception as e:
        print(f"[vad] continuous mode unavailable: {e}", file=sys.stderr)
        _segmenter = None


def inject(text):
    # "type" never touches the clipboard (strongest PHI posture); "paste" is
    # faster and restores whatever the user had on the clipboard afterwards.
    if SETTINGS.get("inject_method", "paste") == "type":
        try:
            keyboard.write(text, delay=0)
        except Exception as e:
            print(f"[inject] type failed: {e}", file=sys.stderr)
        return

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
def _install_hf_download_progress():
    """Route huggingface_hub's per-file byte progress into `_download_progress`
    so the loading window can show a real progress bar during the one-time
    ~640 MB model download instead of an indeterminate spinner (which is
    indistinguishable from a hang). Best-effort: a no-op if hf internals change.

    hf builds its byte-progress bar via huggingface_hub.utils.tqdm.tqdm; we
    subclass it and republish n/total on each update. Patching that one module
    global covers both hf_hub_download and snapshot_download."""
    try:
        import importlib
        # The *submodule* (utils/tqdm.py), not the re-exported class of the same
        # name on the utils package. Its module-global `tqdm` is the class hf's
        # progress-bar context manager instantiates.
        _hf_tqdm_mod = importlib.import_module("huggingface_hub.utils.tqdm")
    except Exception:
        return
    base = _hf_tqdm_mod.tqdm

    def _publish(done, total):
        global _download_progress
        if total and total >= _MODEL_FILE_MIN_BYTES:
            _download_progress = (min(done, total), total)

    class _ReportingTqdm(base):
        def update(self, n=1):
            r = super().update(n)
            try:
                _publish(self.n, self.total or 0)
            except Exception:
                pass
            return r

        def close(self):
            try:
                if self.total:
                    _publish(self.total, self.total)
            except Exception:
                pass
            return super().close()

    _hf_tqdm_mod.tqdm = _ReportingTqdm


def load_model_bg():
    global model, _download_progress
    import onnx_asr
    _install_hf_download_progress()
    _set_status("Loading model (first run downloads ~640 MB)...")
    model = onnx_asr.load_model(MODEL_NAME, quantization="int8",
                                providers=["CPUExecutionProvider"])
    # Download finished (or was cached); drop back to the indeterminate spinner
    # for the model-init + warmup tail below.
    _download_progress = None
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
    global SETTINGS, _segmenter
    old_device = SETTINGS.get("audio_device")
    SETTINGS = new_data
    install_input()  # re-apply key / mode changes immediately
    if sd is not None and new_data.get("audio_device") != old_device:
        _start_stream()  # switch microphones without a restart
    # apply continuous-mode changes live
    if new_data.get("continuous", {}).get("enabled"):
        if _vad is None:
            threading.Thread(target=_load_vad_bg, daemon=True).start()
        else:
            _segmenter = _build_segmenter()  # pick up new pause/threshold values
    _set_status("Settings saved. Ready")


def _start_stream():
    """(Re)open the audio input stream on the configured device.

    audio_device is stored as a device *name* (stable across reboots); None
    means the system default input. Falls back to the default if the saved
    device can't be opened (e.g. the headset was unplugged)."""
    global _stream
    _shutdown_stream()
    device = SETTINGS.get("audio_device") or None
    try:
        _stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                 dtype="float32", blocksize=BLOCKSIZE,
                                 device=device, callback=_audio_cb)
        _stream.start()
    except Exception as e:
        print(f"[audio] could not open '{device}': {e}; using default",
              file=sys.stderr)
        _stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                 dtype="float32", blocksize=BLOCKSIZE,
                                 callback=_audio_cb)
        _stream.start()


def _startup():
    """All blocking init runs here (off the UI thread) so the loading window
    appears instantly instead of waiting on the audio device to open."""
    global np, sd, keyboard, pyperclip, _seg_queue, _seg_thread
    try:
        _set_status("Loading components...")
        import numpy as _np; np = _np
        import sounddevice as _sd; sd = _sd
        import keyboard as _kb; keyboard = _kb
        import pyperclip as _pc; pyperclip = _pc
        _set_status("Starting audio...")
        _start_stream()
        install_input()
        # continuous-dictation plumbing (idle until a hold uses continuous mode)
        _seg_queue = queue.Queue()
        _seg_thread = threading.Thread(target=_continuous_worker, daemon=True)
        _seg_thread.start()
        if SETTINGS.get("continuous", {}).get("enabled"):
            threading.Thread(target=_load_vad_bg, daemon=True).start()
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
        prog = _download_progress
        if prog is not None and prog[0] < prog[1]:
            # Actively downloading the model -> real, determinate progress bar.
            done, total = prog
            if str(bar["mode"]) != "determinate":
                bar.stop()
                bar.config(mode="determinate", maximum=total)
            bar["value"] = done
            mb = 1024 * 1024
            load_msg.config(text=f"Downloading model: {done // mb} / {total // mb} MB"
                                 f"  ({done * 100 // total}%)")
        else:
            # Not downloading (pre-download, cached, or download done -> init).
            if str(bar["mode"]) != "indeterminate":
                bar.config(mode="indeterminate")
                bar.start(12)
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

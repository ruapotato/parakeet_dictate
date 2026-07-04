"""
Silero VAD (v5) run directly through onnxruntime — no PyTorch dependency.

Powers continuous dictation: while the trigger is held, the incoming audio is
split into utterance-sized segments at natural pauses, so each is transcribed
and inserted *as you speak* instead of one big clip on release. This removes the
~30 s practical ceiling and keeps every clip in the recognizer's sweet spot.

The ~2 MB model is downloaded once to a local cache (like the main model) or
loaded from a bundled models/ folder if the exe ships with it.
"""

import sys
import urllib.request
from collections import deque
from pathlib import Path

import numpy as np

VAD_URL = ("https://github.com/snakers4/silero-vad/raw/master/"
           "src/silero_vad/data/silero_vad.onnx")
VAD_FILENAME = "silero_vad.onnx"
SAMPLE_RATE = 16000
FRAME_SAMPLES = 512          # Silero v5 requires exactly 512-sample frames @ 16k


def _candidate_paths():
    """Locations to check before downloading (lets an offline build bundle it)."""
    paths = []
    if getattr(sys, "frozen", False):  # running from a PyInstaller exe
        paths.append(Path(getattr(sys, "_MEIPASS", ".")) / "models" / VAD_FILENAME)
        paths.append(Path(sys.executable).parent / "models" / VAD_FILENAME)
    paths.append(Path(__file__).resolve().parent / "models" / VAD_FILENAME)
    return paths


def _cache_path():
    d = Path.home() / ".cache" / "parakeet_dictate"
    d.mkdir(parents=True, exist_ok=True)
    return d / VAD_FILENAME


def resolve_model(download=True):
    """Return a path to the VAD model, downloading it once if needed (or None)."""
    for p in _candidate_paths():
        if p.is_file():
            return p
    cache = _cache_path()
    if cache.is_file():
        return cache
    if not download:
        return None
    tmp = cache.with_name(cache.name + ".part")
    urllib.request.urlretrieve(VAD_URL, tmp)
    tmp.replace(cache)
    return cache


class SileroVAD:
    """Thin onnxruntime wrapper: feed 512-sample frames, get a speech probability."""

    def __init__(self, model_path=None):
        import onnxruntime as ort
        path = str(model_path or resolve_model())
        so = ort.SessionOptions()
        so.inter_op_num_threads = 1
        so.intra_op_num_threads = 1
        self._sess = ort.InferenceSession(
            path, sess_options=so, providers=["CPUExecutionProvider"])
        self._sr = np.array(SAMPLE_RATE, dtype=np.int64)
        self.reset()

    def reset(self):
        self._state = np.zeros((2, 1, 128), dtype=np.float32)

    def prob(self, frame):
        x = np.asarray(frame, dtype=np.float32).reshape(1, -1)
        out, self._state = self._sess.run(
            ["output", "stateN"],
            {"input": x, "state": self._state, "sr": self._sr})
        return float(out.ravel()[0])


class Segmenter:
    """Turn a stream of 512-sample frames into speech segments.

    push(frame) returns (segment_audio, forced) when a segment closes, else None:
      - a natural close = speech followed by >= min_silence_ms of quiet
      - a forced close  = the segment hit max_segment_s without a pause
    Call flush() when the trigger is released to emit any trailing speech.
    Hysteresis (neg_threshold) mirrors Silero's own VADIterator so brief dips
    below the threshold mid-word don't chop a segment.
    """

    def __init__(self, vad, threshold=0.5, min_silence_ms=700,
                 speech_pad_ms=200, max_segment_s=20.0):
        self.vad = vad
        self.threshold = threshold
        self.neg_threshold = max(0.15, threshold - 0.15)
        self.min_silence = int(SAMPLE_RATE * min_silence_ms / 1000)
        self.max_segment = int(SAMPLE_RATE * max_segment_s)
        pad_frames = max(1, int((speech_pad_ms / 1000) * SAMPLE_RATE / FRAME_SAMPLES))
        self._prepad = deque(maxlen=pad_frames)
        self.reset()

    def reset(self):
        self.vad.reset()
        self._triggered = False
        self._buf = []
        self._silence = 0
        self._prepad.clear()

    def push(self, frame):
        p = self.vad.prob(frame)
        if not self._triggered:
            self._prepad.append(frame)
            if p >= self.threshold:
                self._triggered = True
                self._buf = list(self._prepad)   # keep a little pre-speech context
                self._silence = 0
            return None

        self._buf.append(frame)
        if p < self.neg_threshold:
            self._silence += FRAME_SAMPLES
            if self._silence >= self.min_silence:
                return self._emit(forced=False)
        else:
            self._silence = 0
        if sum(len(f) for f in self._buf) >= self.max_segment:
            return self._emit(forced=True)
        return None

    def flush(self):
        if self._triggered and self._buf:
            return self._emit(forced=False)
        return None

    def _emit(self, forced):
        seg = np.concatenate(self._buf).astype(np.float32) if self._buf else None
        self._buf = []
        self._triggered = False
        self._silence = 0
        self._prepad.clear()
        return (seg, forced)

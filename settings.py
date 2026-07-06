"""
Settings storage for Parakeet Dictate.

Stored as JSON under the user's *real* Documents folder (resolved via the
Windows known-folder API so it honours folder redirection / roaming profiles).
On a roaming setup the file follows the user to any machine.
"""

import json
import sys
from pathlib import Path

APP_DIR_NAME = "ParakeetDictate"
SETTINGS_FILENAME = "settings.json"

DEFAULT_MACRO = (
    "Adult patient checkout:\n"
    "Patient seen and evaluated today. Vitals reviewed and within normal "
    "limits. No acute distress. Plan discussed with the patient, questions "
    "answered. Follow up as needed.\n"
)

DEFAULTS = {
    "input": {
        "mode": "hotkey",          # "hotkey" or "mic_button"
        "hold_or_toggle": "hold",  # "hold" = push-to-talk, "toggle" = press on/off
        "hotkey": "right ctrl",    # key name (keyboard library naming)
        "mic": None,               # {vid, pid, product, byte_index, match, mask/value}
    },
    # Audio capture device. None = system default input. Otherwise the
    # sounddevice device name (a stable string that survives index reshuffles).
    "audio_device": None,
    # How transcribed text reaches the cursor:
    #   "type"  = simulate keystrokes (nothing ever touches the clipboard)
    #   "paste" = clipboard + Ctrl+V (fast; briefly places text on the clipboard)
    # Default is "type": the strongest PHI posture, since patient text never
    # lands on the clipboard where another app could read it.
    "inject_method": "type",
    "trailing_space": True,
    "capitalize_first": True,
    # When True, transcripts are printed to the console for troubleshooting.
    # Leave False in clinical use so PHI never lands in a captured log.
    "debug": False,
    "strip_leading": ["okay", "mm-hmm", "mhm", "um", "uh", "so", "yeah"],
    "ignore_if_only": ["okay", "mm-hmm", "mhm", "um", "uh", "yeah", "yes",
                        "no", "thanks", "thank you"],
    # Exact-match templates: the whole utterance must match the trigger.
    "macros": {
        "adult patient checkout": DEFAULT_MACRO,
    },
    # Inline replacements: spoken form -> written form, applied anywhere in a
    # sentence. Good for drug shorthand, abbreviations, and fixing mis-hears.
    # e.g. "metformin five hundred" -> "metformin 500 mg", "a fib" -> "AFib".
    "substitutions": {},
    # Local numeric / medical formatting. Each is a no-op unless it is confident.
    "formatting": {
        "vitals": True,    # "one twenty over eighty" -> "120/80"
        "units": True,     # "twenty five milligrams" -> "25 mg"
        "numbers": False,  # convert every spoken number to digits (affects prose)
    },
    # Continuous dictation: split a long hold at natural pauses (Silero VAD) and
    # insert each sentence as you speak, removing the ~30 s single-clip ceiling.
    "continuous": {
        "enabled": False,
        "min_silence_ms": 700,   # pause length that ends a segment
        "max_segment_s": 20,     # hard cut if no pause (keeps clips model-sized)
        "threshold": 0.5,        # Silero speech probability threshold
    },
}


def _windows_documents_dir():
    """Real Documents path via SHGetKnownFolderPath (handles redirection)."""
    import ctypes
    from ctypes import wintypes

    # FOLDERID_Documents = {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    folderid = GUID(0xFDD39AD0, 0x238F, 0x46AF,
                    (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
    path_ptr = ctypes.c_wchar_p()
    res = ctypes.windll.shell32.SHGetKnownFolderPath(
        ctypes.byref(folderid), 0, None, ctypes.byref(path_ptr))
    if res != 0:
        raise OSError("SHGetKnownFolderPath failed")
    try:
        return Path(path_ptr.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(path_ptr)


def documents_dir():
    if sys.platform.startswith("win"):
        try:
            return _windows_documents_dir()
        except Exception:
            pass
    return Path.home() / "Documents"


def settings_path():
    d = documents_dir() / APP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d / SETTINGS_FILENAME


# Nested dicts that should be key-merged with defaults (so flags added in a
# later version still get a value) rather than wholesale-replaced by old files.
_MERGE_KEYS = ("input", "formatting", "continuous")


def _merge_defaults(data):
    merged = json.loads(json.dumps(DEFAULTS))  # deep copy
    for k, v in data.items():
        if k in _MERGE_KEYS and isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k].update(v)
        else:
            merged[k] = v
    return merged


def load():
    p = settings_path()
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[settings] could not parse {p}: {e}; using defaults",
                  file=sys.stderr)
    merged = _merge_defaults(data)
    if not p.exists():
        save(merged)
    return merged


def save(data):
    settings_path().write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

# Parakeet Dictate

**Fully local, HIPAA-friendly voice-to-text for Windows — an open-source
alternative to Dragon.** Push a key (or your dictation mic's button), speak, and
the transcript appears at your cursor in any application. No cloud, no GPU, no
audio or text ever leaves the machine.

Built for medical private practices, but useful to anyone who wants private,
offline dictation.

---

## Why this exists

Dragon is expensive, cloud-tied in its modern form, and a pain to deploy.
Parakeet Dictate runs NVIDIA's **Parakeet TDT 0.6B** speech model (INT8 ONNX)
entirely on the CPU, on-device. The recognizer already punctuates and
capitalizes well on its own; this app adds the workflow around it — triggering,
insertion, medical formatting, and templates — and ships as a single `.exe`.

## Feature overview

| Capability | Status |
|---|---|
| Local CPU speech recognition (no GPU, no network after setup) | ✅ |
| Push-to-talk **hold** or **press-to-toggle** | ✅ |
| Trigger by **keyboard hotkey** *or* a **mic/HID record button** | ✅ |
| Pick which **microphone** records | ✅ |
| Insert by **clipboard paste** (fast) or **direct typing** (no clipboard) | ✅ |
| **Macros** — say a phrase, insert a whole paragraph/template | ✅ |
| **Substitutions** — spoken abbreviation → written form, inline | ✅ |
| **Medical formatting** — `one twenty over eighty` → `120/80`, `twenty five milligrams` → `25 mg` | ✅ |
| **Continuous dictation** (checkbox in the General tab) — hold and talk for as long as you like; sentences insert as you pause (Silero VAD) | ✅ |
| Filler-word cleanup (`strip from start`, `ignore if alone`) | ✅ |
| Roaming settings — settings live in Documents, so they follow the user on any setup where the Documents folder is shared across machines (roaming profile / folder redirection) | ✅ |
| Single-file Windows `.exe`, optional automated CI builds | ✅ |

See [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md) for a full settings walkthrough
and [`docs/PRIVACY.md`](docs/PRIVACY.md) for the HIPAA / data-handling posture.

---

## Quick start (run from source)

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python parakeet_dictate.py
```

Put your cursor in any text field, **hold Right Ctrl**, speak, release. The
transcript pastes at the cursor. Open **Edit Settings** to change the trigger,
microphone, macros, and formatting.

> **First run downloads ~640 MB** (the INT8 model) from Hugging Face to
> `%USERPROFILE%\.cache\huggingface`. After that it is fully offline. The
> download is model weights — never patient data.

## Getting the .exe

**Option A — download a prebuilt exe (if CI is enabled on the repo).**
The GitHub Actions workflow at `.github/workflows/build-windows.yml` builds on a
Windows runner and publishes:
- a rolling **`latest`** prerelease on every push to `main`, and
- a **versioned release** whenever you push a tag like `v1.0.0`.

Grab `ParakeetDictate.exe` from the repo's **Releases** page. (Builds are
unsigned, so Windows SmartScreen may warn on first launch — *More info → Run
anyway*.)

**Option B — build it yourself on Windows.** PyInstaller cannot cross-compile,
so this must run on Windows:

```bat
build.bat
```

Output: `dist\ParakeetDictate.exe`.

## Making it *fully* offline (no first-run download)

For a locked-down clinical fleet, bundle the model so the exe never contacts
Hugging Face:

1. Download the INT8 files (encoder/decoder/joiner/tokens) into a `models\`
   folder next to the script.
2. Point `onnx_asr.load_model` at that local path instead of the model name.
3. Add `--add-data "models;models"` to the PyInstaller command in `build.bat`.

This yields a ~700 MB+ exe that needs zero network on any machine.

---

## Notes / gotchas

- **Global hotkey:** the hotkey normally works without elevation. If the key
  does nothing on a locked-down machine, try running the exe as administrator —
  some Windows configs restrict the global keyboard hook.
- **Utterance length:** by default each press is one clip and the model is
  happiest under ~30 s. For paragraph-length notes, turn on the **Continuous
  dictation** checkbox (General tab): a small Silero VAD splits your speech at
  natural pauses and inserts each sentence as you talk, with no length limit. It
  downloads a ~2 MB model once, then runs offline.
- **Using a Dragon mic button?** Close Dragon first so the button's HID reports
  reach this app.

## Project layout

| File | Purpose |
|---|---|
| `parakeet_dictate.py` | App entry point: audio capture, model, injection, UI |
| `postprocess.py` | Filler stripping, macros, substitutions, formatting pipeline |
| `formatting.py` | Local numeric/medical formatting (vitals, units, numbers) |
| `vad.py` | Silero VAD (ONNX) + segmenter for continuous dictation |
| `settings.py` | Roaming JSON settings in the user's Documents folder |
| `settings_gui.py` | Tkinter settings editor |
| `mic_hid.py` | Generic HID button learning/reading (no device hardcoded) |
| `test_formatting.py`, `test_vad.py` | Pure-Python self-tests (run on any OS) |
| `build.bat` | Windows single-exe build |
| `.github/workflows/build-windows.yml` | Automated Windows build + release |

## Roadmap

Higher-value gaps toward full Dragon parity, roughly prioritized:

- System-tray icon, run-minimized, start-on-login
- Optional audio/visual "listening" indicator
- Voice editing commands (e.g. "scratch that")
- Bundled-model build variant for zero-network deployment
- Template fields you can jump between (fill-in-the-blank auto-texts)

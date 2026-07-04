# Parakeet Dictate (Windows, CPU-only)

Local push-to-talk dictation using NVIDIA Parakeet TDT 0.6B (INT8 ONNX).
No GPU, no cloud, no audio leaves the machine.

## Try it without building first

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python parakeet_dictate.py
```

Put your cursor in any text field, **hold Right Ctrl**, speak, release.
The transcript pastes at the cursor.

## Build the single .exe

Run `build.bat` on the Windows box (PyInstaller can't cross-compile, so it
must build on Windows). Output: `dist\ParakeetDictate.exe`.

## Notes / gotchas

- **First run downloads ~640 MB** (the INT8 model) from Hugging Face to
  `%USERPROFILE%\.cache\huggingface`. After that it's fully offline. The
  download is model weights, not PHI.
- **The `keyboard` library needs admin** to install its global hook on some
  Windows configs. If the hotkey does nothing, run the exe as administrator.
- **Utterance length:** the model is happiest under ~30 s per press. For
  paragraph-length dictation, add silence-based chunking (Silero VAD) later —
  the record-then-transcribe loop stays the same.
- **Change the hotkey / trailing space** at the top of `parakeet_dictate.py`.
- **Expected speed on the 13400T:** clips transcribe faster than real time
  (RTF well under 1); the app prints the RTF after each utterance so you can
  measure it on your hardware.

## Making it a *truly* offline single file (no first-run download)

If you want the exe to carry the model so it never touches Hugging Face:

1. Download the INT8 files (encoder/decoder/joiner/tokens) into a `models\`
   folder next to the script.
2. Point `onnx_asr.load_model` at that local path instead of the model name.
3. Add `--add-data "models;models"` to the PyInstaller command in `build.bat`.

This yields a ~700 MB+ exe but requires zero network on any machine — the
better choice for a locked-down clinical fleet.
```

@echo off
REM ==========================================================================
REM  Build ParakeetDictate.exe  (run this ON the Windows 13400T box)
REM  Produces a single-file exe in .\dist\ParakeetDictate.exe
REM ==========================================================================

REM 1) Fresh virtual env keeps the bundle small and clean
python -m venv .venv
call .venv\Scripts\activate.bat

REM 1b) Clean stale build output so old artifacts never mix in
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist ParakeetDictate.spec del /q ParakeetDictate.spec

REM 2) Dependencies + PyInstaller
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

REM 2b) Sanity-check the pure-Python formatting/postprocess/VAD logic
python test_formatting.py || goto :eof
python test_vad.py || goto :eof

REM 3) Build. --collect-all pulls onnxruntime's native DLLs and onnx-asr's
REM    bundled preprocessor/decoder assets, which PyInstaller misses otherwise.
REM    --hidden-import vad ensures the lazily-imported VAD module is bundled.
pyinstaller --onefile --windowed --name ParakeetDictate ^
  --icon parakeet.ico ^
  --collect-all onnxruntime ^
  --collect-all pywinusb ^
  --collect-all onnx_asr ^
  --collect-submodules sounddevice ^
  --hidden-import vad ^
  parakeet_dictate.py

echo.
echo ============================================================
echo  Done. Your exe is at:  dist\ParakeetDictate.exe
echo  First launch downloads the model (~640 MB) once, then it
echo  runs fully offline.
echo ============================================================
pause

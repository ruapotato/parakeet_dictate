# Privacy & HIPAA posture

Parakeet Dictate is designed so that **protected health information (PHI) never
leaves the machine**. This document states plainly what the software does and
does not do with your data, so a practice can evaluate it.

> **Not legal advice.** HIPAA compliance is a property of your whole
> environment (the OS, disk encryption, access controls, and your policies),
> not of one application. This document describes the software's behavior to
> help your compliance review; it does not by itself make a deployment
> compliant.

## What stays local

- **Audio** is captured, held in memory, transcribed on-device, and discarded.
  It is never written to disk and never sent over any network.
- **Transcribed text** is inserted into the app you're using and nothing else.
- **Speech recognition** runs entirely on the CPU via a local ONNX model. There
  is no cloud recognizer and no per-utterance network call.

## The only network activity

- **First run** downloads the ~640 MB speech model from Hugging Face to
  `%USERPROFILE%\.cache\huggingface`. This is model weights only — no patient
  data is uploaded. After the download the app runs fully offline.
- **Enabling continuous dictation** downloads a ~2 MB voice-activity model
  (Silero) once, to `%USERPROFILE%\.cache\parakeet_dictate`. Also weights only;
  offline thereafter. Bundle it in `models\silero_vad.onnx` for a zero-network
  build.
- To eliminate even this, ship a **bundled-model build** (see the README) so the
  exe carries the model and never contacts the network. Recommended for
  locked-down clinical fleets.

There is **no telemetry, analytics, crash reporting, or auto-update** that
transmits data.

## Data at rest

- **Settings** are stored as plain JSON in
  `Documents\ParakeetDictate\settings.json`. If your **macros or substitutions
  contain PHI** (e.g. a template with a patient's details — not recommended),
  that file holds it in plain text. Rely on the machine's disk encryption
  (BitLocker) and access controls.
- **No transcripts are logged** by default. Debug logging (which echoes
  transcripts to the console) is **off** unless you explicitly enable it in
  **General → Debug logging**. Keep it off in clinical use.

## Clipboard considerations

- The default **Paste** insertion method briefly places the transcribed text on
  the Windows clipboard, then restores your previous clipboard contents. During
  that brief window the text is on the clipboard and could be captured by
  clipboard-history tools.
- For the strongest posture, switch **General → How text is inserted** to
  **Type**, which simulates keystrokes and **never uses the clipboard**.

## Recommendations for a practice

- Use **Type** insertion if clipboard-history or clipboard-sync tools are active
  on your workstations.
- Deploy the **bundled-model** exe so no machine needs network access.
- Keep **Debug logging off**.
- Ensure workstation **disk encryption** (BitLocker) is on, since settings live
  in Documents.
- Treat macros/substitutions as configuration, not a place to store patient
  data.

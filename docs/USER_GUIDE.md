# Parakeet Dictate — User Guide

This guide walks through every setting. Open the app and click **Edit Settings**
to find these tabs. Settings are saved as JSON in your **Documents\ParakeetDictate\
settings.json** and follow you across machines on a roaming profile.

---

## The basics

1. Launch Parakeet Dictate and wait for **Ready** (the first launch downloads the
   speech model once).
2. Click into any text field — your EHR, an email, a Word doc.
3. **Hold Right Ctrl**, speak a sentence, then **release**. The text appears.

That's the whole loop. Everything below just tunes it.

---

## Input tab — how you start/stop dictation

- **Trigger source**
  - *Keyboard hotkey* — a key on your keyboard starts dictation.
  - *Mic / HID button* — the record button on a dictation microphone.
- **Behavior**
  - *Hold to talk* — record while the key/button is held (push-to-talk).
  - *Press to toggle* — press once to start, press again to stop.
- **Keyboard key** — type a key name or click **Capture key…** and press the key
  you want to use.
- **Mic / HID device** + **Capture button…** — pick your dictation mic, click
  Capture, then press its record button during the 5-second window. The app
  learns which button you pressed automatically (nothing is hardcoded).
  *Close Dragon first* so the button reaches this app.
- **Microphone (audio)** — which microphone is actually recorded. *System
  default* follows Windows' default input device; or pick a specific headset.

## General tab — insertion and formatting basics

- **How text is inserted at the cursor**
  - *Paste* — fastest. Briefly places the text on the clipboard, then restores
    whatever you had. Good default.
  - *Type* — simulates keystrokes so **nothing ever touches the clipboard**.
    Slightly slower for long text; the strongest choice for handling PHI.
- **Add a trailing space** after each insert (so sentences don't run together).
- **Capitalize the first letter** of each insert.
- **Debug logging** — prints transcripts to the console for troubleshooting.
  **Leave this OFF in clinical use** so no patient text lands in a log.
- **Continuous dictation (beta)** — see below.

### Continuous dictation

By default, one press = one clip: you hold, speak, release, and the whole thing
is transcribed at once (best kept under ~30 seconds).

Turn on **Insert sentences as I pause** to dictate long notes without watching
the clock. While you hold the key, a small on-device voice-activity detector
(Silero) watches for natural pauses; each time you pause, the sentence you just
said is transcribed and inserted, and you keep going. There's no length limit.

- **Pause before inserting (ms)** — how long a silence ends a sentence. Lower
  (e.g. 400) inserts sooner but may split where you didn't mean to; higher
  (e.g. 900) waits for clearer pauses. 700 is a good start.
- The first time you enable it, a **~2 MB model downloads once**, then it works
  offline like everything else.
- Text now appears a beat after each pause instead of all at once on release —
  this is the Dragon-like continuous feel. If you'd rather see everything at the
  end, leave this off.

## Macros tab — say a phrase, insert a template

Whole-utterance templates. If everything you said matches the trigger phrase
exactly, the app inserts the full block of text instead.

- Example trigger: *"adult patient checkout"* → inserts your standard checkout
  paragraph.
- Use **New** / **Delete** and **Update this macro** to manage them.
- Macros are matched on the **entire** utterance; for replacements *inside* a
  sentence, use Substitutions.

## Substitutions tab — inline abbreviation expansion

Replacements applied **anywhere in a sentence**. One per line as
`spoken => written`:

```
a fib => AFib
sob => shortness of breath
prn => as needed
htn => hypertension
```

Say *"patient has a fib and htn"* → **"Patient has AFib and hypertension."**
Longer phrases win over shorter ones, and matching is case-insensitive on whole
words. Great for drug shorthand, acronyms, and fixing words the recognizer
consistently mishears.

## Formatting tab — numbers the way clinicians say them

Each rule stays a no-op unless it is confident, so ordinary prose is left alone.

- **Vitals** — `one twenty over eighty` → `120/80` (also `90 over 60`, etc.).
- **Units** — `twenty five milligrams` → `25 mg`; also `mcg`, `mL`, `kg`,
  `mg/dL`, `mmHg`, `%`, and more (only when a number precedes the unit).
- **All numbers to digits** — converts every spoken number (`twenty five` → `25`).
  This also rewrites numbers in prose (`one of them` → `1 of them`), so it is
  **off by default**. Turn it on if your notes are number-heavy.

## Strip from start — remove filler openers

One word per line. Removed only from the **start** of an utterance — fixes the
common "Okay…" / "Mm-hmm…" that dictation mics pick up before you begin.

## Ignore if alone — drop throwaway utterances

One word/phrase per line. Dropped **only** when it's the entire utterance, so a
stray "yes" or "thanks" doesn't get typed, but the same word mid-sentence is
kept.

---

## Tips for accuracy

- Speak in complete sentences and let the recognizer place the punctuation — it
  handles periods and commas well without you saying them.
- Use **Substitutions** for any word it reliably gets wrong (unusual drug or
  patient names).
- Keep each push under ~30 seconds — or turn on **Continuous dictation** in the
  General tab (a checkbox) and talk for as long as you like.
- The hotkey normally works without special permissions. If it does nothing on a
  locked-down machine, try running the app as **administrator** — some Windows
  configs restrict the global keyboard hook.

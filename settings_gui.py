"""
Tkinter settings editor for Parakeet Dictate.

Sections:
  - Input: hotkey vs mic-button mode, hold vs toggle, and a key capture that
    also detects a keystroke emitted by a dictation mic's record button.
  - Strip from start: filler words removed from the beginning of an utterance.
  - Ignore if alone: words dropped when they are the entire utterance.
  - Macros: spoken phrase -> injected text (paragraph templates, shortcuts).
"""

import tkinter as tk
from tkinter import ttk, messagebox

import keyboard  # only used for the key-capture helper

import settings as settings_mod


class SettingsWindow(tk.Toplevel):
    def __init__(self, master, data, on_save):
        super().__init__(master)
        self.title("Parakeet Dictate - Settings")
        self.geometry("640x560")
        self.data = data
        self.on_save = on_save
        self._capture_hook = None

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        self._build_input_tab(nb)
        self._build_general_tab(nb)
        self._build_macro_tab(nb)
        self._build_substitutions_tab(nb)
        self._build_formatting_tab(nb)
        self._build_list_tab(nb, "Strip from start", "strip_leading",
                             "One word per line. Removed from the START of a "
                             "phrase (fixes 'Okay ...' / 'Mm-hmm ...').")
        self._build_list_tab(nb, "Ignore if alone", "ignore_if_only",
                             "One word/phrase per line. Dropped only when it is "
                             "the ENTIRE utterance.")

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(bar, text="Save", command=self._save).pack(side="right")
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="right", padx=6)

    # ---- Input tab -------------------------------------------------------
    def _build_input_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="Input")
        inp = self.data["input"]
        self.mic_binding = dict(inp["mic"]) if inp.get("mic") else None

        self.mode_var = tk.StringVar(value=inp.get("mode", "hotkey"))
        ttk.Label(f, text="Trigger source:").grid(row=0, column=0, sticky="w", pady=6)
        ttk.Radiobutton(f, text="Keyboard hotkey", variable=self.mode_var,
                        value="hotkey").grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(f, text="Mic / HID button", variable=self.mode_var,
                        value="mic_button").grid(row=0, column=2, sticky="w")

        self.behavior_var = tk.StringVar(value=inp.get("hold_or_toggle", "hold"))
        ttk.Label(f, text="Behavior:").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Radiobutton(f, text="Hold to talk", variable=self.behavior_var,
                        value="hold").grid(row=1, column=1, sticky="w")
        ttk.Radiobutton(f, text="Press to toggle", variable=self.behavior_var,
                        value="toggle").grid(row=1, column=2, sticky="w")

        ttk.Separator(f, orient="horizontal").grid(
            row=2, column=0, columnspan=3, sticky="ew", pady=10)

        # keyboard key
        self.key_label = ttk.Label(f, text="Keyboard key:")
        self.key_label.grid(row=3, column=0, sticky="w", pady=4)
        self.key_var = tk.StringVar(value=inp.get("hotkey", "right ctrl"))
        self.key_entry = ttk.Entry(f, textvariable=self.key_var, width=20)
        self.key_entry.grid(row=3, column=1, sticky="w")
        self.capture_btn = ttk.Button(f, text="Capture key...", command=self._capture_key)
        self.capture_btn.grid(row=3, column=2, sticky="w")

        # HID device
        self.device_label = ttk.Label(f, text="Mic / HID device:")
        self.device_label.grid(row=4, column=0, sticky="w", pady=4)
        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(f, textvariable=self.device_var,
                                         width=32, state="readonly")
        self.device_combo.grid(row=4, column=1, columnspan=2, sticky="w")
        self._devices = []
        self._refresh_devices(select_current=True)

        rr = ttk.Frame(f)
        rr.grid(row=5, column=1, columnspan=2, sticky="w", pady=4)
        self.refresh_btn = ttk.Button(rr, text="Refresh", command=self._refresh_devices)
        self.refresh_btn.pack(side="left")
        self.bind_btn = ttk.Button(rr, text="Capture button...",
                                   command=self._capture_button)
        self.bind_btn.pack(side="left", padx=6)

        self.binding_lbl = ttk.Label(f, foreground="#555", text=self._binding_text())
        self.binding_lbl.grid(row=6, column=0, columnspan=3, sticky="w", pady=(2, 6))

        self.mic_hint = ttk.Label(f, wraplength=580, foreground="#555",
                  text="Pick the device, click Capture button, then press the "
                       "button you want (e.g. the mic's record button). Close "
                       "Dragon first so the button reaches this app.")
        self.mic_hint.grid(row=7, column=0, columnspan=3, sticky="w", pady=6)

        ttk.Separator(f, orient="horizontal").grid(
            row=8, column=0, columnspan=3, sticky="ew", pady=10)

        # audio capture device (which microphone the words are recorded from)
        ttk.Label(f, text="Microphone (audio):").grid(row=9, column=0, sticky="w", pady=4)
        self.audio_var = tk.StringVar()
        self.audio_combo = ttk.Combobox(f, textvariable=self.audio_var,
                                        width=40, state="readonly")
        self.audio_combo.grid(row=9, column=1, columnspan=2, sticky="w")
        self._audio_names = []
        self._refresh_audio_devices()
        ttk.Label(f, wraplength=580, foreground="#555",
                  text="Which microphone is recorded. 'System default' follows "
                       "Windows' default input device.").grid(
            row=10, column=0, columnspan=3, sticky="w", pady=(2, 6))

        # Gray out whichever trigger's controls aren't in use, and keep it in
        # sync when the user flips the radio buttons (or when Capture button
        # auto-switches the mode to mic_button).
        self.mode_var.trace_add("write", self._sync_input_mode)
        self._sync_input_mode()

    def _sync_input_mode(self, *_):
        """Enable only the trigger source that's selected; gray out the other.
        The audio-capture mic stays enabled in both modes."""
        keyboard_mode = self.mode_var.get() == "hotkey"
        kb_state = "normal" if keyboard_mode else "disabled"
        mic_state = "disabled" if keyboard_mode else "normal"
        for w in (self.key_label, self.key_entry, self.capture_btn):
            w.config(state=kb_state)
        for w in (self.device_label, self.refresh_btn, self.bind_btn,
                  self.binding_lbl, self.mic_hint):
            w.config(state=mic_state)
        # Combobox uses "readonly" (not "normal") for its enabled-but-locked look.
        self.device_combo.config(state="disabled" if keyboard_mode else "readonly")

    _AUDIO_DEFAULT = "System default"

    def _refresh_audio_devices(self):
        names = [self._AUDIO_DEFAULT]
        try:
            import sounddevice as sd
            seen = set()
            for d in sd.query_devices():
                if d.get("max_input_channels", 0) > 0:
                    nm = d.get("name", "").strip()
                    if nm and nm not in seen:
                        seen.add(nm)
                        names.append(nm)
        except Exception as e:
            print(f"[audio] device list unavailable: {e}")
        self._audio_names = names
        self.audio_combo["values"] = names
        current = self.data.get("audio_device")
        if current and current in names:
            self.audio_combo.current(names.index(current))
        else:
            self.audio_combo.current(0)

    def _binding_text(self):
        try:
            import mic_hid
            desc = mic_hid.describe(self.mic_binding)
        except Exception:
            desc = "none"
        name = self.mic_binding.get("product", "") if self.mic_binding else ""
        return f"Current mic button: {name}  {desc}".strip()

    def _refresh_devices(self, select_current=False):
        try:
            import mic_hid
            self._devices = mic_hid.list_hid_devices()
        except Exception:
            self._devices = []
        labels = [f"{d['product']}  (0x{d['vid']:04x}/0x{d['pid']:04x})"
                  for d in self._devices]
        self.device_combo["values"] = labels
        if select_current and self.mic_binding:
            for i, d in enumerate(self._devices):
                if d["vid"] == self.mic_binding.get("vid") and \
                   d["pid"] == self.mic_binding.get("pid"):
                    self.device_combo.current(i)
                    return
        if labels and not self.device_var.get():
            self.device_combo.current(0)

    def _selected_device(self):
        idx = self.device_combo.current()
        if idx < 0 or idx >= len(self._devices):
            return None
        return self._devices[idx]

    def _capture_button(self):
        dev = self._selected_device()
        if not dev:
            messagebox.showwarning("Capture", "Select a device first.")
            return
        import mic_hid
        self.bind_btn.config(text="Press the button now...")
        learner = mic_hid.ButtonLearner()
        learner.start(dev["vid"], dev["pid"], window=5.0)

        def poll():
            if learner.done.is_set():
                self.bind_btn.config(text="Capture button...")
                if learner.result:
                    b = dict(learner.result)
                    b.update({"vid": dev["vid"], "pid": dev["pid"],
                              "product": dev["product"]})
                    self.mic_binding = b
                    self.mode_var.set("mic_button")
                    self.binding_lbl.config(text=self._binding_text())
                else:
                    messagebox.showinfo(
                        "Capture",
                        "No button change detected.\n\nMake sure Dragon is "
                        "closed, then try again and press the button firmly "
                        "during the 5-second window.")
                return
            self.after(150, poll)
        self.after(150, poll)

    def _capture_key(self):
        self.capture_btn.config(text="Press a key / mic button...")
        self._cleanup_capture()

        def on_key(event):
            if event.event_type == keyboard.KEY_DOWN:
                self.key_var.set(event.name)
                self.after(0, self._cleanup_capture)
                self.after(0, lambda: self.capture_btn.config(text="Capture key..."))
        self._capture_hook = keyboard.hook(on_key)

    def _cleanup_capture(self):
        if self._capture_hook is not None:
            try:
                keyboard.unhook(self._capture_hook)
            except Exception:
                pass
            self._capture_hook = None

    # ---- General tab -----------------------------------------------------
    def _build_general_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="General")

        ttk.Label(f, text="How text is inserted at the cursor:",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=8, pady=(10, 2))
        self.inject_var = tk.StringVar(value=self.data.get("inject_method", "type"))
        ttk.Radiobutton(f, text="Type  -  simulate keystrokes; nothing ever "
                        "touches the clipboard (best for PHI, default)",
                        variable=self.inject_var, value="type").pack(anchor="w", padx=20)
        ttk.Radiobutton(f, text="Paste  -  fast; briefly uses the clipboard "
                        "(restored after)", variable=self.inject_var,
                        value="paste").pack(anchor="w", padx=20)

        ttk.Separator(f, orient="horizontal").pack(fill="x", padx=8, pady=12)

        self.trailing_var = tk.BooleanVar(value=self.data.get("trailing_space", True))
        ttk.Checkbutton(f, text="Add a trailing space after each insert",
                        variable=self.trailing_var).pack(anchor="w", padx=8, pady=2)
        self.capitalize_var = tk.BooleanVar(value=self.data.get("capitalize_first", True))
        ttk.Checkbutton(f, text="Capitalize the first letter of each insert",
                        variable=self.capitalize_var).pack(anchor="w", padx=8, pady=2)
        self.debug_var = tk.BooleanVar(value=self.data.get("debug", False))
        ttk.Checkbutton(f, text="Debug logging (prints transcripts to the "
                        "console — leave OFF in clinical use)",
                        variable=self.debug_var).pack(anchor="w", padx=8, pady=2)

        ttk.Separator(f, orient="horizontal").pack(fill="x", padx=8, pady=12)

        cont = self.data.get("continuous", {})
        ttk.Label(f, text="Continuous dictation (beta):",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=8, pady=(0, 2))
        self.cont_enabled = tk.BooleanVar(value=cont.get("enabled", False))
        ttk.Checkbutton(f, text="Insert sentences as I pause (removes the ~30 s "
                        "length limit; downloads a ~2 MB model once)",
                        variable=self.cont_enabled).pack(anchor="w", padx=20, pady=2)
        prow = ttk.Frame(f)
        prow.pack(anchor="w", padx=20, pady=2)
        ttk.Label(prow, text="Pause before inserting (ms):").pack(side="left")
        self.cont_silence = tk.IntVar(value=int(cont.get("min_silence_ms", 700)))
        ttk.Spinbox(prow, from_=150, to=2000, increment=50, width=6,
                    textvariable=self.cont_silence).pack(side="left", padx=6)
        ttk.Label(prow, text="(lower = each sentence inserts sooner)",
                  foreground="#777").pack(side="left", padx=6)

    # ---- Substitutions tab ----------------------------------------------
    def _build_substitutions_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="Substitutions")
        self.subs = dict(self.data.get("substitutions", {}))

        ttk.Label(f, wraplength=600, foreground="#555",
                  text="Inline replacements applied anywhere in a sentence "
                       "(e.g. 'a fib' -> 'AFib', 'sob' -> 'shortness of "
                       "breath', 'prn' -> 'as needed').").pack(
            anchor="w", padx=8, pady=(8, 4))

        body = ttk.Frame(f)
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        left.pack(side="left", fill="y", padx=6, pady=6)
        ttk.Label(left, text="Spoken form:").pack(anchor="w")
        self.subs_list = tk.Listbox(left, width=26, height=16)
        self.subs_list.pack(fill="y", expand=True)
        self.subs_list.bind("<<ListboxSelect>>", self._subs_selected)
        for k in self.subs:
            self.subs_list.insert("end", k)
        sbtns = ttk.Frame(left)
        sbtns.pack(fill="x", pady=4)
        ttk.Button(sbtns, text="New", command=self._subs_new).pack(side="left")
        ttk.Button(sbtns, text="Delete", command=self._subs_delete).pack(side="left", padx=4)

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        ttk.Label(right, text="Spoken form:").pack(anchor="w")
        self.subs_key = tk.StringVar()
        ttk.Entry(right, textvariable=self.subs_key).pack(fill="x")
        ttk.Label(right, text="Replace with:").pack(anchor="w", pady=(8, 0))
        self.subs_val = tk.StringVar()
        ttk.Entry(right, textvariable=self.subs_val).pack(fill="x")
        ttk.Button(right, text="Update this substitution",
                   command=self._subs_update).pack(anchor="e", pady=8)

    def _subs_selected(self, _e):
        sel = self.subs_list.curselection()
        if not sel:
            return
        k = self.subs_list.get(sel[0])
        self.subs_key.set(k)
        self.subs_val.set(self.subs.get(k, ""))

    def _subs_new(self):
        self.subs_key.set("")
        self.subs_val.set("")

    def _subs_delete(self):
        sel = self.subs_list.curselection()
        if not sel:
            return
        k = self.subs_list.get(sel[0])
        self.subs.pop(k, None)
        self.subs_list.delete(sel[0])

    def _subs_update(self):
        k = self.subs_key.get().strip().lower()
        v = self.subs_val.get().strip()
        if not k:
            messagebox.showwarning("Substitution", "Spoken form cannot be empty.")
            return
        existing = list(self.subs.keys())
        self.subs[k] = v
        if k not in existing:
            self.subs_list.insert("end", k)

    # ---- Formatting tab --------------------------------------------------
    def _build_formatting_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="Formatting")
        fmt = self.data.get("formatting", {})
        ttk.Label(f, wraplength=580, foreground="#555",
                  text="Local number/medical formatting. Each rule stays a "
                       "no-op unless it is confident, so it won't disturb "
                       "ordinary prose.").pack(anchor="w", padx=8, pady=(10, 6))

        self.fmt_vitals = tk.BooleanVar(value=fmt.get("vitals", True))
        ttk.Checkbutton(f, text="Vitals:  'one twenty over eighty'  →  '120/80'",
                        variable=self.fmt_vitals).pack(anchor="w", padx=12, pady=3)
        self.fmt_units = tk.BooleanVar(value=fmt.get("units", True))
        ttk.Checkbutton(f, text="Units:  'twenty five milligrams'  →  '25 mg'",
                        variable=self.fmt_units).pack(anchor="w", padx=12, pady=3)
        self.fmt_numbers = tk.BooleanVar(value=fmt.get("numbers", False))
        ttk.Checkbutton(f, text="All numbers to digits  'twenty five' → '25'  "
                        "(also affects prose — off by default)",
                        variable=self.fmt_numbers).pack(anchor="w", padx=12, pady=3)

    # ---- generic word-list tab ------------------------------------------
    def _build_list_tab(self, nb, title, key, hint):
        f = ttk.Frame(nb)
        nb.add(f, text=title)
        ttk.Label(f, text=hint, wraplength=580, foreground="#555").pack(
            anchor="w", padx=6, pady=6)
        txt = tk.Text(f, height=18, wrap="none")
        txt.pack(fill="both", expand=True, padx=6, pady=6)
        txt.insert("1.0", "\n".join(self.data.get(key, [])))
        setattr(self, f"_text_{key}", txt)

    # ---- macros tab ------------------------------------------------------
    def _build_macro_tab(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="Macros")
        self.macros = dict(self.data.get("macros", {}))

        left = ttk.Frame(f)
        left.pack(side="left", fill="y", padx=6, pady=6)
        ttk.Label(left, text="Spoken phrase:").pack(anchor="w")
        self.macro_list = tk.Listbox(left, width=26, height=18)
        self.macro_list.pack(fill="y", expand=True)
        self.macro_list.bind("<<ListboxSelect>>", self._macro_selected)
        for k in self.macros:
            self.macro_list.insert("end", k)
        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="New", command=self._macro_new).pack(side="left")
        ttk.Button(btns, text="Delete", command=self._macro_delete).pack(side="left", padx=4)

        right = ttk.Frame(f)
        right.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        ttk.Label(right, text="Trigger phrase:").pack(anchor="w")
        self.macro_key = tk.StringVar()
        ttk.Entry(right, textvariable=self.macro_key).pack(fill="x")
        ttk.Label(right, text="Inserts this text:").pack(anchor="w", pady=(8, 0))
        self.macro_body = tk.Text(right, height=16, wrap="word")
        self.macro_body.pack(fill="both", expand=True)
        ttk.Button(right, text="Update this macro",
                   command=self._macro_update).pack(anchor="e", pady=4)

    def _macro_selected(self, _e):
        sel = self.macro_list.curselection()
        if not sel:
            return
        k = self.macro_list.get(sel[0])
        self.macro_key.set(k)
        self.macro_body.delete("1.0", "end")
        self.macro_body.insert("1.0", self.macros.get(k, ""))

    def _macro_new(self):
        self.macro_key.set("new phrase")
        self.macro_body.delete("1.0", "end")

    def _macro_delete(self):
        sel = self.macro_list.curselection()
        if not sel:
            return
        k = self.macro_list.get(sel[0])
        self.macros.pop(k, None)
        self.macro_list.delete(sel[0])

    def _macro_update(self):
        k = self.macro_key.get().strip().lower()
        body = self.macro_body.get("1.0", "end").rstrip("\n")
        if not k:
            messagebox.showwarning("Macro", "Trigger phrase cannot be empty.")
            return
        existing = list(self.macros.keys())
        self.macros[k] = body
        if k not in existing:
            self.macro_list.insert("end", k)

    # ---- save ------------------------------------------------------------
    def _parse_list(self, key):
        txt = getattr(self, f"_text_{key}").get("1.0", "end")
        return [ln.strip() for ln in txt.splitlines() if ln.strip()]

    def _save(self):
        # commit whatever is currently in the macro / substitution editors so an
        # unsaved new/edited entry isn't lost when the user hits Save directly.
        if self.macro_key.get().strip():
            self._macro_update()
        if self.subs_key.get().strip():
            self._subs_update()
        self.data["input"]["mode"] = self.mode_var.get()
        self.data["input"]["hold_or_toggle"] = self.behavior_var.get()
        self.data["input"]["hotkey"] = self.key_var.get().strip() or "right ctrl"
        self.data["input"]["mic"] = self.mic_binding
        sel_audio = self.audio_var.get()
        self.data["audio_device"] = None if sel_audio == self._AUDIO_DEFAULT else sel_audio
        self.data["inject_method"] = self.inject_var.get()
        self.data["trailing_space"] = bool(self.trailing_var.get())
        self.data["capitalize_first"] = bool(self.capitalize_var.get())
        self.data["debug"] = bool(self.debug_var.get())
        self.data["substitutions"] = self.subs
        self.data["formatting"] = {
            "vitals": bool(self.fmt_vitals.get()),
            "units": bool(self.fmt_units.get()),
            "numbers": bool(self.fmt_numbers.get()),
        }
        cont = dict(self.data.get("continuous", {}))
        cont["enabled"] = bool(self.cont_enabled.get())
        try:
            cont["min_silence_ms"] = int(self.cont_silence.get())
        except (tk.TclError, ValueError):
            pass
        self.data["continuous"] = cont
        self.data["strip_leading"] = self._parse_list("strip_leading")
        self.data["ignore_if_only"] = self._parse_list("ignore_if_only")
        self.data["macros"] = self.macros
        settings_mod.save(self.data)
        self._cleanup_capture()
        if self.on_save:
            self.on_save(self.data)
        self.destroy()

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
        self._build_list_tab(nb, "Strip from start", "strip_leading",
                             "One word per line. Removed from the START of a "
                             "phrase (fixes 'Okay ...' / 'Mm-hmm ...').")
        self._build_list_tab(nb, "Ignore if alone", "ignore_if_only",
                             "One word/phrase per line. Dropped only when it is "
                             "the ENTIRE utterance.")
        self._build_macro_tab(nb)

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
        ttk.Label(f, text="Keyboard key:").grid(row=3, column=0, sticky="w", pady=4)
        self.key_var = tk.StringVar(value=inp.get("hotkey", "right ctrl"))
        ttk.Entry(f, textvariable=self.key_var, width=20).grid(row=3, column=1, sticky="w")
        self.capture_btn = ttk.Button(f, text="Capture key...", command=self._capture_key)
        self.capture_btn.grid(row=3, column=2, sticky="w")

        # HID device
        ttk.Label(f, text="Mic / HID device:").grid(row=4, column=0, sticky="w", pady=4)
        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(f, textvariable=self.device_var,
                                         width=32, state="readonly")
        self.device_combo.grid(row=4, column=1, columnspan=2, sticky="w")
        self._devices = []
        self._refresh_devices(select_current=True)

        rr = ttk.Frame(f)
        rr.grid(row=5, column=1, columnspan=2, sticky="w", pady=4)
        ttk.Button(rr, text="Refresh", command=self._refresh_devices).pack(side="left")
        self.bind_btn = ttk.Button(rr, text="Capture button...",
                                   command=self._capture_button)
        self.bind_btn.pack(side="left", padx=6)

        self.binding_lbl = ttk.Label(f, foreground="#555", text=self._binding_text())
        self.binding_lbl.grid(row=6, column=0, columnspan=3, sticky="w", pady=(2, 6))

        ttk.Label(f, wraplength=580, foreground="#555",
                  text="Pick the device, click Capture button, then press the "
                       "button you want (e.g. the mic's record button). Close "
                       "Dragon first so the button reaches this app.").grid(
            row=7, column=0, columnspan=3, sticky="w", pady=6)

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
        # commit whatever is currently in the macro editor so an unsaved
        # new/edited macro isn't lost when the user hits Save directly.
        if self.macro_key.get().strip():
            self._macro_update()
        self.data["input"]["mode"] = self.mode_var.get()
        self.data["input"]["hold_or_toggle"] = self.behavior_var.get()
        self.data["input"]["hotkey"] = self.key_var.get().strip() or "right ctrl"
        self.data["input"]["mic"] = self.mic_binding
        self.data["strip_leading"] = self._parse_list("strip_leading")
        self.data["ignore_if_only"] = self._parse_list("ignore_if_only")
        self.data["macros"] = self.macros
        settings_mod.save(self.data)
        self._cleanup_capture()
        if self.on_save:
            self.on_save(self.data)
        self.destroy()

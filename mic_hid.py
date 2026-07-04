"""
Generic HID button support (Windows) for Parakeet Dictate.

Nothing device-specific is hardcoded. The GUI lets the user pick a HID device
and press whatever button they want; learn_binding() watches the reports and
works out which byte/bit changed. That binding is stored in settings, and
MicButtonReader replays it at runtime to fire press/release callbacks.
"""

import threading
import time


def _popcount(b):
    return bin(b).count("1")


def list_hid_devices():
    """Return [{vid, pid, product, vendor}] for all HID devices."""
    try:
        from pywinusb import hid
    except Exception as e:
        print(f"[hid] pywinusb unavailable: {e}")
        return []
    out, seen = [], set()
    for d in hid.HidDeviceFilter().get_devices():
        key = (d.vendor_id, d.product_id, d.product_name)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "vid": d.vendor_id,
            "pid": d.product_id,
            "product": (d.product_name or "").strip() or "(unknown)",
            "vendor": (d.vendor_name or "").strip(),
        })
    return out


class ButtonLearner:
    """Collect reports from a device for a short window, then infer a binding.

    Result (or None) lands in .result once .done is set. Binding shape:
        {"byte_index": int, "match": "bitmask", "mask": int}
        {"byte_index": int, "match": "value",   "value": int}
    """

    def __init__(self):
        self.reports = []
        self.done = threading.Event()
        self.result = None

    def start(self, vid, pid, window=5.0):
        threading.Thread(target=self._run, args=(vid, pid, window),
                         daemon=True).start()

    def _run(self, vid, pid, window):
        try:
            from pywinusb import hid
        except Exception as e:
            print(f"[hid] {e}")
            self.done.set()
            return
        devs = hid.HidDeviceFilter(vendor_id=vid, product_id=pid).get_devices()
        if not devs:
            self.done.set()
            return
        dev = devs[0]
        got = threading.Event()

        def on_report(data):
            self.reports.append(bytes(data))
            # once we've seen at least two distinct reports (idle + press),
            # we can infer immediately instead of waiting out the window.
            if len({r for r in self.reports}) >= 2:
                got.set()

        try:
            dev.open()
            dev.set_raw_data_handler(on_report)
            got.wait(timeout=window)
            # brief settle so we also capture the release report if it's mid-flight
            if got.is_set():
                time.sleep(0.25)
        except Exception as e:
            print(f"[hid] learn open failed (is Dragon holding the mic?): {e}")
        finally:
            try:
                dev.close()
            except Exception:
                pass
        self.result = self._infer()
        self.done.set()

    def _infer(self):
        uniq = []
        for r in self.reports:
            if r not in uniq:
                uniq.append(r)
        if len(uniq) < 2:
            return None
        # idle = the resting report (fewest bits set overall)
        idle = min(uniq, key=lambda r: sum(_popcount(x) for x in r))
        # prefer a bit that turns ON when pressed
        for r in uniq:
            if r == idle:
                continue
            n = min(len(r), len(idle))
            for i in range(n):
                newly = r[i] & (~idle[i] & 0xFF)
                if newly:
                    return {"byte_index": i, "match": "bitmask", "mask": newly}
        # fallback: a byte that changes to a distinct value
        for r in uniq:
            if r == idle:
                continue
            n = min(len(r), len(idle))
            for i in range(n):
                if r[i] != idle[i]:
                    return {"byte_index": i, "match": "value", "value": r[i]}
        return None


def describe(binding):
    if not binding:
        return "none"
    i = binding.get("byte_index")
    if binding.get("match") == "value":
        return f"byte {i} = 0x{binding['value']:02x}"
    return f"byte {i} bit 0x{binding['mask']:02x}"


class MicButtonReader:
    """Open a HID device and fire on_press/on_release for a learned binding."""

    def __init__(self, vid, pid, binding, on_press, on_release):
        self.vid = vid
        self.pid = pid
        self.binding = binding
        self.on_press = on_press
        self.on_release = on_release
        self._dev = None
        self._down = False
        self._ok = False

    def available(self):
        return self._ok

    def _pressed(self, data):
        i = self.binding.get("byte_index", 0)
        if i >= len(data):
            return False
        if self.binding.get("match") == "value":
            return data[i] == self.binding.get("value")
        return bool(data[i] & self.binding.get("mask", 0))

    def _on_report(self, data):
        pressed = self._pressed(data)
        if pressed and not self._down:
            self._down = True
            try:
                self.on_press()
            except Exception as e:
                print(f"[mic] on_press: {e}")
        elif not pressed and self._down:
            self._down = False
            try:
                self.on_release()
            except Exception as e:
                print(f"[mic] on_release: {e}")

    def start(self):
        try:
            from pywinusb import hid
        except Exception as e:
            print(f"[mic] pywinusb unavailable: {e}")
            return False
        if not self.binding:
            print("[mic] no button binding set")
            return False
        devs = hid.HidDeviceFilter(vendor_id=self.vid, product_id=self.pid).get_devices()
        if not devs:
            print(f"[mic] device 0x{self.vid:04x}/0x{self.pid:04x} not found")
            return False
        self._dev = devs[0]
        try:
            self._dev.open()
            self._dev.set_raw_data_handler(self._on_report)
            self._ok = True
            print(f"[mic] armed: {self._dev.product_name} ({describe(self.binding)})")
            return True
        except Exception as e:
            print(f"[mic] open failed (is Dragon holding it?): {e}")
            self._dev = None
            return False

    def stop(self):
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:
                pass
            self._dev = None
        self._ok = False

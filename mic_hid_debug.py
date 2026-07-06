"""
Nuance mic HID diagnostic (Windows).

Run in two steps.

STEP 1 - list every HID device so we can spot the mic:
    pip install pywinusb
    python mic_hid_debug.py

    Look for a Nuance / Dictaphone / PowerMic entry. The vendor id is very
    often 0x0554 (Dictaphone/Nuance). Note its vendor_id and product_id.

STEP 2 - watch the raw button reports (replace the id you found):
    python mic_hid_debug.py --vid 0x0554
    (optionally add --pid 0xXXXX if several devices share the vendor id)

    Then press the RECORD button (and the others) a few times. Each line is a
    raw HID report. Copy several lines - especially the ones that change when
    you press vs release record - and send them back. That byte pattern is all
    we need to bind the record button as a trigger source.
"""

import sys
import time
import argparse

try:
    from pywinusb import hid
except Exception as e:
    print("Could not import pywinusb. Install it first:\n    pip install pywinusb")
    print(f"(import error: {e})")
    sys.exit(1)


def list_devices():
    devices = hid.HidDeviceFilter().get_devices()
    if not devices:
        print("No HID devices found.")
        return
    print(f"{'VID':>7} {'PID':>7}  product / vendor")
    print("-" * 60)
    seen = set()
    for d in devices:
        key = (d.vendor_id, d.product_id, d.product_name)
        if key in seen:
            continue
        seen.add(key)
        vname = (d.vendor_name or "").strip()
        pname = (d.product_name or "").strip()
        print(f"0x{d.vendor_id:04x} 0x{d.product_id:04x}  {pname}  [{vname}]")
    print("\nSpot the Nuance / Dictaphone / PowerMic row, then re-run with"
          "\n    python mic_hid_debug.py --vid 0xVVVV  (add --pid 0xPPPP if needed)")


def watch(vid, pid):
    flt = hid.HidDeviceFilter(vendor_id=vid) if pid is None \
        else hid.HidDeviceFilter(vendor_id=vid, product_id=pid)
    devices = flt.get_devices()
    if not devices:
        print(f"No device matched vid=0x{vid:04x}"
              + (f" pid=0x{pid:04x}" if pid else ""))
        return

    last = {}

    def make_handler(tag):
        def handler(data):
            # print only when the report actually changes, to cut noise
            b = bytes(data)
            if last.get(tag) == b:
                return
            last[tag] = b
            print(f"[{tag}] " + " ".join(f"{x:02x}" for x in b))
        return handler

    opened = []
    for i, dev in enumerate(devices):
        try:
            dev.open()
            dev.set_raw_data_handler(make_handler(i))
            opened.append(dev)
            print(f"Opened: 0x{dev.vendor_id:04x} 0x{dev.product_id:04x} "
                  f"{dev.product_name}")
        except Exception as e:
            print(f"Could not open a matching device: {e}")

    if not opened:
        return
    print("\nPress the RECORD button (and others). Ctrl+C to stop.\n")
    try:
        while any(d.is_plugged() for d in opened):
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        for d in opened:
            try:
                d.close()
            except Exception:
                pass


# Values tried per data byte: every single bit, then all bits. Covers both
# bit-flag LEDs and simple on/off command bytes.
LED_VALUES = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0xFF]


def _report_len(report):
    """Byte length of a HID report (incl. the leading report-id byte). pywinusb
    doesn't expose it cleanly, so try the raw buffer, the private field, then a
    harmless all-zero set_raw_data probe."""
    try:
        d = report.get_raw_data()
        if d:
            return len(d)
    except Exception:
        pass
    v = getattr(report, "_HidReport__raw_report_size", None)
    if isinstance(v, int) and v > 0:
        return v
    for size in range(1, 65):
        try:
            report.set_raw_data([0] * size)
            return size
        except Exception:
            continue
    return None


def _zero(report, size, rid):
    buf = [0] * size
    if size > 1:
        buf[0] = rid
    try:
        report.set_raw_data(buf)
        report.send()
    except Exception:
        pass


def find_led(vid, pid, hold=1.2):
    """Deep probe for the LED control report. Walks every HID interface of the
    (composite) device, every output and feature report, and drives each data
    byte across every single bit plus 0xFF, then all bytes high together.

    Each attempt prints a numbered line BEFORE it holds the value on, so when
    the red LED lights, the last [#N] printed is the winner. Ctrl+C to stop
    early. Safe: one report at a time, always zeroed back; unplug/replug if the
    device acts odd.
    """
    flt = hid.HidDeviceFilter(vendor_id=vid) if pid is None \
        else hid.HidDeviceFilter(vendor_id=vid, product_id=pid)
    devices = flt.get_devices()
    if not devices:
        print(f"No device matched vid=0x{vid:04x}"
              + (f" pid=0x{pid:04x}" if pid else ""))
        return

    print(f"{len(devices)} HID interface(s) match. Probing each. WATCH THE LED; "
          "note the [#N] that lights it.\n")
    n = 0
    for di, dev in enumerate(devices):
        try:
            dev.open()
        except Exception as e:
            print(f"[iface {di}] could not open: {e}")
            continue
        try:
            path = (dev.device_path or "")[-40:]
            reports = []
            try:
                reports += [("output", r) for r in dev.find_output_reports()]
            except Exception:
                pass
            try:
                reports += [("feature", r) for r in dev.find_feature_reports()]
            except Exception:
                pass
            print(f"=== iface {di}: 0x{dev.vendor_id:04x}/0x{dev.product_id:04x} "
                  f"{dev.product_name} | {len(reports)} writable report(s) | ...{path}")
            for kind, report in reports:
                size = _report_len(report)
                rid = report.report_id
                if not size:
                    print(f"  {kind} id={rid}: couldn't determine size; skipping")
                    continue
                # data bytes are everything after the leading report-id byte
                data_idx = list(range(1, size)) if size > 1 else [0]
                print(f"  {kind} report id={rid} ({size} bytes), sweeping "
                      f"bytes {data_idx}")
                for i in data_idx:
                    for val in LED_VALUES:
                        n += 1
                        buf = [0] * size
                        if size > 1:
                            buf[0] = rid
                        buf[i] = val
                        try:
                            report.set_raw_data(buf)
                            report.send()
                        except Exception as e:
                            print(f"  [#{n}] id={rid} byte[{i}]=0x{val:02x} "
                                  f"send failed: {e}")
                            continue
                        print(f"  [#{n}] {kind} id={rid} byte[{i}]=0x{val:02x} "
                              f"<-- LED?")
                        time.sleep(hold)
                        _zero(report, size, rid)
                        time.sleep(0.15)
                # all data bytes high at once (multi-byte command LEDs)
                if len(data_idx) > 1:
                    n += 1
                    buf = [0] * size
                    buf[0] = rid
                    for i in data_idx:
                        buf[i] = 0xFF
                    try:
                        report.set_raw_data(buf)
                        report.send()
                        print(f"  [#{n}] {kind} id={rid} ALL bytes=0xFF <-- LED?")
                        time.sleep(hold)
                    except Exception as e:
                        print(f"  [#{n}] all-0xFF send failed: {e}")
                    _zero(report, size, rid)
                    time.sleep(0.15)
        finally:
            try:
                dev.close()
            except Exception:
                pass
    print(f"\nDone ({n} attempts). Tell me the [#N] that lit the LED — that "
          "pins the interface, report id, byte, and value.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vid", help="vendor id, e.g. 0x0554")
    ap.add_argument("--pid", help="product id, e.g. 0x1001")
    ap.add_argument("--leds", action="store_true",
                    help="probe output/feature reports to find the LED control byte")
    ap.add_argument("--hold", type=float, default=1.2,
                    help="seconds to hold each value on during --leds (default 1.2)")
    args = ap.parse_args()

    if not args.vid:
        list_devices()
        return
    vid = int(args.vid, 16) if args.vid.lower().startswith("0x") else int(args.vid)
    pid = None
    if args.pid:
        pid = int(args.pid, 16) if args.pid.lower().startswith("0x") else int(args.pid)
    if args.leds:
        find_led(vid, pid, hold=args.hold)
    else:
        watch(vid, pid)


if __name__ == "__main__":
    main()

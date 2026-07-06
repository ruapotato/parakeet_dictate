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


def _report_size(report):
    """pywinusb doesn't expose a report's byte length directly; find it by
    probing which all-zero buffer set_raw_data accepts (harmless)."""
    for size in range(1, 33):
        try:
            report.set_raw_data([0] * size)
            return size
        except Exception:
            continue
    return None


def find_led(vid, pid):
    """Brute-force the LED control report. Enumerates every output and feature
    report on the device and flashes each byte high one at a time; watch the
    mic and note the step where the red LED lights. That report id + byte index
    is all we need to drive the LED from Parakeet.

    Safe: it only sets one byte at a time and zeroes it back. If the device ever
    acts oddly, just unplug/replug it.
    """
    flt = hid.HidDeviceFilter(vendor_id=vid) if pid is None \
        else hid.HidDeviceFilter(vendor_id=vid, product_id=pid)
    devices = flt.get_devices()
    if not devices:
        print(f"No device matched vid=0x{vid:04x}"
              + (f" pid=0x{pid:04x}" if pid else ""))
        return

    for dev in devices:
        try:
            dev.open()
        except Exception as e:
            print(f"Could not open device: {e}")
            continue
        try:
            reports = []
            try:
                reports += [("output", r) for r in dev.find_output_reports()]
            except Exception:
                pass
            try:
                reports += [("feature", r) for r in dev.find_feature_reports()]
            except Exception:
                pass
            if not reports:
                print(f"0x{dev.vendor_id:04x}/0x{dev.product_id:04x} "
                      f"{dev.product_name}: no writable reports on this interface")
                continue
            print(f"\n=== 0x{dev.vendor_id:04x}/0x{dev.product_id:04x} "
                  f"{dev.product_name}: {len(reports)} writable report(s) ===")
            for kind, report in reports:
                size = _report_size(report)
                if not size:
                    continue
                rid = report.report_id
                print(f"\n--- {kind} report id={rid} ({size} bytes) --- "
                      "WATCH THE LED")
                for i in range(size):
                    buf = [0] * size
                    buf[i] = 0xFF
                    try:
                        report.set_raw_data(buf)
                        report.send()
                    except Exception as e:
                        print(f"  byte[{i}] send failed: {e}")
                        continue
                    print(f"  {kind} id={rid} byte[{i}]=0xFF  <-- LED on now?")
                    time.sleep(1.3)
                    try:
                        report.set_raw_data([0] * size)
                        report.send()
                    except Exception:
                        pass
                    time.sleep(0.3)
        finally:
            try:
                dev.close()
            except Exception:
                pass
    print("\nDone. Tell me the line that lit the LED (kind, report id, byte).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vid", help="vendor id, e.g. 0x0554")
    ap.add_argument("--pid", help="product id, e.g. 0x1001")
    ap.add_argument("--leds", action="store_true",
                    help="probe output/feature reports to find the LED control byte")
    args = ap.parse_args()

    if not args.vid:
        list_devices()
        return
    vid = int(args.vid, 16) if args.vid.lower().startswith("0x") else int(args.vid)
    pid = None
    if args.pid:
        pid = int(args.pid, 16) if args.pid.lower().startswith("0x") else int(args.pid)
    if args.leds:
        find_led(vid, pid)
    else:
        watch(vid, pid)


if __name__ == "__main__":
    main()

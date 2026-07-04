"""Segmenter state-machine tests (scripted VAD, no model needed).
Run: python test_vad.py"""
import numpy as np
import vad


class FakeVAD:
    def __init__(self, probs):
        self.probs = list(probs)
        self.i = 0

    def reset(self):
        self.i = 0

    def prob(self, frame):
        p = self.probs[self.i] if self.i < len(self.probs) else 0.0
        self.i += 1
        return p


F = np.ones(vad.FRAME_SAMPLES, dtype=np.float32)


def drive(probs, **kw):
    seg = vad.Segmenter(FakeVAD(probs), speech_pad_ms=0, **kw)
    out = []
    for _ in probs:
        r = seg.push(F)
        if r is not None:
            out.append(r)
    tail = seg.flush()
    if tail is not None:
        out.append(tail)
    return out


def run():
    fails = 0

    def check(name, cond):
        nonlocal fails
        fails += not cond
        print(f"[{'ok' if cond else 'XX'}] {name}")

    # 1. one burst then silence -> exactly one natural segment
    out = drive([0.9] * 5 + [0.0] * 8, min_silence_ms=100, max_segment_s=99)
    check("single burst -> 1 segment", len(out) == 1 and out[0][1] is False)

    # 2. two bursts separated by silence -> two segments
    out = drive([0.9] * 4 + [0.0] * 8 + [0.9] * 4 + [0.0] * 8,
                min_silence_ms=100, max_segment_s=99)
    check("two bursts -> 2 segments", len(out) == 2)

    # 3. long unbroken speech -> at least one FORCED cut, no dropped audio
    out = drive([0.9] * 40, min_silence_ms=9999, max_segment_s=0.2)
    forced = [o for o in out if o[1] is True]
    check("long speech -> forced cut(s)", len(forced) >= 1)
    check("long speech -> tail flushed too", len(out) >= 2)

    # 4. pure silence -> nothing emitted
    out = drive([0.0] * 20, min_silence_ms=100, max_segment_s=99)
    check("silence -> no segments", len(out) == 0)

    # 5. segment audio is real float32 with sane length
    out = drive([0.9] * 6 + [0.0] * 8, min_silence_ms=100, max_segment_s=99)
    seg = out[0][0]
    check("segment is float32 ndarray", isinstance(seg, np.ndarray) and seg.dtype == np.float32)
    check("segment length > 0", seg.size > 0)

    print("\n" + ("ALL PASS" if not fails else f"{fails} FAILURES"))
    return fails


if __name__ == "__main__":
    raise SystemExit(1 if run() else 0)

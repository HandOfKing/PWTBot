"""Teach the Remaining-counter digit reader from a clip whose Remaining values are known.

    python tools/harvest_remaining_digits.py <video> <truth.csv> [--per-digit 2] [--harvest-before 34]
    python tools/harvest_remaining_digits.py <video> <truth.csv> --check-only

truth.csv: start_s,end_s,value -- the value the counter shows over [start_s, end_s] of the clip
(tests/fixtures/remaining_vp13.csv is an example; read it off the frames). Leave a margin at the
edges of each interval: the digit animates when it changes.

A glyph is saved to <templates>/digits_remaining/<digit>_<n>.png only when the current library
CANNOT read its frame (None), the frame splits into exactly as many glyphs as the true value has
digits (or, for 11, is the single blob two touching 1s make: saved as an "11" template), and
the frame lies before --harvest-before, so the rest of the clip stays held out. At most
--per-digit new templates per digit, the worst-read first.

Afterwards every frame inside every truth interval is re-read and reported as correct / blank /
WRONG. WRONG must be 0: a wrong Remaining value is a phantom or a lost elimination.
"""
import argparse, csv, glob, os, sys
from pathlib import Path
import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pwt import profiles                                    # noqa: E402
from pwt.readers.counters import CounterReader               # noqa: E402


def load_truth(path):
    with open(path, encoding="utf-8-sig") as fh:
        return [(float(r["start_s"]), float(r["end_s"]), int(r["value"])) for r in csv.DictReader(fh)]


def frames(video, truth, step=1):
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    for lo, hi, v in truth:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(lo * fps)))
        i = int(round(lo * fps))
        while i / fps <= hi:
            ok, f = cap.read()
            if not ok: break
            if (i - int(round(lo * fps))) % step == 0:
                yield i / fps, v, f
            i += 1


def check(reader, video, truth, box):
    x0, y0, x1, y1 = box
    n = right = blank = 0
    wrong = []
    for t, v, f in frames(video, truth):
        got, _ = reader.read(f[y0:y1, x0:x1])
        n += 1
        if got is None: blank += 1
        elif got == v: right += 1
        else: wrong.append((round(t, 2), v, got))
    return n, right, blank, wrong


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("truth")
    ap.add_argument("--profile", default=profiles.DEFAULT)
    ap.add_argument("--per-digit", type=int, default=2)
    ap.add_argument("--harvest-before", type=float, default=float("inf"))
    ap.add_argument("--check-only", action="store_true")
    a = ap.parse_args(argv)
    prof = profiles.load(a.profile)
    reader = CounterReader(prof).remaining
    truth = load_truth(a.truth)
    box = prof["remaining_box"]
    x0, y0, x1, y1 = box

    if not a.check_only:
        cands = {}
        for t, v, f in frames(a.video, [r for r in truth if r[0] < a.harvest_before], step=3):
            if t >= a.harvest_before: continue
            cell = f[y0:y1, x0:x1]
            got, sc = reader.read(cell)
            if got is not None: continue
            gs = reader.glyphs(cell)
            if not gs: continue
            labels = list(str(v))
            if len(gs) == 1 and len(labels) == 2 and labels[0] == labels[1] == "1":
                labels = ["11"]          # "11": the two thin 1s often touch at the top and form ONE blob
            if len(gs) != len(labels): continue
            for g, ch in zip(gs, labels):
                d, s = reader.classify(g)
                if d == ch and s >= reader.min_score: continue          # this glyph is fine
                cands.setdefault(ch, []).append((s, t, g))
        os.makedirs(reader.folder, exist_ok=True)
        for ch, lst in sorted(cands.items()):
            added = 0
            for s, t, g in sorted(lst, key=lambda c: c[0]):
                if added >= a.per_digit: break
                d, s_now = reader.classify(g)
                if d == ch and s_now >= reader.min_score: continue      # covered by one just added
                k = len(glob.glob(os.path.join(reader.folder, f"{ch}_*.png")))
                cv2.imwrite(os.path.join(reader.folder, f"{ch}_{k}.png"), g)
                reader.reload()
                added += 1
                print(f"  added {ch}_{k}.png from {t:.2f}s (was {d} at {s:.2f})")

    n, right, blank, wrong = check(reader, a.video, truth, box)
    held = [r for r in truth if r[0] >= a.harvest_before]
    print(f"all intervals: {n} frames  correct {right}  blank {blank}  WRONG {len(wrong)}")
    if held and a.harvest_before != float("inf"):
        hn, hr, hb, hw = check(reader, a.video, held, box)
        print(f"held out (from {a.harvest_before:g}s): {hn} frames  correct {hr}  blank {hb}  WRONG {len(hw)}")
    for w in wrong[:20]: print("  WRONG", w)
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())

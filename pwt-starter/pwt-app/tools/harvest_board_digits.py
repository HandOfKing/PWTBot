"""Teach the scoreboard digit reader from a board whose true values are known.

    python tools/harvest_board_digits.py <video> <truth.csv> [--profile P] [--at 1,3,5,7] [--per-digit 4]
    python tools/harvest_board_digits.py <video> <truth.csv> --check-only

truth.csv: `player` plus one column per profile `scoreboard.value_cols` name, values as shown on
screen (read them off a paused frame; tests/fixtures/match_board_vp11.csv is an example).

A glyph is saved to <templates>/digits_board/<digit>_<n>.png only when the cell splits into exactly
as many glyphs as the true value has digits, at most --per-digit new ones per digit, the ones the
current library reads worst first, skipping near-copies of templates already there.

Afterwards every truth cell is re-read on every 0.5 s of the video and reported as correct / blank
(None: unknown glyph, flagged downstream) / WRONG. WRONG must be 0 -- a wrong number is worse than a
blank one. Check on a DIFFERENT board than the one harvested from before trusting the result.
"""
import argparse, csv, os, sys
from pathlib import Path
import cv2, numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pwt import profiles                                    # noqa: E402
from pwt.readers.counters import CounterReader               # noqa: E402
from pwt.readers.screens import ScreenReader                  # noqa: E402
from pwt.readers.digits import _norm                          # noqa: E402


def load_truth(path):
    with open(path, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    return {r["player"]: {k: int(v) for k, v in r.items() if k != "player" and v != ""} for r in rows}


def frames(video, times):
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    for t in times:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps)))
        ok, f = cap.read()
        if ok: yield t, f
    cap.release()


def cells(S, frame, truth):
    """(player, column, true value, cell image) for every truth cell visible on this frame."""
    for r in S.read_rows(frame, list(truth)):
        if r["name"] in truth and r["conf"] >= 0.75:
            for col, (a, b) in S.value_cols.items():
                if col in truth[r["name"]]:
                    yield r["name"], col, truth[r["name"]][col], frame[r["y"] - 20:r["y"] + 20, a:b]


def check(S, video, truth, step=0.5):
    dur = cv2.VideoCapture(str(video)).get(cv2.CAP_PROP_FRAME_COUNT) / 30.0
    ok = blank = wrong = 0
    wrongs, seen = [], set()
    for t, f in frames(video, np.arange(0, dur, step)):
        for name, col, v, cell in cells(S, f, truth):
            got = S.digits.read(cell)[0]
            seen.add((name, col))
            if got is None: blank += 1
            elif got == v: ok += 1
            else:
                wrong += 1; wrongs.append(f"{t:.1f}s {name} {col}: read {got}, true {v}")
    return ok, blank, wrong, wrongs, len(seen)


def harvest(S, video, truth, at, per_digit):
    D = S.digits
    cands = {}
    for t, f in frames(video, at):
        for name, col, v, cell in cells(S, f, truth):
            gs = D.glyphs(cell)
            if len(gs) != len(str(v)): continue
            for g, ch in zip(gs, str(v)):
                d, sc = D.classify(g) if D.templates else (None, -1.0)
                cands.setdefault(ch, []).append((sc if d == ch else -1.0, g))
    added = {}
    for ch, lst in sorted(cands.items()):
        lst.sort(key=lambda c: c[0])                         # worst-read first
        mine = [t for d, t in D.templates if d == ch]
        n = 0
        for sc, g in lst:
            if n >= per_digit: break
            v = _norm(g)
            if any(float((t * v).mean()) >= 0.97 for t in mine): continue   # near-copy
            k = len([p for p in os.listdir(D.folder) if p.startswith(f"{ch}_")])
            cv2.imwrite(os.path.join(D.folder, f"{ch}_{k}.png"), g)
            mine.append(v); n += 1
        added[ch] = n
    D.reload()
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("truth")
    ap.add_argument("--profile", default="gameloop-spectator-6v6-1080p")
    ap.add_argument("--at", default="1,3,5,7", help="seconds to harvest from")
    ap.add_argument("--per-digit", type=int, default=4)
    ap.add_argument("--check-only", action="store_true")
    a = ap.parse_args()
    P = profiles.load(a.profile)
    S = ScreenReader(P, CounterReader(P))
    truth = load_truth(a.truth)
    if not a.check_only:
        print("added:", harvest(S, a.video, truth, [float(x) for x in a.at.split(",")], a.per_digit))
    ok, blank, wrong, wrongs, n = check(S, a.video, truth)
    print(f"{n} distinct cells seen; reads: {ok} correct, {blank} blank, {wrong} WRONG")
    for w in wrongs[:20]: print("  ", w)
    sys.exit(1 if wrong else 0)


if __name__ == "__main__":
    main()

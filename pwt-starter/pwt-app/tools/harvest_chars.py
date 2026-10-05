"""One-time dev tool: build the character template library from a clip with a known roster.

Usage:
    python tools/harvest_chars.py --clip clips/2026-10-01\ 23-12-52.mkv \
        --roster RGODxEMPEROR KG696969 PARABloodthirs TheWolverine \
                 Sarthakkkd Strike333 StarJohnnysins Makjets69 \
                 KhajwaKILL3R OmkarKurhade WonderWoman888 TrishaSingh \
                 InnocentDevil enriquelatin BruceWayne

How it works:
  1. Scan every 3rd frame (for speed) with the FeedReader to find kill-feed rows.
  2. Track lines like LineTracker does (simplified).
  3. For each stable line, try to match its glyph count against roster names.
  4. When a unique match is found OR Tesseract confirms a roster match,
     harvest the character templates.
  5. Templates are saved to pwt/templates/chars_feed/.

After running, Tesseract is no longer needed at runtime.
"""
import argparse, sys
from pathlib import Path
import cv2, numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pwt import profiles
from pwt.readers.feed import FeedReader
from pwt.readers.chars import CharReader, _label
from pwt.readers import names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True)
    ap.add_argument("--roster", nargs="+", required=True)
    ap.add_argument("--fps", type=float, default=12)
    ap.add_argument("--profile", default="gameloop-windowed-1080p")
    ap.add_argument("--out", default=str(ROOT / "pwt" / "templates" / "chars_feed"))
    ap.add_argument("--max-per-char", type=int, default=6,
                    help="max template variants per character")
    a = ap.parse_args()

    prof = profiles.load(a.profile)
    feed = FeedReader(prof)
    reader = CharReader(a.out)

    # Build a length-to-name index for glyph-count matching
    by_len = {}
    for name in a.roster:
        by_len.setdefault(len(name), []).append(name)

    cap = cv2.VideoCapture(a.clip)
    if not cap.isOpened():
        print(f"Cannot open {a.clip}"); return
    vid_fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(vid_fps / a.fps))          # process at target fps
    print(f"Clip: {a.clip}  {vid_fps} fps  {total} frames  step={step}")
    print(f"Roster ({len(a.roster)}): {a.roster}")
    print(f"Output: {a.out}\n")

    # Track lines across frames (simplified version of LineTracker)
    active_lines = []       # each: {icons, y, kw, vw, last_t, k_mask, v_mask, seen, harvested}
    harvested_total = 0
    chars_seen = set()
    frame_no = 0

    while True:
        ok = cap.grab()
        if not ok:
            break
        frame_no += 1
        if frame_no % step != 0:
            continue
        ok, frame = cap.retrieve()
        if not ok:
            break
        t = frame_no / vid_fps

        rows = feed.rows(frame)
        used = set()
        for r in rows:
            kw = r.k_span[1] - r.k_span[0]
            vw = r.v_span[1] - r.v_span[0]
            # try to match to an existing line
            best, best_d = None, 1e9
            for li, line in enumerate(active_lines):
                if li in used or line["icons"] != r.icons:
                    continue
                dy = r.y - line["y"]
                if abs(dy) <= 60 and abs(kw - line["kw"]) <= 8 and abs(vw - line["vw"]) <= 8:
                    d = abs(dy) + abs(kw - line["kw"]) + abs(vw - line["vw"])
                    if d < best_d:
                        best, best_d = li, d
            if best is not None:
                line = active_lines[best]
                line.update(y=r.y, kw=kw, vw=vw, last_t=t, seen=line["seen"] + 1)
                # keep the best mask (from 2nd+ sighting, not the slide-in frame)
                if line["seen"] >= 2:
                    line["k_mask"] = r.k_mask
                    line["v_mask"] = r.v_mask
                used.add(best)
            else:
                active_lines.append(dict(
                    icons=r.icons, y=r.y, kw=kw, vw=vw,
                    first_t=t, last_t=t, seen=1,
                    k_mask=r.k_mask, v_mask=r.v_mask,
                    harvested=False))

        # check expired lines (gone for > 1s) and try to harvest
        still_active = []
        for line in active_lines:
            if t - line["last_t"] > 1.0 and not line["harvested"] and line["seen"] >= 3:
                n = _try_harvest(reader, line, a.roster, by_len, a.max_per_char)
                harvested_total += n
                if n:
                    for ch in set("".join(a.roster)):
                        if _has_template(a.out, ch):
                            chars_seen.add(ch)
                line["harvested"] = True
            if t - line["last_t"] <= 2.0:
                still_active.append(line)
        active_lines = still_active

        if frame_no % (step * 120) == 0:
            print(f"  {t:7.1f}s  harvested {harvested_total} glyphs  "
                  f"unique chars: {len(chars_seen)}")

    # flush remaining
    for line in active_lines:
        if not line["harvested"] and line["seen"] >= 3:
            harvested_total += _try_harvest(reader, line, a.roster, by_len, a.max_per_char)

    cap.release()

    # report
    reader.reload()
    print(f"\nDone. {harvested_total} glyph templates saved to {a.out}")
    print(f"Unique characters with templates: {len(reader.templates)} entries")

    # check coverage
    all_chars = set("".join(a.roster))
    covered = set()
    for ch, _ in reader.templates:
        covered.add(ch)
    missing = all_chars - covered
    if missing:
        print(f"WARNING: missing templates for: {sorted(missing)}")
    else:
        print("Full coverage of all roster characters!")


def _try_harvest(reader, line, roster, by_len, max_per_char):
    """Try to identify the killer/victim names and harvest their glyphs."""
    total = 0
    for role, mask in [("killer", line["k_mask"]), ("victim", line["v_mask"])]:
        if mask is None:
            continue
        gs = reader.glyphs(mask)
        n_glyphs = len(gs)
        if n_glyphs < 3:
            continue

        name = None

        # Strategy 1: unique glyph-count match
        candidates = by_len.get(n_glyphs, [])
        if len(candidates) == 1:
            name = candidates[0]

        # Strategy 2: Tesseract + roster fuzzy match
        if name is None:
            raw = names.ocr_mask(mask)
            if raw:
                best_name, best_score = names.match(raw, roster)
                if best_name and best_score >= 0.55 and len(best_name) == n_glyphs:
                    name = best_name

        # Strategy 3: try existing templates + roster match
        if name is None and reader.ready:
            text = reader.read(mask)
            if text:
                best_name, best_score = names.match(text, roster)
                if best_name and best_score >= 0.55 and len(best_name) == n_glyphs:
                    name = best_name

        if name and len(name) == n_glyphs:
            saved = reader.harvest(mask, name, max_per_char)
            if saved:
                total += saved
                print(f"  harvested {role:>6} '{name}': {saved} new glyphs "
                      f"({n_glyphs} total chars)")

    return total


def _has_template(folder, ch):
    import glob, os
    lab = _label(ch)
    return bool(glob.glob(os.path.join(str(folder), f"{lab}_*.png")))


if __name__ == "__main__":
    main()

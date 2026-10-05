"""One-time dev tool: build the kill-feed character template library from a clip
with a known roster.  After running, Tesseract is no longer needed at runtime.

Usage:
    python tools/harvest_chars.py --clip clips/match.mkv \
        --profile gameloop-spectator-6v6-1080p \
        --roster Sarthakkkd RGODxEMPEROR KG696969 ...

How it works:
  1. Sample the clip and find kill-feed rows with FeedReader.
  2. Track each row across frames (a simplified LineTracker) and keep the mask
     from the 2nd+ sighting, so half-rendered slide-in frames are never harvested.
  3. Split the row mask into words by x-gap.  The first word is the killer, the
     last is the victim; anything between is icons and is ignored.
  4. Identify each word with **Tesseract plus roster fuzzy matching**, and only
     accept it when the score clears --min-score AND the roster name's length
     equals the word's glyph count.  Equal length is what makes the glyph->char
     alignment sound; chars.harvest() refuses the pair otherwise.
  5. Crop the row mask to that word's columns and harvest its glyphs.

Why Tesseract and not our own templates: this is the bootstrap.  Reading the
names with the library we are building would let one mislabelled glyph seed more
mislabelled glyphs.  names._tess_mask is called directly for the same reason --
names.ocr_mask would start preferring CharReader as soon as it had 26 entries.

--report-only runs the whole identification pass and prints what it *would*
harvest, writing nothing.  Use it before committing to a library.
"""
import argparse, sys
from collections import Counter
from pathlib import Path
import cv2, numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pwt import profiles
from pwt.readers.feed import FeedReader
from pwt.readers.chars import CharReader, _label
from pwt.readers import names


def words_of(reader, mask01, gap_px=10):
    """Group row-mask components into words. Returns [(x0, x1, n_glyphs)]."""
    comps = reader._components(mask01)
    if not comps:
        return []
    groups, cur = [], [comps[0]]
    for c in comps[1:]:
        prev = cur[-1]
        if c["x"] - (prev["x"] + prev["w"]) > gap_px:
            groups.append(cur)
            cur = [c]
        else:
            cur.append(c)
    groups.append(cur)
    out = []
    for g in groups:
        x0 = min(c["x"] for c in g)
        x1 = max(c["x"] + c["w"] for c in g)
        out.append((x0, x1, len(g)))
    return out


def identify(raw_tokens, n_glyphs, roster, min_score, allow_length_guess=False):
    """Best roster name for a word, or None.

    Requires a fuzzy score over min_score AND an exact length match, since the
    harvester aligns glyph i to name[i].

    The length-only fallback is off by default. It fires whenever exactly one
    roster name has the right length, which cannot tell a real read from a
    partially-detected longer name, and a wrong label here seeds wrong glyphs
    for every character in that name.
    """
    best = None
    for tok in raw_tokens:
        if not tok:
            continue
        name, score = names.match(tok, roster)
        if name and score >= min_score and len(name) == n_glyphs:
            if best is None or score > best[1]:
                best = (name, score)
    if best:
        return best
    if allow_length_guess:
        cands = [n for n in roster if len(n) == n_glyphs]
        if len(cands) == 1:
            return (cands[0], 0.0)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True)
    ap.add_argument("--roster", nargs="+", required=True)
    ap.add_argument("--fps", type=float, default=12)
    ap.add_argument("--profile", default="gameloop-spectator-6v6-1080p")
    ap.add_argument("--out", default=str(ROOT / "pwt" / "templates" / "chars_feed"))
    ap.add_argument("--max-per-char", type=int, default=6)
    ap.add_argument("--min-score", type=float, default=0.70,
                    help="roster match score required to trust a label (stricter "
                         "than runtime 0.55: a mislabelled template is costly)")
    ap.add_argument("--report-only", action="store_true",
                    help="identify and report, write nothing")
    ap.add_argument("--use-templates", action="store_true",
                    help="second pass: also read with the templates harvested so "
                         "far, to identify lines Tesseract could not")
    ap.add_argument("--allow-length-guess", action="store_true",
                    help="accept a name purely because it is the only roster "
                         "entry of that length (unsafe, off by default)")
    ap.add_argument("--keep-sightings", type=int, default=4,
                    help="how many frames of each line to read")
    a = ap.parse_args()

    prof = profiles.load(a.profile)
    feed = FeedReader(prof)
    reader = CharReader(a.out)

    cap = cv2.VideoCapture(a.clip)
    if not cap.isOpened():
        print(f"Cannot open {a.clip}")
        return 1
    vid_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(round(vid_fps / a.fps)))
    print(f"Clip: {a.clip}  {vid_fps} fps  {total} frames  step={step}")
    print(f"Profile: {a.profile}   roster: {len(a.roster)} names")
    print(f"Output: {a.out}{'  (REPORT ONLY)' if a.report_only else ''}\n")

    active, frame_no = [], 0
    harvested_total = 0
    id_counts = Counter()
    rows_seen = 0
    unidentified = 0

    while True:
        if not cap.grab():
            break
        frame_no += 1
        if frame_no % step:
            continue
        ok, frame = cap.retrieve()
        if not ok:
            break
        t = frame_no / vid_fps

        rows = feed.rows(frame)
        rows_seen += len(rows)
        used = set()
        for r in rows:
            ink = int(r.row_mask.sum())
            best, best_d = None, 1e9
            for li, ln in enumerate(active):
                if li in used or ln["icons"] != r.icons:
                    continue
                dy = abs(r.y - ln["y"])
                di = abs(ink - ln["ink"]) / max(ln["ink"], 1)
                if dy <= 60 and di <= 0.25 and dy + di < best_d:
                    best, best_d = li, dy + di
            if best is not None:
                ln = active[best]
                ln.update(y=r.y, ink=ink, last_t=t, seen=ln["seen"] + 1)
                if ln["seen"] >= 2 and len(ln["masks"]) < a.keep_sightings:
                    ln["masks"].append(r.row_mask)   # never the slide-in frame
                used.add(best)
            else:
                active.append(dict(icons=r.icons, y=r.y, ink=ink, first_t=t,
                                   last_t=t, seen=1, masks=[],
                                   harvested=False))

        still = []
        for ln in active:
            if t - ln["last_t"] > 1.0 and not ln["harvested"] and ln["seen"] >= 3:
                n, labels = harvest_line(reader, ln, a, id_counts)
                harvested_total += n
                if not labels:
                    unidentified += 1
                ln["harvested"] = True
            if t - ln["last_t"] <= 2.0:
                still.append(ln)
        active = still

        if frame_no % (step * 240) == 0:
            print(f"  {t:7.1f}s  rows {rows_seen:4d}  glyphs {harvested_total:4d}  "
                  f"chars {len({c for c, *_ in reader.templates})}")

    for ln in active:
        if not ln["harvested"] and ln["seen"] >= 3:
            n, labels = harvest_line(reader, ln, a, id_counts)
            harvested_total += n
            if not labels:
                unidentified += 1
    cap.release()

    reader.reload()
    covered = {c for c, *_ in reader.templates}
    print(f"\nFeed rows seen: {rows_seen}")
    print(f"Lines identified: {sum(id_counts.values())}   unidentified: {unidentified}")
    for name, n in id_counts.most_common():
        print(f"    {name:<16} {n}")
    print(f"\n{'Would harvest' if a.report_only else 'Harvested'}: "
          f"{harvested_total} glyph templates")
    print(f"Templates loaded: {len(reader.templates)} across {len(covered)} characters")
    print(f"reader.ready = {reader.ready}")

    need = set("".join(names.norm(n) for n in a.roster))
    have = {names.norm(c) if c.isalnum() else c for c in covered}
    missing = sorted(ch for ch in set("".join(a.roster)) if ch not in covered)
    if missing:
        print(f"\nNo template for: {missing}")
        print("  (a name containing one of these cannot be read from templates alone)")
    else:
        print("\nFull coverage of every character in the roster.")
    return 0


def harvest_line(reader, ln, a, id_counts):
    """Identify the killer and victim words on one tracked line and harvest them.

    Reads every retained sighting of the line, not just one. A single frame's
    mask is often half-occluded; pooling the Tesseract reads across sightings is
    what lifts the identification rate (profile `ocr_samples` makes the same
    point for the runtime path).
    """
    masks = [m for m in ln["masks"] if m is not None]
    if not masks:
        return 0, []

    # Harvest geometry comes from the most fully-rendered sighting.
    mask = max(masks, key=lambda m: int(m.sum()))
    ws = words_of(reader, mask)
    if len(ws) < 2:
        return 0, []

    # Bootstrap identification: Tesseract, never our own templates, unless
    # --use-templates is set for a second pass over what pass 1 could not read.
    first_toks, last_toks, all_toks = [], [], []
    for m in masks:
        toks = [t for t in names._tess_mask(m).split() if t]
        if a.use_templates and reader.ready:
            toks += [t for t in reader.read(m).split() if t]
        if toks:
            first_toks.append(toks[0])
            last_toks.append(toks[-1])
            all_toks += toks

    # Resolve both slots before writing anything, so the self-kill guard can veto.
    picks = {}
    for slot, (x0, x1, n_glyphs) in (("killer", ws[0]), ("victim", ws[-1])):
        if n_glyphs < 3:
            continue
        ordered = (first_toks if slot == "killer" else last_toks) + all_toks
        picks[slot] = (identify(ordered, n_glyphs, a.roster, a.min_score,
                                a.allow_length_guess), x0, x1, n_glyphs)

    # §5.8's bug class, at harvest time: one player cannot be both ends of a
    # row. If both slots land on the same name, one of them is wrong and we
    # cannot tell which, so neither is harvested.
    k, v = picks.get("killer", (None,))[0], picks.get("victim", (None,))[0]
    if k and v and k[0] == v[0]:
        if a.report_only:
            print(f"  {ln['first_t']:7.1f}s  SKIP both slots read {k[0]!r} "
                  f"- one is wrong, cannot tell which")
        return 0, []

    total, labels = 0, []
    for slot in ("killer", "victim"):
        if slot not in picks or not picks[slot][0]:
            continue
        (name, score), x0, x1, n_glyphs = picks[slot]
        id_counts[name] += 1
        labels.append(name)
        sub = mask[:, x0:x1 + 1]
        if a.report_only:
            got = len(reader.glyphs(sub))
            print(f"  {ln['first_t']:7.1f}s {slot:>6} -> {name:<16} "
                  f"score {score:.2f}  glyphs {got}/{len(name)}"
                  f"{'  MISALIGNED' if got != len(name) else ''}")
        else:
            saved = reader.harvest(sub, name, a.max_per_char)
            if saved:
                total += saved
                print(f"  {ln['first_t']:7.1f}s {slot:>6} -> {name:<16} "
                      f"score {score:.2f}  +{saved} glyphs")
    return total, labels


if __name__ == "__main__":
    sys.exit(main())

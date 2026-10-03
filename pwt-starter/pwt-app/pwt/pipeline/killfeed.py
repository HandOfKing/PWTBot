"""PWT kill-feed extractor — prototype v0.1

Reads sampled frames (f0001.jpg ...) at a known fps, finds kill-feed rows,
classifies icons by template, OCRs names, fuzzy-matches them to the roster,
and dedupes row sightings into events.

Usage: python3 killfeed.py <frame_dir> <fps> <out_prefix>
"""
import cv2, glob, os, sys, csv, difflib, subprocess, numpy as np

# ---- layout for THIS recording (GameLoop windowed; game area x100-1828, y53-1025)
FX0, FY0, FX1, FY1 = 100, 215, 760, 480   # feed grows upward from the bottom slot (~y455)
ROW_LEFT_MIN, ROW_LEFT_MAX = 105, 140      # feed rows are left-aligned at x~118
ROSTER = ["TheWolverine", "PARAbloodthirs", "RGODxEMPEROR", "Makjets69"]
ICON_THRESH = 0.62
MERGE_GAP_S = 1.0          # a row key absent longer than this starts a new sighting

TEMPL = {}
for p in glob.glob(os.path.join(os.path.dirname(__file__) or ".", "templates", "*.png")):
    n = os.path.basename(p)[:-4]
    if n.endswith("_rgb"): continue
    TEMPL[n] = (cv2.imread(p, 0) > 127).astype(np.float32)


KERNEL = cv2.getStructuringElement(cv2.MORPH_RECT, (23, 23))

def white_mask(crop):
    """Text/icon pixels = near-neutral pixels much brighter than their local background
    (white top-hat). Threshold is relative, so it survives the round-end dim overlay."""
    c = crop.astype(np.int16)
    mn = c.min(2).astype(np.uint8); mx = c.max(2)
    th = cv2.morphologyEx(mn, cv2.MORPH_TOPHAT, KERNEL).astype(np.int16)
    t = max(18, 0.45 * np.percentile(th, 99.8))
    return ((th > t) & (mx - mn.astype(np.int16) < 45)).astype(np.uint8)


def find_rows(m):
    prof = m[:, 14:440].sum(1)          # skip the window edge at x~100-110 (vertical streaks)
    rows, y, H = [], 0, len(prof)
    while y < H:
        if prof[y] >= 3:
            y0 = y
            while y < H and prof[y] >= 2: y += 1
            if 9 <= y - y0 <= 26: rows.append((y0, y))
        y += 1
    return rows


def segments(m, y0, y1, gap=9):
    col = m[y0:y1].sum(0); col[:12] = 0
    xs = np.where(col > 0)[0]
    if not len(xs): return []
    segs, s, p = [], xs[0], xs[0]
    for x in xs[1:]:
        if x - p > gap: segs.append([s, p + 1]); s = x
        p = x
    segs.append([s, p + 1])
    return [s for s in segs if s[1] - s[0] >= 3]


def match_icon(m, y0, y1, a, b):
    patch = m[max(0, y0 - 6):y1 + 6, max(0, a - 6):b + 6].astype(np.float32)
    best, name = 0, None
    for n, t in TEMPL.items():
        if t.shape[0] > patch.shape[0] or t.shape[1] > patch.shape[1]: continue
        # icon width must roughly fit the segment width
        if not (0.6 < (b - a) / (t.shape[1] - 6) < 1.5): continue
        r = cv2.matchTemplate(patch, t, cv2.TM_CCOEFF_NORMED).max()
        if r > best: best, name = r, n
    return (name, best) if best >= ICON_THRESH else (None, best)


def ocr(crop_mask):
    img = 255 - cv2.resize(crop_mask * 255, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    img = cv2.copyMakeBorder(img, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    ok, buf = cv2.imencode(".png", img)
    r = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "7", "-l", "eng"],
                       input=buf.tobytes(), capture_output=True)
    return r.stdout.decode(errors="ignore").strip()


def norm(s):
    return s.lower().replace("ø", "o").replace("0", "o").replace(" ", "")


def match_name(raw):
    if not raw: return None, 0.0
    scores = [(difflib.SequenceMatcher(None, norm(raw), norm(n)).ratio(), n) for n in ROSTER]
    sc, n = max(scores)
    return n, sc


def find_icons(m, y0, y1):
    """Slide every icon template along the row band; keep non-overlapping best peaks."""
    band = m[max(0, y0 - 6):y1 + 6].astype(np.float32)
    cands = []
    for n, t in TEMPL.items():
        if t.shape[0] > band.shape[0]: continue
        r = cv2.matchTemplate(band, t, cv2.TM_CCOEFF_NORMED).max(0)
        xs = np.where(r >= ICON_THRESH)[0]
        for x in xs:
            lo, hi = max(0, x - 4), x + 5
            if r[x] == r[lo:hi].max():
                cands.append((float(r[x]), int(x), int(x + t.shape[1]), n))
    cands.sort(reverse=True)
    keep = []
    for c in cands:
        if all(c[2] <= k[1] + 3 or c[1] >= k[2] - 3 for k in keep): keep.append(c)
    return sorted(keep, key=lambda c: c[1])


def text_span(m, y0, y1, a, b, direction):
    """Columns with text between a and b; for the victim, stop at the first big gap."""
    col = m[y0:y1, a:b].sum(0)
    xs = np.where(col > 0)[0]
    if not len(xs): return None
    if direction == "right":
        end = xs[0]
        for x in xs[1:]:
            if x - end > 14: break
            end = x
        return a + xs[0], a + end + 1
    return a + xs[0], a + xs[-1] + 1


def parse_frame(path):
    im = cv2.imread(path)
    crop = im[FY0:FY1, FX0:FX1]
    m = white_mask(crop)
    out = []
    for (y0, y1) in find_rows(m):
        col = m[y0:y1].sum(0); col[:12] = 0
        xs = np.where(col > 0)[0]
        if not len(xs) or not (ROW_LEFT_MIN <= xs[0] + FX0 <= ROW_LEFT_MAX): continue
        icons = find_icons(m, y0, y1)
        if not icons: continue                          # not a feed row (e.g. a name tag)
        # templates carry 3 px padding: real icon = [x+3, x+w-3]
        ks = text_span(m, y0, y1, 12, icons[0][1] + 1, "left")
        vs = text_span(m, y0, y1, icons[-1][2] - 1, m.shape[1], "right")
        if not ks or not vs or ks[1] - ks[0] < 12 or vs[1] - vs[0] < 12: continue
        k_raw = ocr(m[y0 - 2:y1 + 2, ks[0]:ks[1]])
        v_raw = ocr(m[y0 - 2:y1 + 2, vs[0]:vs[1]])
        k, kc = match_name(k_raw); v, vc = match_name(v_raw)
        if min(kc, vc) < 0.5: continue                  # names not on roster -> background noise
        names = [c[3] for c in icons]
        weapon = next((n.replace("weapon_", "") for n in names if n.startswith("weapon_")), "")
        if "icon_knock" in names: etype = "knock"
        elif "icon_tombstone" in names: etype = "eliminated_knocked"
        else: etype = "kill"
        out.append(dict(row_y=int(y0 + FY0), killer=k, killer_raw=k_raw, killer_conf=round(kc, 2),
                        victim=v, victim_raw=v_raw, victim_conf=round(vc, 2), type=etype,
                        weapon=weapon, icons="|".join(f"{c[3]}:{c[0]:.2f}" for c in icons)))
    return out


def dedupe(sightings, fps):
    """sightings: list of (t, row). A key's per-frame count rising = new event."""
    events, open_ = [], {}   # key -> list of [first_t, last_t, n_seen, min_conf]
    by_t = {}
    for t, r in sightings: by_t.setdefault(t, []).append(r)
    for t in sorted(by_t):
        counts = {}
        for r in by_t[t]:
            key = (r["killer"], r["type"], r["victim"])
            counts.setdefault(key, []).append(r)
        for key, rows in counts.items():
            live = [e for e in open_.get(key, []) if t - e["last_t"] <= MERGE_GAP_S]
            for e, r in zip(live, rows):
                e["last_t"] = t; e["n"] += 1; e["confs"].append(min(r["killer_conf"], r["victim_conf"])); e["weapons"].append(r["weapon"])
            for r in rows[len(live):]:
                e = dict(first_t=t, last_t=t, n=1, killer=key[0], type=key[1], victim=key[2],
                         weapons=[r["weapon"]], confs=[min(r["killer_conf"], r["victim_conf"])])
                events.append(e); live.append(e)
            open_[key] = live
    min_n = max(2, round(0.5 * fps))                    # must persist >= ~0.5 s (drops slide/shift glitches)
    kept, dropped = [], []
    for e in events:
        e["conf"] = round(float(np.median(e["confs"])), 2)
        ws = [w for w in e["weapons"] if w]
        e["weapon"] = max(set(ws), key=ws.count) if ws else ""
        (kept if e["n"] >= min_n and e["killer"] and e["victim"] else dropped).append(e)
    for e in kept:
        e["flag"] = "LOW_CONF" if e["conf"] < 0.75 or e["killer"] == e["victim"] else ""
    return kept, dropped


def run(frame_dir, fps, prefix):
    files = sorted(glob.glob(os.path.join(frame_dir, "f*.jpg")))
    sightings = []
    for i, f in enumerate(files):
        t = round(i / fps, 3)                         # timestamp from frame index
        for r in parse_frame(f):
            sightings.append((t, r))
    with open(prefix + "_rows.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["t", "row_y", "killer", "killer_raw", "killer_conf", "type", "weapon",
                    "victim", "victim_raw", "victim_conf", "icons"])
        for t, r in sightings:
            w.writerow([t, r["row_y"], r["killer"], r["killer_raw"], r["killer_conf"], r["type"],
                        r["weapon"], r["victim"], r["victim_raw"], r["victim_conf"], r["icons"]])
    ev, dropped = dedupe(sightings, fps)
    print(f"dropped {len(dropped)} transient detections:", [(e['first_t'], e['killer'], e['type'], e['victim'], e['n']) for e in dropped])
    with open(prefix + "_events.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["feed_first_seen_s", "feed_last_seen_s", "killer", "type", "weapon", "victim",
                    "sightings", "name_conf", "flag"])
        for e in ev:
            w.writerow([e["first_t"], e["last_t"], e["killer"], e["type"], e["weapon"], e["victim"],
                        e["n"], e["conf"], e["flag"]])
    return files, sightings, ev


if __name__ == "__main__":
    import time
    t0 = time.time()
    files, s, ev = run(sys.argv[1], float(sys.argv[2]), sys.argv[3])
    print(f"{len(files)} frames, {len(s)} row sightings, {len(ev)} events, {time.time()-t0:.1f}s")
    for e in ev:
        print(f"  {e['first_t']:6.2f}-{e['last_t']:6.2f}s  {e['killer']} --{e['type']}/{e['weapon'] or '-'}--> {e['victim']}  (seen {e['n']}x, conf {e['conf']}) {e['flag']}")

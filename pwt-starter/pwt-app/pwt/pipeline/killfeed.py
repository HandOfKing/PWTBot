"""PWT kill-feed extractor — Phase 1

Reads sampled frames (cv2 BGR images) from decode.decode_frames(), finds
kill-feed rows, classifies icons by template, OCRs names, fuzzy-matches them
to a roster, and dedupes row sightings into events.

Each row is OCR'd exactly once when it first appears (read-once tracking by
y-position).  Evidence crops are saved to evidence_dir when provided.

Public API
----------
run_on_frames(frames, profile, roster, evidence_dir=None) -> (events, dropped)

Legacy CLI shim (prototype compat)
-----------------------------------
run(frame_dir, fps, prefix)  — still works for manual testing
"""
from __future__ import annotations
import csv
import difflib
import glob
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from .profile import LayoutProfile

# ── template loading ──────────────────────────────────────────────────────────
# Loaded lazily per profile so multiple profiles can coexist.

def _load_templates(templates_path: Path) -> dict[str, np.ndarray]:
    templ: dict[str, np.ndarray] = {}
    for p in templates_path.glob("*.png"):
        n = p.stem
        if n.endswith("_rgb"):
            continue
        img = cv2.imread(str(p), 0)
        if img is not None:
            templ[n] = (img > 127).astype(np.float32)
    return templ


# ── image helpers ─────────────────────────────────────────────────────────────

_KERNEL = cv2.getStructuringElement(cv2.MORPH_RECT, (23, 23))


def white_mask(crop: np.ndarray) -> np.ndarray:
    """Text/icon pixels = near-neutral pixels much brighter than local background."""
    c = crop.astype(np.int16)
    mn = c.min(2).astype(np.uint8)
    mx = c.max(2)
    th = cv2.morphologyEx(mn, cv2.MORPH_TOPHAT, _KERNEL).astype(np.int16)
    t = max(18, 0.45 * np.percentile(th, 99.8))
    return ((th > t) & (mx - mn.astype(np.int16) < 45)).astype(np.uint8)


def find_rows(m: np.ndarray) -> list[tuple[int, int]]:
    prof = m[:, 14:440].sum(1)
    rows, y, H = [], 0, len(prof)
    while y < H:
        if prof[y] >= 3:
            y0 = y
            while y < H and prof[y] >= 2:
                y += 1
            if 9 <= y - y0 <= 26:
                rows.append((y0, y))
        y += 1
    return rows


def find_icons(
    m: np.ndarray,
    y0: int,
    y1: int,
    templ: dict[str, np.ndarray],
    icon_thresh: float,
) -> list[tuple[float, int, int, str]]:
    band = m[max(0, y0 - 6):y1 + 6].astype(np.float32)
    cands: list[tuple[float, int, int, str]] = []
    for n, t in templ.items():
        if t.shape[0] > band.shape[0]:
            continue
        r = cv2.matchTemplate(band, t, cv2.TM_CCOEFF_NORMED).max(0)
        xs = np.where(r >= icon_thresh)[0]
        for x in xs:
            lo, hi = max(0, x - 4), x + 5
            if r[x] == r[lo:hi].max():
                cands.append((float(r[x]), int(x), int(x + t.shape[1]), n))
    cands.sort(reverse=True)
    keep: list[tuple[float, int, int, str]] = []
    for c in cands:
        if all(c[2] <= k[1] + 3 or c[1] >= k[2] - 3 for k in keep):
            keep.append(c)
    return sorted(keep, key=lambda c: c[1])


def text_span(
    m: np.ndarray,
    y0: int,
    y1: int,
    a: int,
    b: int,
    direction: str,
) -> Optional[tuple[int, int]]:
    col = m[y0:y1, a:b].sum(0)
    xs = np.where(col > 0)[0]
    if not len(xs):
        return None
    if direction == "right":
        end = xs[0]
        for x in xs[1:]:
            if x - end > 14:
                break
            end = x
        return a + xs[0], a + end + 1
    return a + xs[0], a + xs[-1] + 1


def _ocr(crop_mask: np.ndarray) -> str:
    img = 255 - cv2.resize(
        crop_mask * 255, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC
    )
    img = cv2.copyMakeBorder(img, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    _, buf = cv2.imencode(".png", img)
    r = subprocess.run(
        ["tesseract", "stdin", "stdout", "--psm", "7", "-l", "eng"],
        input=buf.tobytes(), capture_output=True,
    )
    return r.stdout.decode(errors="ignore").strip()


def _norm(s: str) -> str:
    return s.lower().replace("ø", "o").replace("0", "o").replace(" ", "")


def _match_name(
    raw: str, roster: list[str]
) -> tuple[Optional[str], float]:
    if not raw or not roster:
        return None, 0.0
    scores = [
        (difflib.SequenceMatcher(None, _norm(raw), _norm(n)).ratio(), n)
        for n in roster
    ]
    sc, n = max(scores)
    return n, sc


# ── per-frame row parser ──────────────────────────────────────────────────────

def parse_frame_img(
    img: np.ndarray,
    profile: LayoutProfile,
    roster: list[str],
    templ: dict[str, np.ndarray],
) -> list[dict]:
    """Extract kill-feed rows from one BGR image.  Returns raw (undeduped) rows."""
    fx0, fy0, fx1, fy1 = profile.feed_box
    crop = img[fy0:fy1, fx0:fx1]
    m = white_mask(crop)
    out = []
    for y0, y1 in find_rows(m):
        col = m[y0:y1].sum(0)
        col[:12] = 0
        xs = np.where(col > 0)[0]
        if not len(xs):
            continue
        left_x = int(xs[0])
        if not (profile.row_left_min <= left_x <= profile.row_left_max):
            continue
        icons = find_icons(m, y0, y1, templ, profile.icon_thresh)
        if not icons:
            continue
        ks = text_span(m, y0, y1, 12, icons[0][1] + 1, "left")
        vs = text_span(m, y0, y1, icons[-1][2] - 1, m.shape[1], "right")
        if not ks or not vs or ks[1] - ks[0] < 12 or vs[1] - vs[0] < 12:
            continue
        k_raw = _ocr(m[y0 - 2:y1 + 2, ks[0]:ks[1]])
        v_raw = _ocr(m[y0 - 2:y1 + 2, vs[0]:vs[1]])
        k, kc = _match_name(k_raw, roster)
        v, vc = _match_name(v_raw, roster)
        if roster and min(kc, vc) < 0.5:
            continue   # not on roster → background noise
        names = [c[3] for c in icons]
        weapon = next(
            (n.replace("weapon_", "") for n in names if n.startswith("weapon_")), ""
        )
        if "icon_knock" in names:
            etype = "knock"
        elif "icon_tombstone" in names:
            etype = "eliminated_knocked"
        else:
            etype = "kill"
        out.append(dict(
            row_y=int(y0),          # crop-relative y (for read-once tracking)
            row_y_abs=int(y0 + fy0),
            crop_y0=int(y0), crop_y1=int(y1),
            killer=k, killer_raw=k_raw, killer_conf=round(kc, 2),
            victim=v, victim_raw=v_raw, victim_conf=round(vc, 2),
            type=etype, weapon=weapon,
            icons="|".join(f"{c[3]}:{c[0]:.2f}" for c in icons),
        ))
    return out


# ── read-once row tracker ─────────────────────────────────────────────────────

_Y_TOL = 8   # pixels: rows within this distance are the "same" feed slot


class _ActiveRow:
    __slots__ = ("data", "first_idx", "last_idx", "evidence_crop")

    def __init__(self, data: dict, frame_idx: int, evidence_crop: np.ndarray):
        self.data = data
        self.first_idx = frame_idx
        self.last_idx = frame_idx
        self.evidence_crop = evidence_crop


def _closest_active(
    y: int, active: dict[int, _ActiveRow]
) -> Optional[int]:
    for ay in active:
        if abs(ay - y) <= _Y_TOL:
            return ay
    return None


# ── main pipeline entry point ─────────────────────────────────────────────────

def run_on_frames(
    frames: list[tuple[int, float, np.ndarray]],
    profile: LayoutProfile,
    roster: list[str],
    evidence_dir: Optional[Path] = None,
    fps: float = 4.0,
) -> tuple[list[dict], list[dict]]:
    """Process decoded frames, return (events, dropped_transient_rows).

    events dicts include:
      feed_first_seen_s, feed_last_seen_s, killer, type, weapon, victim,
      sightings, name_conf, flag, evidence_path (or None)
    """
    templ = _load_templates(profile.templates_path)
    active: dict[int, _ActiveRow] = {}   # crop-relative y_center -> _ActiveRow
    completed: list[_ActiveRow] = []

    fx0, fy0, fx1, fy1 = profile.feed_box

    for sample_idx, timestamp, img in frames:
        rows = parse_frame_img(img, profile, roster, templ)
        current_ys: set[int] = set()

        for row in rows:
            y = row["row_y"]
            current_ys.add(y)
            existing_y = _closest_active(y, active)
            if existing_y is None:
                # New row: OCR already done by parse_frame_img; save evidence crop
                crop = img[fy0 + row["crop_y0"]:fy0 + row["crop_y1"], fx0:fx1]
                active[y] = _ActiveRow(row, sample_idx, crop.copy())
            else:
                active[existing_y].last_idx = sample_idx

        # Rows that vanished this frame → move to completed
        for y in list(active.keys()):
            if not any(abs(y - cy) <= _Y_TOL for cy in current_ys):
                completed.append(active.pop(y))

    # Flush anything still active at end of video
    completed.extend(active.values())
    active.clear()

    # Dedupe: keep rows that were visible for >= 0.5 s
    min_frames = max(2, round(0.5 * fps))
    events: list[dict] = []
    dropped: list[dict] = []

    for ar in completed:
        n = ar.last_idx - ar.first_idx + 1
        d = ar.data
        k, v = d["killer"], d["victim"]
        conf = round(float(np.median([d["killer_conf"], d["victim_conf"]])), 2)
        ev = dict(
            feed_first_seen_s=round(ar.first_idx / fps, 3),
            feed_last_seen_s=round(ar.last_idx / fps, 3),
            killer=k, type=d["type"], weapon=d["weapon"], victim=v,
            sightings=n, name_conf=conf, flag="",
            evidence_crop=ar.evidence_crop,
            evidence_path=None,
        )
        if n >= min_frames and k and v:
            ev["flag"] = "LOW_CONF" if conf < 0.75 or k == v else ""
            events.append(ev)
        else:
            dropped.append(ev)

    # Save evidence crops
    if evidence_dir:
        evidence_dir = Path(evidence_dir)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        for i, ev in enumerate(events):
            crop = ev.pop("evidence_crop", None)
            if crop is not None and crop.size > 0:
                path = evidence_dir / f"ev_{i:04d}.png"
                cv2.imwrite(str(path), crop)
                ev["evidence_path"] = str(path)
    else:
        for ev in events:
            ev.pop("evidence_crop", None)
        for ev in dropped:
            ev.pop("evidence_crop", None)

    return events, dropped


# ── legacy shim (prototype compatibility) ────────────────────────────────────

def run(frame_dir: str, fps: float, prefix: str) -> tuple:
    """Original prototype interface: reads JPEG frames from a directory."""
    from .profile import LayoutProfile
    # Build a minimal profile from the old hard-coded constants
    import json
    _profiles_dir = Path(__file__).parent.parent.parent / "profiles"
    default_json = _profiles_dir / "gameloop-windowed-1080p.json"
    if default_json.exists():
        profile = LayoutProfile.load(default_json)
    else:
        raise FileNotFoundError(
            "profiles/gameloop-windowed-1080p.json not found; "
            "create it or pass a LayoutProfile explicitly."
        )
    roster: list[str] = []   # no roster in legacy mode; names flagged LOW_CONF

    files = sorted(glob.glob(os.path.join(frame_dir, "f*.jpg")))
    templ = _load_templates(profile.templates_path)
    sightings = []
    for i, f in enumerate(files):
        t = round(i / fps, 3)
        img = cv2.imread(f)
        if img is None:
            continue
        for r in parse_frame_img(img, profile, roster, templ):
            sightings.append((t, r))

    # Write rows CSV (prototype format)
    with open(prefix + "_rows.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["t", "row_y", "killer", "killer_raw", "killer_conf", "type",
                    "weapon", "victim", "victim_raw", "victim_conf", "icons"])
        for t, r in sightings:
            w.writerow([t, r["row_y_abs"], r["killer"], r["killer_raw"],
                        r["killer_conf"], r["type"], r["weapon"],
                        r["victim"], r["victim_raw"], r["victim_conf"], r["icons"]])

    # Build fake frames list for run_on_frames
    fake_frames = []
    for i, f in enumerate(files):
        img = cv2.imread(f)
        if img is not None:
            fake_frames.append((i, i / fps, img))

    ev, dropped = run_on_frames(fake_frames, profile, roster, fps=fps)
    print(f"dropped {len(dropped)} transient rows")

    with open(prefix + "_events.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["feed_first_seen_s", "feed_last_seen_s", "killer", "type",
                    "weapon", "victim", "sightings", "name_conf", "flag"])
        for e in ev:
            w.writerow([e["feed_first_seen_s"], e["feed_last_seen_s"],
                        e["killer"], e["type"], e["weapon"], e["victim"],
                        e["sightings"], e["name_conf"], e["flag"]])
    return files, sightings, ev


if __name__ == "__main__":
    import time
    t0 = time.time()
    files, s, ev = run(sys.argv[1], float(sys.argv[2]), sys.argv[3])
    print(f"{len(files)} frames, {len(s)} sightings, {len(ev)} events, "
          f"{time.time() - t0:.1f}s")
    for e in ev:
        print(f"  {e['feed_first_seen_s']:6.2f}-{e['feed_last_seen_s']:6.2f}s  "
              f"{e['killer']} --{e['type']}/{e['weapon'] or '-'}--> {e['victim']}  "
              f"(seen {e['sightings']}x, conf {e['name_conf']}) {e['flag']}")

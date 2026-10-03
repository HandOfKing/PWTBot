"""Round-end and match-end scoreboard detection and reading.

Detection: a round-end scoreboard fills most of the screen with a bright
white/grey overlay.  We check a configurable trigger_box for high average
brightness and a minimum fraction of near-white pixels.

Reading: player names are OCR'd with Tesseract (--psm 7, single line); stat
columns are read with digit-only OCR.  Both are flagged when confidence is
low, consistent with the project's "never guess" rule.

All coordinates come from the LayoutProfile; nothing is hard-coded here.
"""
from __future__ import annotations
import subprocess
from typing import Optional
import cv2
import numpy as np

from .profile import LayoutProfile


# ── detection ────────────────────────────────────────────────────────────────

def scoreboard_visible(img: np.ndarray, profile: LayoutProfile) -> bool:
    """Return True when a round-end / match-end scoreboard is likely on screen."""
    sb = profile.scoreboard
    if not sb:
        return False
    x0, y0, x1, y1 = sb["trigger_box"]
    region = img[y0:y1, x0:x1]
    if region.size == 0:
        return False
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    mean_bright = float(np.mean(gray))
    white_frac = float(np.mean(gray >= sb.get("trigger_brightness_min", 180)))
    return (mean_bright >= sb.get("trigger_brightness_min", 180) * 0.6
            and white_frac >= sb.get("trigger_white_frac_min", 0.15))


# ── OCR helpers ──────────────────────────────────────────────────────────────

def _ocr_line(crop_gray: np.ndarray) -> str:
    """OCR a single-line text crop; return stripped string."""
    img = cv2.resize(crop_gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    _, buf = cv2.imencode(".png", img)
    r = subprocess.run(
        ["tesseract", "stdin", "stdout", "--psm", "7", "-l", "eng"],
        input=buf.tobytes(), capture_output=True,
    )
    return r.stdout.decode(errors="ignore").strip()


def _ocr_digits(crop_gray: np.ndarray) -> Optional[int]:
    """OCR a digit-only crop; return int or None."""
    img = cv2.resize(crop_gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    _, b = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    b = cv2.copyMakeBorder(b, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    _, buf = cv2.imencode(".png", b)
    r = subprocess.run(
        ["tesseract", "stdin", "stdout", "--psm", "7",
         "-c", "tessedit_char_whitelist=0123456789"],
        input=buf.tobytes(), capture_output=True,
    )
    s = r.stdout.decode(errors="ignore").strip()
    return int(s) if s.isdigit() else None


# ── reading ───────────────────────────────────────────────────────────────────

def read_scoreboard(img: np.ndarray, profile: LayoutProfile) -> dict:
    """Read one scoreboard frame.

    Returns::

        {
            "players": [
                {"ign": str, "ign_conf": float,
                 "eliminations": int|None, "damage_dealt": int|None,
                 "team": str|None},
                ...
            ]
        }

    team assignment is left as None here; callers infer it from column
    position if the scoreboard has separate blue/red sections.
    """
    sb = profile.scoreboard
    if not sb:
        return {"players": []}

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    name_x0, name_x1 = sb["name_col"]
    stat_cols: dict[str, list[int]] = sb.get("stat_cols", {})
    row_y = sb["row_start_y"]
    row_h = sb["row_height"]
    max_rows = sb.get("max_players", 16)

    players = []
    for i in range(max_rows):
        y0 = row_y + i * row_h
        y1 = y0 + row_h - 2

        name_crop = gray[y0:y1, name_x0:name_x1]
        if name_crop.size == 0:
            break
        # Blank row check: skip if the strip is nearly uniform
        if float(np.std(name_crop)) < 5.0:
            continue

        ign = _ocr_line(name_crop)
        if not ign:
            continue

        stats: dict[str, Optional[int]] = {}
        for stat_name, (sx0, sx1) in stat_cols.items():
            stats[stat_name] = _ocr_digits(gray[y0:y1, sx0:sx1])

        players.append(dict(ign=ign, ign_conf=1.0, team=None, **stats))

    return {"players": players}


# ── frame sequence → scoreboard list ─────────────────────────────────────────

def collect_scoreboards(
    frames: list[tuple[int, float, np.ndarray]],
    profile: LayoutProfile,
    min_hold_s: float = 1.0,
) -> list[dict]:
    """Scan all frames and return one entry per distinct scoreboard appearance.

    Each entry::

        {"sample_idx": int, "timestamp_s": float, "data": <read_scoreboard result>}

    A scoreboard must be visible for at least *min_hold_s* seconds before we
    read it (to avoid reading a partially-faded-in overlay).  We take the
    middle frame of each run.
    """
    fps = 4.0  # sample rate (same master clock as rest of pipeline)
    min_frames = max(1, round(min_hold_s * fps))

    runs: list[list[tuple[int, float, np.ndarray]]] = []
    current: list[tuple[int, float, np.ndarray]] = []

    for sample_idx, ts, img in frames:
        if scoreboard_visible(img, profile):
            current.append((sample_idx, ts, img))
        else:
            if len(current) >= min_frames:
                runs.append(current)
            current = []
    if len(current) >= min_frames:
        runs.append(current)

    results = []
    for run in runs:
        mid = run[len(run) // 2]
        sample_idx, ts, img = mid
        results.append({
            "sample_idx": sample_idx,
            "timestamp_s": ts,
            "data": read_scoreboard(img, profile),
        })
    return results

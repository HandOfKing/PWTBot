"""PWT HUD counters — Phase 1

Per sampled frame reads:
  - Remaining (players alive)  → exact elimination times
  - banner helmets              → which team lost a player
  - banner round score          → round winner + round-end time

Then aligns kill-feed eliminations to true times.

Public API
----------
run_on_frames(frames, feed_events, profile, team_map, fps=4.0)
    -> (aligned_events, drops, deaths)

Legacy CLI shim
---------------
run(frame_dir, fps, feed_csv, prefix)  — still works for manual testing
"""
from __future__ import annotations
import csv
import glob
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from .profile import LayoutProfile


# ── OCR ───────────────────────────────────────────────────────────────────────

def _ocr_digits(img: np.ndarray) -> Optional[int]:
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    g = cv2.resize(g, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    b = cv2.copyMakeBorder(b, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    out = subprocess.run(
        ["tesseract", "stdin", "stdout", "--psm", "7",
         "-c", "tessedit_char_whitelist=0123456789"],
        input=cv2.imencode(".png", b)[1].tobytes(), capture_output=True,
    )
    s = out.stdout.decode().strip()
    return int(s) if s.isdigit() else None


# ── per-pixel HUD reads ───────────────────────────────────────────────────────

def _helmet_state(
    img: np.ndarray, x: int, y: int, white_thresh: int, gray_thresh: int
) -> Optional[str]:
    patch = img[y - 11:y + 11, x - 13:x + 13]
    if patch.size == 0:
        return None
    v = np.percentile(patch.astype(int).min(2), 90)
    if v > white_thresh:
        return "alive"
    if v > gray_thresh:
        return "dead"
    return None


def _banner_visible(img: np.ndarray, profile: LayoutProfile) -> bool:
    """Banner (score boxes) must be solidly blue / red."""
    b = all(
        int(img[y, x][0]) - int(img[y, x][2]) > 80
        for x, y in profile.banner_blue_pts
    )
    r = all(
        int(img[y, x][2]) - int(img[y, x][0]) > 70
        for x, y in profile.banner_red_pts
    )
    return b and r


def _read_frame(
    img: np.ndarray,
    profile: LayoutProfile,
    team_size: int,
) -> tuple[Optional[int], Optional[dict]]:
    """Return (remaining_count, helmet_dict) for one frame.

    helmet_dict is None when the banner isn't visible.
    """
    x0, y0, x1, y1 = profile.remaining_box
    rem = _ocr_digits(img[y0:y1, x0:x1])
    if not _banner_visible(img, profile):
        return rem, None
    helm_positions = profile.helmet_pos_for_size(team_size)
    helm = {
        team: [
            _helmet_state(img, x, y, profile.white_thresh, profile.gray_thresh)
            for x, y in pts
        ]
        for team, pts in helm_positions.items()
    }
    return rem, helm


# ── stabiliser ───────────────────────────────────────────────────────────────

def _stable(
    series: list[tuple[float, Optional[int]]], k: int = 2
) -> list[tuple[float, Optional[int], int]]:
    """Accept a value once it appears k consecutive readable frames.
    Returns list of (timestamp, from_value, to_value)."""
    out: list = []
    cur = cand = None
    n = 0
    cand_t = left_t = None
    for t, v in series:
        if v is None:
            continue
        if cur is not None and v != cur and left_t is None:
            left_t = t
        if v == cand:
            n += 1
        else:
            cand, n, cand_t = v, 1, t
        if n >= k and v != cur:
            out.append((round(left_t if left_t is not None else cand_t, 3), cur, v))
            cur, left_t = v, None
        elif v == cur:
            left_t = None
    return out


# ── main entry point ──────────────────────────────────────────────────────────

def run_on_frames(
    frames: list[tuple[int, float, np.ndarray]],
    feed_events: list[dict],
    profile: LayoutProfile,
    team_map: dict[str, str],
    team_size: int = 2,
    fps: float = 4.0,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Align feed events to true times from Remaining drops.

    Parameters
    ----------
    frames      : decoded frames from decode.decode_frames()
    feed_events : output of killfeed.run_on_frames()
    profile     : layout profile
    team_map    : {ign -> "blue"|"red"}  (from scoreboard; may be empty)
    team_size   : players per team (for helmet slot count)

    Returns
    -------
    aligned_events, drops, deaths
    """
    rem_series: list[tuple[float, Optional[int]]] = []
    helm_series: list[tuple[float, dict]] = []

    for _idx, ts, img in frames:
        rem, helm = _read_frame(img, profile, team_size)
        rem_series.append((ts, rem))
        if helm is not None:
            helm_series.append((ts, helm))

    # 1) Remaining drops → one elimination per count decrease
    drops: list[dict] = []
    for t, before, after in _stable(rem_series):
        if before is not None and after < before:
            drops += [dict(t=t, team=None) for _ in range(before - after)]

    # 2) Helmet alive→dead transitions → which team lost
    deaths: list[dict] = []
    state: dict = {}
    pend: dict = {}
    last_t: Optional[float] = None

    def _flush():
        for (team, k), pt in list(pend.items()):
            deaths.append(dict(t=pt, team=team, slot=k + 1))
            state[(team, k)] = "dead"
        pend.clear()

    for t, h in helm_series:
        if last_t is not None and t - last_t > 1.5 / fps:
            _flush()
        last_t = t
        for team, slots in h.items():
            for k, s in enumerate(slots):
                key = (team, k)
                if s == "alive":
                    state[key] = "alive"
                    pend.pop(key, None)
                    continue
                if s == "dead" and state.get(key) == "alive":
                    if key in pend:
                        deaths.append(dict(t=pend.pop(key), team=team, slot=k + 1))
                        state[key] = "dead"
                    else:
                        pend[key] = t
    _flush()

    # 3) Assign a team to each Remaining drop from the nearest helmet death
    used: set[int] = set()
    for d in drops:
        for j, hd in enumerate(deaths):
            if j not in used and 0 <= hd["t"] - d["t"] <= 1.0:
                d["team"] = hd["team"]
                used.add(j)
                break

    # 4) Align feed eliminations to earliest unused Remaining drop
    taken: set[int] = set()
    aligned: list[dict] = []
    for e in feed_events:
        row = dict(e)
        row["victim_team"] = team_map.get(e.get("victim") or "", "")
        row["true_time_s"] = e["feed_first_seen_s"]
        row["time_source"] = "feed (approx)"
        if e.get("type") in ("kill", "eliminated_knocked"):
            ft = float(e["feed_first_seen_s"])
            for j, d in enumerate(drops):
                if j in taken or d["t"] > ft:
                    continue
                if d["team"] and row["victim_team"] and d["team"] != row["victim_team"]:
                    continue
                row["true_time_s"] = d["t"]
                row["time_source"] = (
                    "Remaining drop" + (" + helmet" if d["team"] else "")
                )
                taken.add(j)
                break
        row["feed_delay_s"] = round(
            float(e["feed_first_seen_s"]) - float(row["true_time_s"]), 2
        )
        aligned.append(row)

    return aligned, drops, deaths


# ── round segmentation helper ─────────────────────────────────────────────────

def detect_rounds(
    frames: list[tuple[int, float, np.ndarray]],
    profile: LayoutProfile,
    fps: float = 4.0,
) -> list[dict]:
    """Detect round boundaries from banner visibility transitions.

    Returns list of {round_no, start_s, end_s} (winner/scores filled by caller).
    """
    banner_states: list[tuple[float, bool]] = [
        (ts, _banner_visible(img, profile)) for _, ts, img in frames
    ]

    rounds: list[dict] = []
    in_round = False
    round_start = 0.0
    round_no = 1

    for ts, visible in banner_states:
        if visible and not in_round:
            in_round = True
            round_start = ts
        elif not visible and in_round:
            in_round = False
            rounds.append(dict(round_no=round_no, start_s=round_start, end_s=ts,
                               winner_team=None, result_text=None,
                               blue_score=None, red_score=None))
            round_no += 1

    if in_round:  # video ended mid-round
        last_ts = banner_states[-1][0] if banner_states else 0.0
        rounds.append(dict(round_no=round_no, start_s=round_start, end_s=last_ts,
                           winner_team=None, result_text=None,
                           blue_score=None, red_score=None))

    return rounds


# ── legacy shim ───────────────────────────────────────────────────────────────

def run(frame_dir: str, fps: float, feed_csv: str, prefix: str) -> tuple:
    """Original prototype interface: reads JPEG frames from a directory."""
    _profiles_dir = Path(__file__).parent.parent.parent / "profiles"
    default_json = _profiles_dir / "gameloop-windowed-1080p.json"
    if default_json.exists():
        profile = LayoutProfile.load(default_json)
    else:
        raise FileNotFoundError("profiles/gameloop-windowed-1080p.json not found")

    files = sorted(glob.glob(os.path.join(frame_dir, "f*.jpg")))
    fake_frames = []
    for i, f in enumerate(files):
        img = cv2.imread(f)
        if img is not None:
            fake_frames.append((i, round(i / fps, 3), img))

    feed_events = list(csv.DictReader(open(feed_csv, encoding="utf-8")))
    # Convert to the dict format run_on_frames expects
    converted = []
    for e in feed_events:
        converted.append(dict(
            feed_first_seen_s=float(e["feed_first_seen_s"]),
            feed_last_seen_s=float(e.get("feed_last_seen_s", e["feed_first_seen_s"])),
            killer=e["killer"], type=e["type"], weapon=e.get("weapon", ""),
            victim=e["victim"], sightings=int(e.get("sightings", 1)),
            name_conf=float(e.get("name_conf", 1.0)), flag=e.get("flag", ""),
        ))

    team_map: dict[str, str] = {}   # unknown in legacy mode
    aligned, drops, deaths = run_on_frames(
        fake_frames, converted, profile, team_map, team_size=2, fps=fps
    )

    with open(prefix + "_aligned_events.csv", "w", newline="") as fh:
        cols = ["true_time_s", "time_source", "feed_first_seen_s", "feed_delay_s",
                "killer", "type", "weapon", "victim", "victim_team", "name_conf", "flag"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in aligned:
            w.writerow(r)

    return [], drops, deaths, aligned


if __name__ == "__main__":
    _, drops, deaths, aligned = run(
        sys.argv[1], float(sys.argv[2]), sys.argv[3], sys.argv[4]
    )
    for r in aligned:
        print(
            f"  true {float(r['true_time_s']):6.2f}s [{r['time_source']}]  "
            f"feed {float(r['feed_first_seen_s']):6.2f}s (+{r['feed_delay_s']}s)  "
            f"{r['killer']} --{r['type']}/{r['weapon'] or '-'}--> "
            f"{r['victim']} ({r['victim_team']})"
        )

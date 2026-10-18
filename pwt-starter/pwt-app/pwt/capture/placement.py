"""Where the game picture sits in the frame, and moving it back to where the profile expects it.

The same game picture can land at a different place in an OBS recording. The reference
recordings captured the whole GameLoop window, so the game sits at x=100, y=53 of the
1920x1080 frame (the profile's `game_area`). 2026-10-17 00-54-26 captured the game alone,
at the frame's top-left corner, same size: every HUD element 100 px left and 53 px up, and
the layout check refused it (banner and Remaining at 0%).

A shift by whole pixels puts every HUD element back on the profile's coordinates exactly:
no resampling, so the readers and templates see the same pixels as on a reference recording.
The shift is found by matching one static HUD element (the "Remaining" label, the profile's
`placement.anchor_template`) on frames sampled across the recording. Before anything is moved,
the game picture itself is measured (the part of the frame that changes between samples): it
must be the profile's size, at the place the shift says, wholly inside a frame of the profile's
resolution. The label alone cannot tell a resized picture from a moved one (it still matches
at 0.74-0.77 on a frame scaled by 1-3%).

Only a shift. A game picture of another SIZE is not rescaled (DECISIONS R16: on 2026-10-15
20-40-55, game ~1780x998, rescaling left the Remaining counter readable on 64-82% of frames
against 92%). That, a picture that moves during the recording, or one the frame cuts off, is
a `problem`: the layout check reports it as a blocker and refuses the recording.
The layout check always runs on the frames the readers will see, with its usual thresholds.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass

import cv2, numpy as np


@dataclass
class Placement:
    dx: int = 0            # add to x to reach the profile's coordinates
    dy: int = 0
    frames: int = 0        # sampled frames that were decoded
    agree: int = 0         # ... on which the anchor was found at this shift
    note: str = ""         # for the run log
    problem: str = ""      # a reason to refuse the recording (a layout-check blocker)

    @property
    def moved(self):
        return bool(self.dx or self.dy)

    @property
    def transform(self):
        """frame -> frame for the readers, or None when the recording needs no shift."""
        if not self.moved:
            return None
        dx, dy = self.dx, self.dy
        return lambda frame: shift(frame, dx, dy)


def shift(frame, dx, dy):
    """The frame moved by (dx, dy) whole pixels; what moves in from outside is black."""
    out = np.zeros_like(frame)
    h, w = frame.shape[:2]
    if abs(dx) >= w or abs(dy) >= h:
        return out
    out[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)] = \
        frame[max(-dy, 0):h + min(-dy, 0), max(-dx, 0):w + min(-dx, 0)]
    return out


def anchor_shift(gray, tpl, at, min_score):
    """(dx, dy) that moves the anchor found in *gray* back to *at*, or None if it is not found."""
    m = cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED)
    _, best, _, loc = cv2.minMaxLoc(m)
    if best < min_score:
        return None
    return at[0] - loc[0], at[1] - loc[1]


def picture_rect(s1, s2, n, std_min, min_px):
    """(x0, y0, x1, y1) of the part of the frame that changes between the n sampled frames
    (per-pixel std above std_min on more than min_px pixels of a row / column), or None.
    s1, s2: per-pixel sums of the gray frames and of their squares."""
    if n < 6:
        return None
    mean = s1 / n
    moving = np.sqrt(np.maximum(s2 / n - mean * mean, 0)) > std_min
    rows = np.flatnonzero(moving.sum(1) > min_px)
    cols = np.flatnonzero(moving.sum(0) > min_px)
    if not rows.size or not cols.size:
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def transform_for(profile, path, log=print):
    """The shift a tool that reads raw frames must apply (None for a reference recording).
    Raises ValueError when the HUD is elsewhere and cannot be shifted back: cutting the
    profile's boxes out of such frames would harvest junk (R15)."""
    p = find(profile, path)
    if p.problem:
        raise ValueError(p.problem)
    if p.note:                  # shifted, or read where it is because the label was not found
        log(p.note)
    return p.transform


def find(profile, path, samples=12) -> Placement:
    """Sample frames across the recording and find the shift that puts its HUD on the profile.

    No shift (the reference placement, or the anchor not found often enough at one place) ->
    dx = dy = 0 and the recording is read exactly as before. A shift is taken only when the
    anchor is found at the same place on at least `min_frames` sampled frames and on most of
    the frames it was found on, and the measured game picture is the profile's size at that
    place. A HUD found away from the profile's place that cannot be shifted back is a problem.
    """
    cfg = profile.get("placement")
    if not cfg:
        return Placement(note="profile has no placement anchor")
    tpl = cv2.imread(str(profile.templates / cfg["anchor_template"]), cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        return Placement(note=f"placement anchor {cfg['anchor_template']} not found")
    at = tuple(cfg["anchor_at"])

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open {path}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    idxs = (np.linspace(total * 0.03, total * 0.97, samples).astype(int)
            if total > samples else range(max(total, 1)))
    found, n, s1, s2, size = [], 0, 0.0, 0.0, None
    try:
        for i in idxs:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
            ok, frame = cap.read()
            if not ok:
                continue
            n += 1
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            size = gray.shape[1], gray.shape[0]
            g = gray.astype(np.float32)
            s1, s2 = s1 + g, s2 + g * g
            s = anchor_shift(gray, tpl, at, cfg["min_score"])
            if s is not None:
                found.append(s)
    finally:
        cap.release()

    x0, y0, x1, y1 = profile["game_area"]
    gw, gh = x1 - x0, y1 - y0
    if not found:
        # A picture of another size hides the label from a scale-1 template (2026-10-17 23-59-38: the
        # game fills the 1920x1080 frame, HUD x1.11). The guard's banner and helmet boxes can still hit,
        # so say what is wrong instead of leaving it to the landmark rates.
        rect = picture_rect(s1, s2, n, cfg["rect_std_min"], cfg["rect_min_px"])
        # Only a picture BIGGER than game_area: a board-only clip (the scrolling table moves, the label is
        # hidden) measures smaller and is fine; a smaller resized picture is left to the layout check, where
        # Remaining is critical (hud.CRITICAL). No smaller picture has been measured yet.
        if rect is not None and ((rect[2] - rect[0]) - gw > cfg["rect_tol_px"] or (rect[3] - rect[1]) - gh > cfg["rect_tol_px"]):
            return Placement(frames=n, problem=(
                f"the game picture measures {rect[2] - rect[0]}x{rect[3] - rect[1]} at x={rect[0]}, y={rect[1]}, "
                f"not {gw}x{gh}: it was resized (GameLoop full screen, or the OBS source scaled), so the HUD "
                f"is not where the layout reads it. Run GameLoop in a window and keep the OBS source at its "
                f"native size (right-click it, Transform, Reset Transform)"))
        return Placement(frames=n, note=f"the 'Remaining' label was not found on any of {n} sampled "
                                        f"frames, so the recording is read where it is")
    ranked = Counter(found).most_common()
    (dx, dy), k = ranked[0]
    if len(ranked) > 1 and ranked[1][1] >= cfg["min_frames"]:
        (bx, by), k2 = ranked[1]
        return Placement(frames=n, agree=k, problem=(
            f"the game picture moves during the recording: the HUD is at one place on {k} sampled "
            f"frames and at another on {k2} (shifts {dx:+d},{dy:+d} and {bx:+d},{by:+d}); do not move "
            f"or resize the GameLoop window or the OBS source while recording"))
    if k < cfg["min_frames"] or k * 2 <= len(found):
        return Placement(frames=n, agree=k,
                         note=f"the 'Remaining' label was found on {len(found)} of {n} sampled frames, "
                              f"at most {k} of them at one place: too few to move the recording, "
                              f"so it is read where it is")
    if not (dx or dy):
        return Placement(frames=n, agree=k)

    pw, ph = (profile.get("resolution") or size)
    want = (x0 - dx, y0 - dy, x1 - dx, y1 - dy)
    where = f"the HUD is {-dx:+d},{-dy:+d} px from the layout's place on {k} of {n} sampled frames"
    if size != (pw, ph):
        return Placement(frames=n, agree=k, problem=(
            f"{where}, and the frame is {size[0]}x{size[1]}, not {pw}x{ph}: record on a {pw}x{ph} "
            f"OBS canvas"))
    if want[0] < 0 or want[1] < 0 or want[2] > size[0] or want[3] > size[1]:
        return Placement(frames=n, agree=k, problem=(
            f"{where}, which puts part of the game picture outside the frame"))
    rect = picture_rect(s1, s2, n, cfg["rect_std_min"], cfg["rect_min_px"])
    if rect is None or max(abs(a - b) for a, b in zip(rect, want)) > cfg["rect_tol_px"]:
        got = ("could not be measured" if rect is None else
               f"measures {rect[2] - rect[0]}x{rect[3] - rect[1]} at x={rect[0]}, y={rect[1]}")
        return Placement(frames=n, agree=k, problem=(
            f"{where}, but the game picture {got}, not {gw}x{gh} at x={want[0]}, y={want[1]}: a "
            f"resized picture is not read. Set the GameLoop source in OBS back to its native size "
            f"(right-click it, Transform, Reset Transform) and record again"))
    return Placement(dx, dy, n, k,
                     f"game picture found at x={want[0]}, y={want[1]} (measured {rect[2] - rect[0]}x"
                     f"{rect[3] - rect[1]}; the layout expects {gw}x{gh} at x={x0}, y={y0}; anchor on {k} "
                     f"of {n} sampled frames): every frame is shifted by ({dx:+d}, {dy:+d}) px before it "
                     f"is read, nothing rescaled")

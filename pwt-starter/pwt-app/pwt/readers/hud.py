"""Does this profile actually fit this footage? (handoff gap 8.5)

The failure this exists to stop: a 720p re-encode of a known-good recording ran
to completion and produced *silently wrong* data -- rounds never detected, knocks
recorded as kills, and one player credited with killing himself. Nothing raised,
nothing was flagged, and the CSV looked plausible. `profiles.load()` scales pixel
values when the frame height differs, but scaling is an assumption, not a
guarantee, and when it is wrong every downstream reader fails quietly.

So before the engine runs, sample some frames and confirm the profile's landmarks
are where the profile says they are. Each check reports the fraction of sampled
frames on which a landmark was found; a wrong profile collapses several at once.

This is a structural check, not an accuracy check. It answers "is this the
footage this profile was measured on", not "how good will the output be".
"""
from __future__ import annotations
import cv2, numpy as np

# Minimum hit rate for each landmark across the sampled frames. Measured on the
# reference recordings, then given generous headroom: correct footage clears
# these comfortably, so a near-miss means something really is off.
THRESHOLDS = {
    "banner":    0.15,   # score boxes solid blue/red while a round is live
    "remaining": 0.25,   # the Remaining counter reads a number
    "helmets":   0.15,   # at least half the helmet slots resolve alive/dead
    # The feed panel is drawn only while rows are on screen, so its rate tracks
    # how many kills happened, not whether the profile fits. Measured at 30% on
    # the reference 6v6 recording. Kept as a signal but given a low bar -- the
    # verdict rests on the three landmarks that are part of the permanent HUD.
    "feed_panel": 0.08,
    # Catches gap 8.2: the app finds feed rows and reports zero kills with no
    # error. Needs a roster; skipped without one.
    #
    # It does NOT detect a wrong profile at the right resolution, though that is
    # what it was added for. Measured: pointing the 2v2 profile at 6v6 footage
    # still resolves 57% of rows (32 of 56), because that profile's feed box
    # (100,215,760,480) overlaps the real 6v6 feed (106,280,620,520), so it reads
    # genuine rows alongside the scenery its `text` detector picks up. Row counts
    # mislead for the same reason and in the opposite direction -- the wrong
    # profile finds MORE rows, 170 vs 18 over 60 frames. A same-resolution
    # mismatch is caught by the structural checks below instead, which need no
    # video at all.
    "names_resolve": 0.20,
}

# Structural checks: answered from the profile and the frame size, before any
# pixels are measured. A failure here is never tolerated -- unlike a landmark
# rate, there is no footage for which it could be a near-miss.
#   - aspect ratio differs from the profile: scaling cannot fix it.
#   - no helmet positions for this team size: eliminations lose their team, every
#     one is flagged NO_HELMETS, and `_align` loses its team filter
#     (CLAUDE.md gap 2). This is what separates the two 1080p profiles.

# How many landmarks may fail before the footage is rejected. One failing check
# is tolerated because a short clip can legitimately miss one (a clip entirely
# inside a scoreboard screen shows no banner, for instance).
MAX_FAILURES = 1


class HudCheck:
    def __init__(self, ok, checks, notes, frame_size, profile_size, blockers=()):
        self.ok, self.checks, self.notes = ok, checks, notes
        self.frame_size, self.profile_size = frame_size, profile_size
        self.blockers = list(blockers)

    @property
    def failed(self):
        return [k for k, v in self.checks.items() if v["ok"] is False]

    def report(self):
        """Human-readable block, suitable for a terminal or a GUI text box."""
        w, h = self.frame_size
        pw, ph = self.profile_size
        lines = [f"HUD check: {'PASS' if self.ok else 'FAIL'}",
                 f"  footage {w}x{h}   profile measured at {pw}x{ph}"]
        for b in self.blockers:
            lines.append(f"  FAIL {b}")
        for name, c in self.checks.items():
            mark = "ok  " if c["ok"] else "FAIL"
            lines.append(f"  {mark} {name:<13} found on {c['rate']:>5.0%} of frames "
                         f"(need {c['need']:.0%})")
        for n in self.notes:
            lines.append(f"  note: {n}")
        if not self.ok:
            lines += [
                "",
                "This profile does not fit this footage. Running anyway does not fail",
                "loudly -- it produces a plausible-looking table with wrong rounds,",
                "knocks recorded as kills, and occasional self-kills.",
                "",
                "  - recording at a different resolution needs its own profile",
                "  - a different game mode (aerial TDM) needs its own profile",
                "  - pass --force to run regardless, and treat every row as suspect",
            ]
        return "\n".join(lines)


def check(profile, path, samples=40, team_size=6, roster=()):
    """Sample *samples* frames spread across the clip and test the landmarks.

    *roster* enables the names_resolve check, which is the only one that can
    catch a wrong profile at the correct resolution. Without it the check still
    runs, but says so in its report rather than implying a clean pass.
    """
    from .counters import CounterReader
    from .feed import FeedReader
    from . import names as _names

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open {path}")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    counters = CounterReader(profile)
    feed = FeedReader(profile)

    idxs = (np.linspace(0, max(total - 1, 0), samples).astype(int)
            if total > samples else range(max(total, 1)))

    hits = dict(banner=0, remaining=0, helmets=0, feed_panel=0)
    n = rows_read = rows_resolved = 0
    for i in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, frame = cap.read()
        if not ok:
            continue
        n += 1
        try:
            if counters.banner_visible(frame):
                hits["banner"] += 1
        except Exception:
            pass
        try:
            if counters.read_remaining(frame) is not None:
                hits["remaining"] += 1
        except Exception:
            pass
        try:
            st = counters.helmets(frame, team_size) or {}
            vals = [v for v in st.values()] if isinstance(st, dict) else list(st)
            flat = []
            for v in vals:
                flat.extend(v) if isinstance(v, (list, tuple)) else flat.append(v)
            if flat and sum(1 for v in flat if v) >= len(flat) / 2:
                hits["helmets"] += 1
        except Exception:
            pass
        try:
            if _feed_panel_present(profile, frame):
                hits["feed_panel"] += 1
        except Exception:
            pass
        if roster:
            try:
                for r in feed.rows(frame)[:2]:
                    rows_read += 1
                    raw = _names.ocr_mask(r.row_mask)
                    for tok in raw.split():
                        nm, sc = _names.match(tok, list(roster))
                        if nm and sc >= 0.55:
                            rows_resolved += 1
                            break
            except Exception:
                pass
    cap.release()

    n = max(n, 1)
    checks, notes = {}, []
    for name, need in THRESHOLDS.items():
        if name == "names_resolve":
            if not roster:
                notes.append("no roster supplied, so the names check was skipped -- "
                             "a profile that is wrong at this resolution cannot be "
                             "detected without it")
                continue
            if rows_read == 0:
                checks[name] = dict(rate=0.0, need=need, ok=False)
                notes.append("no kill-feed rows anywhere in the sampled frames: "
                             "either the feed box is wrong or the clip has no kills")
                continue
            rate = rows_resolved / rows_read
            checks[name] = dict(rate=rate, need=need, ok=rate >= need)
            notes.append(f"names check read {rows_read} sampled feed rows, "
                         f"{rows_resolved} resolved to a roster name")
            continue
        rate = hits[name] / n
        checks[name] = dict(rate=rate, need=need, ok=rate >= need)

    pres = profile.get("resolution") or [w, h]
    pw, ph = int(pres[0]), int(pres[1])
    blockers = []

    if (w, h) != (pw, ph):
        notes.append(f"footage is {w}x{h} but this profile was measured at {pw}x{ph}; "
                     f"pixel values were scaled by {h / max(ph, 1):.3f} and that is "
                     f"an assumption, not a guarantee")
    if ph and abs((w / max(h, 1)) - (pw / max(ph, 1))) > 0.02:
        blockers.append("aspect ratio differs from the profile; scaling cannot fix that")

    # Does this profile even claim to know this team size?
    try:
        profile.helmets(team_size)
    except KeyError as e:
        blockers.append(f"profile has no helmet positions for {team_size}v{team_size}: "
                        f"{e.args[0].rstrip('.')}")
        notes.append("without helmets no elimination gets a team, every one is "
                     "flagged NO_HELMETS, and _align loses its team filter")
    except Exception:
        pass

    n_fail = sum(1 for c in checks.values() if not c["ok"])
    ok = (n_fail <= MAX_FAILURES) and not blockers
    if n_fail:
        notes.append(f"{n_fail} landmark(s) below threshold"
                     + ("; one is tolerated" if n_fail <= MAX_FAILURES else ""))
    return HudCheck(ok, checks, notes, (w, h), (pw, ph), blockers)


def _feed_panel_present(profile, frame):
    """The feed's flat dark left padding, the signal the `panel` detector uses.

    Checked structurally rather than by asking the feed for rows: a clip can
    legitimately contain no kills in the sampled frames, but the panel's padding
    is there whenever the HUD is.
    """
    f = profile["feed"]
    x0, y0, x1, y1 = f["box"]
    pads = f.get("padding_px")
    if not pads:
        return False
    band = frame[y0:y1, x0:x1]
    if band.size == 0:
        return False
    g = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    for px in (pads if isinstance(pads, (list, tuple)) else [pads]):
        col = int(px) - x0
        if not (0 <= col < g.shape[1]):
            continue
        strip = g[:, max(col - 2, 0):col + 3].astype(np.float32)
        if strip.size and strip.mean() <= f.get("dark_mean_max", 90) \
                and strip.std() <= f.get("dark_std_max", 25) * 2.5:
            return True
    return False

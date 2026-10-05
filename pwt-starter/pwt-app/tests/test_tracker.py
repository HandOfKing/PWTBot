"""Line tracking and name roles, on synthetic sightings (no video, no OCR engine).

These pin the behaviours that made the elimination count depend on the
sampling rate (handoff 2026-10-05 §3): one feed row must become ONE line however
often it is sampled, and a lone name must never be guessed into the killer slot.
"""
import numpy as np
from pwt.readers import feed, names
from pwt.readers.feed import LineTracker, Row, row_names

ROSTER = ["TheWolverine", "PARABloodthirs", "KG696969", "KhajwaKILL3R", "RGODxEMPEROR", "OmkarKurhade"]


def _row(y, icons, h=34):
    r = Row(y=y, h=h, icons=tuple(icons), icon_scores={i: 0.9 for i in icons},
            row_mask=np.zeros((h + 4, 10), np.uint8), crop=np.zeros((h + 16, 10, 3), np.uint8))
    return r


def _run(script, fps, text):
    """script(t) -> list of Rows on screen at t. Returns confirmed lines."""
    orig = names.ocr_mask
    names.ocr_mask = lambda m: text
    try:
        tr = LineTracker(min_seen_s=0.5, gap_s=1.0, ocr_samples=3)
        out = []
        for k in range(int(6 * fps)):
            t = k / fps
            out += tr.update(t, script(t))
            for f in [f for l in tr.lines for f in l.futures]:
                f.result()                          # deterministic: reads finish within the frame
        out += tr.flush()
        return out, tr
    finally:
        names.ocr_mask = orig


KNOCK = ("weapon_UMP45", "icon_knock")


def test_icon_flicker_is_one_line_at_every_rate():
    # A knock row at the bottom slot for 3.5 s. Between 1.0 and 1.15 s an
    # in-world nameplate crosses it and hides the knock icon; the matcher
    # also double-hits the gun now and then. Seen for real at 57.0 s in
    # Video_Project_9, where it became a phantom kill at 24 fps.
    # The plate passes more than once, so the fragment lives past min_seen_s --
    # that is what let it confirm on the real clip.
    def script(t):
        if not 0.2 <= t < 3.7:
            return []
        if 1.0 <= t < 1.15 or 1.7 <= t < 1.8 or 2.4 <= t < 2.5:
            return [_row(440, ("weapon_UMP45",))]
        if 2.0 <= t < 2.1:
            return [_row(438, ("weapon_UMP45", "icon_knock", "weapon_UMP45"))]
        return [_row(438, KNOCK)]
    for fps in (4, 12, 24, 30):
        lines, _ = _run(script, fps, "KhajwaKILL3R =P KG696969")
        assert len(lines) == 1, (fps, [(l.first_t, l.etype) for l in lines])
        assert lines[0].etype == "knock"


def test_new_row_in_the_same_slot_is_a_new_line():
    # Old knock row sits at the bottom, then a NEW kill row arrives there and
    # the old one moves up (undetected after it moves). Two events, not one.
    def script(t):
        if 0.2 <= t < 2.0:
            return [_row(438, KNOCK)]
        if 2.0 <= t < 4.5:
            return [_row(438, ("weapon_UMP45",))]
        return []
    for fps in (4, 24):
        lines, _ = _run(script, fps, "TheWolverine =P PARABloodthirs")
        assert sorted(l.etype for l in lines) == ["kill", "knock"], fps


def test_flicker_folds_into_its_own_slot_not_a_neighbour():
    # Two rows on screen together: a knock row above, a kill row below. Now
    # and then the kill row is mis-read with a knock icon. Those frames must
    # fold into the kill row (same slot), never into the knock row above.
    def script(t):
        if not 0.2 <= t < 3.0:
            return []
        low = KNOCK if 1.0 <= t < 1.2 else ("weapon_UMP45",)
        return [_row(386, KNOCK), _row(438, low)]
    for fps in (4, 24):
        lines, tr = _run(script, fps, "TheWolverine =P PARABloodthirs")
        assert sorted((l.etype, round(l.hist[0][1])) for l in lines) == [("kill", 455), ("knock", 403)], fps


def test_lone_name_role_comes_from_its_position():
    # two names: killer then victim
    assert row_names('| TheWolverine =P" KGGSESE9 |', ROSTER)[::2] == ("TheWolverine", "KG696969")
    # row caught mid slide-in: killer still off screen -> the name is the VICTIM
    assert row_names("ine =P' PARAbloodthirs", ROSTER)[::2] == (None, "PARABloodthirs")
    # victim unreadable -> the name is the KILLER
    assert row_names("RGODxEWPEROR =P ~~", ROSTER)[::2] == ("RGODxEMPEROR", None)
    # nothing else in the reading: no way to tell -> no role, never a guess
    assert row_names("OmkarKurhade", ROSTER)[::2] == (None, None)
    # one name with junk on both sides: ambiguous -> no role
    assert row_names("I OmkarKurhade J", ROSTER)[::2] == (None, None)


def test_partial_readings_combine_by_role():
    ln = feed.Line(1, frozenset(), 0.0, 1.0, 438, 34, row=_row(438, ()))
    class F:                                        # a finished OCR future
        def __init__(self, s): self.s = s
        def done(self): return True
        def result(self): return self.s
    ln.futures = [F("ine =P PARAbloodthirs"), F("TheWolverine =P ~~")]
    k, _, v, _, _ = ln.vote(ROSTER)
    assert (k, v) == ("TheWolverine", "PARABloodthirs")
    ln.futures = [F("ine =P PARAbloodthirs")]
    k, _, v, _, _ = ln.vote(ROSTER)
    assert (k, v) == (None, "PARABloodthirs")

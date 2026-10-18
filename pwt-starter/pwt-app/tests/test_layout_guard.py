"""The layout check refuses what it cannot read, and says why.

2026-10-17 23-59-38 and 2026-10-18 00-50-39 were recorded with the game picture filling the
1920x1080 frame (HUD x1.11). Banner and helmets still hit their boxes, the Remaining counter read
on 0% of frames, and with one failed landmark tolerated the check passed: a friend's laptop wrote
a workbook with no eliminations. Remaining is now never the tolerated failure (hud.CRITICAL), and
placement names a picture LARGER than the game area even when the scale-1 label is not found.
"""
import cv2, numpy as np
from _util import CLIP, skip
from test_placement import PROF, ANCHOR, AX, AY, _frame, _tmp, _write
from pwt.capture import placement
from pwt.readers import hud


def test_remaining_is_never_the_tolerated_failure():
    """Video_Project_9 with the Remaining counter blacked out: every other landmark passes,
    the check must still refuse."""
    if not CLIP.exists(): skip(f"test clip not found at {CLIP}")
    x0, y0, x1, y1 = PROF["remaining_box"]
    cap = cv2.VideoCapture(str(CLIP))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames = []
    for i in np.linspace(n * 0.05, n * 0.95, 24).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, f = cap.read()
        if ok:
            f[y0:y1, x0:x1] = 0
            frames.append(f)
    cap.release()
    with _tmp() as d:
        chk = hud.check(PROF, _write(d / "no_remaining.avi", frames),
                        roster=["KG696969", "Makjets69", "Sarthakkkd", "BruceWayne³", "TheWolverine"])
    assert chk.failed == ["remaining"], chk.report()                   # the only failure ...
    assert not chk.ok and "never tolerated" in chk.report()           # ... and it is not tolerated


def test_full_frame_picture_is_refused_with_its_reason():
    """The game filling the frame: the picture is measured even when the label is not found."""
    s = 1920 / 1728
    big = cv2.resize(ANCHOR, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    frames = []
    for i in range(12):
        f = _frame(i, at=(0, 0), size=(1920, 1080), label=False)
        y, x = round(AY * s), round(AX * s)
        f[y:y + big.shape[0], x:x + big.shape[1]] = big[..., None]
        frames.append(f)
    with _tmp() as d:
        p = placement.find(PROF, _write(d / "full.avi", frames))
    assert not p.moved and "measures 1920x1080" in p.problem and "window" in p.problem.lower(), p


def test_a_board_only_clip_is_not_refused():
    """A clip cut from a final board (the harvest tools' input): the label is hidden and only the scrolling
    table moves, a region SMALLER than the game picture. That is read where it is, not refused."""
    frames = []
    for i in range(12):
        f = np.zeros((1080, 1920, 3), np.uint8)
        f[53:1025, 100:1828] = 60                                         # static board backdrop
        f[300:900, 200:1800] = np.kron(np.random.default_rng(i).integers(0, 255, (38, 100), dtype=np.uint8),
                                       np.ones((16, 16), np.uint8))[:600, :1600, None]
        frames.append(f)
    with _tmp() as d:
        p = placement.find(PROF, _write(d / "board.avi", frames))
        assert not p.moved and not p.problem and "not found" in p.note, p
        assert placement.transform_for(PROF, d / "board.avi", log=lambda *a: None) is None

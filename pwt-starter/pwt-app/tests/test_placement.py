"""capture/placement.py: a recording whose game picture is the reference size but sits elsewhere
in the frame is shifted back onto the profile; a reference recording is left exactly as it is;
a resized, cut-off or moving picture is refused (DECISIONS M15, R16).

Most tests need no recording: a synthetic "game picture" (random 16-px blocks that change every
frame, with the Remaining label pasted where the HUD draws it) on a black frame. The last one
moves frames of clips/Video_Project_9.mp4 the way 2026-10-17 00-54-26 was recorded (game at the
frame's top-left corner) and skips without the clip.
"""
import gc, tempfile
from contextlib import contextmanager
from pathlib import Path
import cv2, numpy as np
from _util import CLIP, skip
from pwt import process, profiles
from pwt.capture import placement
from pwt.capture.sources import FileReplaySource
from pwt.readers import hud

PROF = profiles.load(profiles.DEFAULT)
CFG = PROF["placement"]
ANCHOR = cv2.imread(str(PROF.templates / CFG["anchor_template"]), cv2.IMREAD_GRAYSCALE)
GX, GY, GX1, GY1 = PROF["game_area"]                      # 100, 53, 1828, 1025
GW, GH = GX1 - GX, GY1 - GY                               # 1728 x 972
AX, AY = CFG["anchor_at"][0] - GX, CFG["anchor_at"][1] - GY   # the label inside the game picture


@contextmanager
def _tmp():
    with tempfile.TemporaryDirectory(prefix="pwt_test_", ignore_cleanup_errors=True) as d:
        yield Path(d)
        gc.collect()                                      # let go of open captures / databases


def _write(path, frames, fps=4):
    """Lossless (FFV1), so the test sees exactly the pixels it wrote."""
    h, w = frames[0].shape[:2]
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"FFV1"), fps, (w, h))
    for f in frames:
        out.write(f)
    out.release()
    return path


def _frame(seed, at=(GX, GY), size=(GW, GH), frame=(1920, 1080), label=True):
    """A black frame with a game picture of *size* at *at*; the label where the HUD draws it."""
    rng = np.random.default_rng(seed)
    gw, gh = size
    pic = np.kron(rng.integers(0, 255, (gh // 16 + 1, gw // 16 + 1), dtype=np.uint8),
                  np.ones((16, 16), np.uint8))[:gh, :gw]
    if label:
        pic[AY:AY + ANCHOR.shape[0], AX:AX + ANCHOR.shape[1]] = ANCHOR
    f = np.zeros((frame[1], frame[0]), np.uint8)
    x, y = at
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + gw, frame[0]), min(y + gh, frame[1])
    f[y0:y1, x0:x1] = pic[y0 - y:y1 - y, x0 - x:x1 - x]
    return cv2.cvtColor(f, cv2.COLOR_GRAY2BGR)


def test_shift_moves_pixels_exactly():
    f = _frame(1, at=(0, 0))
    g = placement.shift(f, 100, 53)
    assert g.shape == f.shape
    assert np.array_equal(g[53:, 100:], f[:-53, :-100])                 # moved, not resampled
    assert not g[:53].any() and not g[:, :100].any()                    # what moved in is black
    assert np.array_equal(placement.shift(g, -100, -53)[:-53, :-100], f[:-53, :-100])
    assert not placement.shift(f, 1920, 0).any()


def test_reference_placement_is_left_alone():
    with _tmp() as d:
        p = placement.find(PROF, _write(d / "ref.avi", [_frame(i) for i in range(12)]))
        assert (p.dx, p.dy) == (0, 0) and p.transform is None and p.agree == 12
        assert not p.note and not p.problem


def test_moved_picture_is_found_and_shifted_back():
    with _tmp() as d:
        frames = [_frame(i, at=(0, 0)) for i in range(12)]
        frames[3] = _frame(3, at=(0, 0), label=False)                    # label hidden (a scoreboard)
        vid = _write(d / "moved.avi", frames)
        p = placement.find(PROF, vid)
        assert (p.dx, p.dy) == (100, 53) and p.agree == 11 and not p.problem
        assert "(+100, +53)" in p.note and "measured 1728x972" in p.note
        gen = FileReplaySource(vid, fps=4, transform=p.transform).frames()
        t, f = next(gen); gen.close()
        assert placement.anchor_shift(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), ANCHOR,
                                      tuple(CFG["anchor_at"]), CFG["min_score"]) == (0, 0)


def test_resized_picture_is_refused_not_shifted():
    """The label alone still matches on a resized picture; the measured size stops the shift
    (2026-10-15 20-40-55: ~1780x998 at y=59)."""
    with _tmp() as d:
        p = placement.find(PROF, _write(d / "big.avi", [_frame(i, at=(0, 59), size=(1780, 998))
                                                       for i in range(12)]))
        assert not p.moved and p.transform is None
        assert "measures 1780x998" in p.problem and "Reset Transform" in p.problem


def test_frame_size_and_bounds_are_checked():
    with _tmp() as d:
        small = placement.find(PROF, _write(d / "canvas.avi", [_frame(i, at=(0, 0), frame=(GW, GH))
                                                              for i in range(12)]))
        assert not small.moved and f"frame is {GW}x{GH}, not 1920x1080" in small.problem
        cut = placement.find(PROF, _write(d / "cut.avi", [_frame(i, at=(300, 200)) for i in range(12)]))
        assert not cut.moved and "outside the frame" in cut.problem


def test_a_picture_that_moves_is_refused():
    with _tmp() as d:
        frames = [_frame(i, at=(0, 0) if i < 6 else (GX, GY)) for i in range(12)]
        p = placement.find(PROF, _write(d / "moving.avi", frames))
        assert not p.moved and "moves during the recording" in p.problem


def test_no_anchor_or_no_agreement_means_no_shift():
    with _tmp() as d:
        p = placement.find(PROF, _write(d / "none.avi", [_frame(i, label=False) for i in range(12)]))
        assert not p.moved and not p.problem and "not found" in p.note
        scattered = [_frame(i, at=(GX - 10 * i, GY)) for i in range(6)]  # never twice at one place
        p = placement.find(PROF, _write(d / "scattered.avi", scattered))
        assert not p.moved and not p.problem and "too few to move" in p.note


def test_corner_recording_passes_the_layout_check_only_once_shifted():
    """Video_Project_9 moved to the frame's corner, as 2026-10-17 00-54-26 was recorded:
    refused as it is (banner and Remaining 0%), passes once placement shifts it back."""
    if not CLIP.exists(): skip(f"test clip not found at {CLIP}")
    cap = cv2.VideoCapture(str(CLIP))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames = []
    for i in np.linspace(n * 0.05, n * 0.95, 24).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, f = cap.read()
        if ok: frames.append(placement.shift(f, -GX, -GY))
    cap.release()
    roster = ["KG696969", "Makjets69", "Sarthakkkd", "BruceWayne³", "TheWolverine", "RGODxEMPEROR"]
    with _tmp() as d:
        vid = _write(d / "corner.avi", frames)
        raw = hud.check(PROF, vid, roster=roster)
        assert not raw.ok and {"banner", "remaining"} <= set(raw.failed)
        p = placement.find(PROF, vid)
        assert (p.dx, p.dy) == (GX, GY) and not p.problem, p
        chk = hud.check(PROF, vid, roster=roster, transform=p.transform)
        assert chk.ok, chk.report()
        r = process.process(vid, roster=roster, db_path=d / "pwt.db", out_dir=d)   # the app's path
        text = r.layout_report or (r.log_path.read_text(encoding="utf-8") if r.log_path else "")
        assert r.layout_ok and "shifted by (+100, +53)" in text, text

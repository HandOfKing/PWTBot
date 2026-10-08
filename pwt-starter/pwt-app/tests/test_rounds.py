"""Rounds, on clips/Video_Project_13.mp4: 18:30-21:00 of 2026-10-04 22-55-47 (Chirag, 2026-10-07).

The clip holds the end of round 15, all of round 16 -- the first round with blue's score at "10",
where the old banner check went blind and the app merged rounds 16-25 -- and the start of 17.
Truth, read off the frames: round 15 has 9 deaths in the clip (Remaining 12 -> 3), round 16 has
6 (12 -> 6, the last four in one team wipe at 115.0 s), and each round's board is up ~2.8 s.

The same answer is required with the banner check switched off after 57 s (the Remaining reset
must start round 16), and with that reset switched off too (round 16's board must create it).
"""
from collections import Counter
from pathlib import Path
import tempfile
from _util import ROOT, has_tesseract, skip
from pwt import db, profiles
from pwt.engine.engine import Engine
from pwt.capture.sources import FileReplaySource

CLIP = ROOT / "clips" / "Video_Project_13.mp4"
ROSTER = ["PARABloodthirs", "RGODxEMPEROR", "Makjets69", "TrishaSingh", "TheWolverine", "KhajwaKILL3R",
          "Anoydyne15op", "KG696969", "StarJohnnysins", "WonderWoman888", "BruceWayne³", "DeathwishツSpy"]


def _run(banner_after=None, reset=True, fps=6):
    if not CLIP.exists(): skip(f"test clip not found at {CLIP}")
    if not has_tesseract(): skip("tesseract not installed")
    d = Path(tempfile.mkdtemp())
    conn = db.connect(d / "pwt.db")
    eng = Engine(profiles.load(), conn, roster=ROSTER, source_file=CLIP.name, recorded_at="2026-10-04 23:14:17",
                 data_dir=d, log=lambda *a: None)
    now = [0.0]
    if banner_after is not None:
        seen = eng.counters.banner_visible
        eng.counters.banner_visible = lambda im: seen(im) and now[0] < banner_after
    if not reset:
        start = eng._start_round
        eng._start_round = lambda t, frame=None, how=None: None if how else start(t, frame, how)
    for t, f in FileReplaySource(CLIP, fps=fps).frames():
        now[0] = t
        eng.process(t, f)
    s = eng.finish()
    mid = s["match_id"]
    q = lambda sql: conn.execute(sql, (mid,)).fetchall()
    elims = Counter(r[0] for r in q("""SELECT r.round_no FROM events e JOIN rounds r ON r.id = e.round_id
        WHERE e.match_id=? AND e.event_type IN ('kill','eliminated_knocked') AND IFNULL(e.flag,'') <> 'NO_DROP'"""))
    boards = {r[0] for r in q("""SELECT r.round_no FROM scoreboard_stats s LEFT JOIN rounds r ON r.id = s.round_id
                                 WHERE s.match_id=?""")}
    no_drop = q("SELECT COUNT(*) FROM events WHERE match_id=? AND flag='NO_DROP'")[0][0]
    named_r1 = q("""SELECT COUNT(*) FROM events e JOIN rounds r ON r.id = e.round_id WHERE e.match_id=?
                    AND r.round_no=1 AND e.event_type='kill' AND e.flag IS NULL""")[0][0]
    return s["rounds"], dict(elims), boards, no_drop, named_r1


def test_rounds_after_a_two_digit_score():
    rounds, elims, boards, no_drop, named_r1 = _run()
    assert rounds == 3
    assert elims == {1: 9, 2: 6}, elims              # = the Remaining counter's drops in each round
    assert boards == {1, 2}                          # filed under their rounds; no "match" board
    assert no_drop == 0
    assert named_r1 == 9                             # every round-15 death named (was mostly "?")


def test_remaining_reset_starts_the_round_when_the_banner_is_missed():
    rounds, elims, boards, no_drop, _ = _run(banner_after=57)
    assert rounds == 3 and elims == {1: 9, 2: 6} and boards == {1, 2} and no_drop == 0, (rounds, elims, boards)


def test_a_board_creates_a_round_nobody_saw_start():
    rounds, elims, boards, no_drop, _ = _run(banner_after=57, reset=False)
    assert rounds == 2 and elims == {1: 9, 2: 6} and boards == {1, 2} and no_drop == 0, (rounds, elims, boards)

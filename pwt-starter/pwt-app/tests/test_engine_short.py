"""Engine acceptance of short lines (rows on screen < min_seen_s), without a video.

Pins the 149.1 s case from Video_Project_9: TheWolverine's knock row on
WonderWoman888 is still on screen, moving up, when his kill row on the same
player slides in below it. The kill is a real second row -- but only the knock
line's LATER sightings show the two were on screen together, so the engine must
look at the line's live sighting list, not a copy taken when the knock was
recorded. (A copy silently dropped this elimination.)
"""
import tempfile
from pathlib import Path
from pwt import db, profiles
from pwt.engine.engine import Engine


class FakeLine:
    def __init__(self, k, v, etype, ts, short=False):
        self.k, self.v, self.etype, self.short = k, v, etype, short
        self.hist = [(t, 455.0) for t in ts]
        self.first_t, self.weapon, self.best_crop = ts[0], None, None

    def vote(self, roster):
        return self.k, 0.95, self.v, 0.95, f"{self.k} =P {self.v}"


def _engine():
    d = Path(tempfile.mkdtemp(prefix="pwt_eng_"))
    conn = db.connect(d / "pwt.db")
    eng = Engine(profiles.load("gameloop-spectator-6v6-1080p"), conn,
                 roster=["TheWolverine", "WonderWoman888"], source_file="t.mkv", data_dir=d, log=None)
    return eng, conn


def _types(conn):
    return [r[0] for r in conn.execute("SELECT event_type FROM events ORDER BY id")]


def test_short_kill_seen_together_with_the_knock_is_kept():
    eng, conn = _engine()
    knock = FakeLine("TheWolverine", "WonderWoman888", "knock", [147.6 + i / 24 for i in range(20)])
    eng._confirm(knock)
    knock.hist += [(149.083, 420.0), (149.125, 410.0)]           # still on screen, moving up
    eng._confirm(FakeLine("TheWolverine", "WonderWoman888", "kill", [149.083, 149.125], short=True))
    assert _types(conn) == ["knock", "kill"]


def test_short_row_with_the_same_pair_but_never_together_is_a_duplicate():
    eng, conn = _engine()
    eng._confirm(FakeLine("TheWolverine", "WonderWoman888", "knock", [147.6 + i / 24 for i in range(20)]))
    # e.g. the first frames of the knock row sliding in without its knock icon
    eng._confirm(FakeLine("TheWolverine", "WonderWoman888", "kill", [148.5, 148.54], short=True))
    assert _types(conn) == ["knock"]


def test_short_row_needs_two_names():
    eng, conn = _engine()
    eng._confirm(FakeLine("TheWolverine", None, "kill", [10.0, 10.04], short=True))
    assert _types(conn) == []

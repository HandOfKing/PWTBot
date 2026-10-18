"""Rooms of up to 8 a side, uneven too (D17): each side's count is read off the banner helmets
while everyone is alive, and each side's helmets are then read at its own count.

Synthetic banners: a gray panel (an empty slot or a gray helmet, both "dead") with white boxes
(live helmets) at the profile's measured slots. The last test uses Video_Project_9 at 30.0 s,
round 1 with all 12 players alive, and skips without the clip.
"""
import cv2, numpy as np
from _util import CLIP, skip
from pwt import profiles
from pwt.readers.counters import CounterReader

P = profiles.load(profiles.DEFAULT)
C = CounterReader(P)


def _banner(blue=(), red=()):
    """A frame whose banner shows white helmets at the given slots and gray everywhere else."""
    f = np.zeros((1080, 1920, 3), np.uint8)
    f[55:135, 540:1400] = 100                                         # panel: reads "dead"
    for x, y in list(blue) + list(red):
        f[y - 11:y + 11, x - 13:x + 13] = 235                         # a live helmet
    return f


def test_every_measured_size_is_read_on_its_own_side():
    for nb in P.helmet_counts("blue"):
        for nr in P.helmet_counts("red"):
            f = _banner(P.helmet_slots("blue", nb), P.helmet_slots("red", nr))
            assert C.side_counts(f) == {"blue": nb, "red": nr}, (nb, nr)


def test_uneven_room_reads_each_side_at_its_own_count():
    f = _banner(P.helmet_slots("blue", 8), P.helmet_slots("red", 7))
    sides = C.side_counts(f)
    assert sides == {"blue": 8, "red": 7}
    states = C.helmets_by_side(f, sides)
    assert [len(states["blue"]), len(states["red"])] == [8, 7]
    assert all(s == "alive" for v in states.values() for s in v)


def test_a_layout_never_measured_is_not_guessed():
    odd = P.helmet_slots("red", 7)[:3]                                # 3 red helmets: never seen
    assert C.side_counts(_banner(P.helmet_slots("blue", 6), odd)) == {"blue": 6, "red": None}
    assert 3 not in P.helmet_counts("red") and 4 not in P.helmet_counts("blue")


def test_a_gray_helmet_looks_like_an_empty_slot():
    """Why the engine reads counts only before the round's first death: blue 8 with the player
    in its first bottom slot eliminated has exactly the white helmets of blue 7."""
    eight = P.helmet_slots("blue", 8)
    out = [p for p in eight if p not in P.helmet_slots("blue", 7)]
    assert len(out) == 1
    f = _banner([p for p in eight if p != out[0]], P.helmet_slots("red", 8))
    assert C.side_counts(f)["blue"] == 7


def test_engine_reads_sides_only_while_everyone_is_alive():
    """The engine takes a round's side counts when the helmets match a layout, add up to the
    Remaining counter, and no death has been counted in the round yet."""
    import tempfile
    from pathlib import Path
    from pwt import db
    from pwt.engine.engine import Engine
    d = Path(tempfile.mkdtemp(prefix="pwt_eng_"))
    eng = Engine(P, db.connect(d / "pwt.db"), roster=["KG696969"], source_file="t.mkv", data_dir=d, log=None)
    eng.round_no = 1
    full = _banner(P.helmet_slots("blue", 8), P.helmet_slots("red", 7))
    eng.rem["value"] = 14                                             # counter disagrees: not taken
    eng._read_sides(1.0, full)
    assert eng.sides is None
    eng.rem["value"] = 15
    eng._read_sides(1.1, full)
    assert eng.sides == {"blue": 8, "red": 7}
    eng.sides = None                                                  # same round after a death:
    eng.drops.append(dict(t=2.0, team=None, used=False, round=1))     # blue 8 minus one looks like 7
    eng.rem["value"] = 14
    gone = [p for p in P.helmet_slots("blue", 8) if p not in P.helmet_slots("blue", 7)]
    eng._read_sides(2.5, _banner([p for p in P.helmet_slots("blue", 8) if p not in gone], P.helmet_slots("red", 7)))
    assert eng.sides is None


def test_a_helmet_pairs_with_its_drop_in_either_order():
    """Video_Project_9 at 24 fps: helmets turn gray 0.17-1.04 s after the counter drops, and can be
    one frame ahead of it. Both orders give the drop its team; a helmet far from any drop does not."""
    import tempfile
    from pathlib import Path
    from pwt import db
    from pwt.engine import engine as E
    d = Path(tempfile.mkdtemp(prefix="pwt_eng_"))
    eng = E.Engine(P, db.connect(d / "pwt.db"), roster=["KG696969"], source_file="t.mkv", data_dir=d, log=None)
    eng.round_no = 1
    eng._add_drop(58.125); eng._add_drop(58.667); eng._add_drop(58.667)    # a wipe, three helmets gray at once
    for slot in (2, 3, 5):
        eng._helmet_death(59.167, "red", slot)
    assert [x["team"] for x in eng.drops] == ["red", "red", "red"]
    eng._helmet_death(70.0, "blue", 0)                                      # gray a frame before its drop
    eng._add_drop(70.0 + E.HELMET_LEAD_S / 2)
    assert eng.drops[-1]["team"] == "blue"
    eng._add_drop(80.0)
    eng._helmet_death(80.0 + E.HELMET_LAG_S + 0.5, "red", 1)               # too late: not this drop's
    eng._helmet_death(90.0, "blue", 2)
    eng._add_drop(90.0 + E.HELMET_LEAD_S + 0.5)                            # helmet too early: not paired
    assert eng.drops[-2]["team"] is None and eng.drops[-1]["team"] is None
    # confirmed out of time order (each signal needs two readings): the helmet greyed AFTER the drop's
    # time but was confirmed before the drop was -- they still pair
    eng._helmet_death(100.4, "red", 3)
    eng._add_drop(100.0)
    assert eng.drops[-1]["team"] == "red"


def test_a_real_6v6_round_start():
    if not CLIP.exists(): skip(f"test clip not found at {CLIP}")
    cap = cv2.VideoCapture(str(CLIP))
    cap.set(cv2.CAP_PROP_POS_MSEC, 30_000)
    ok, f = cap.read()
    cap.release()
    assert ok and C.side_counts(f) == {"blue": 6, "red": 6}
    assert all(s == "alive" for v in C.helmets_by_side(f, {"blue": 6, "red": 6}).values() for s in v)

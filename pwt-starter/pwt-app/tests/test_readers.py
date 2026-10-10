"""Readers on single frames of the one layout (6v6 first-person spectator, GameLoop 1080p).

Fixtures (tests/fixtures), cut from the clips named:
  live_score_10.jpg      Video_Project_13 80.0 s  round 16, blue score "10" (two digits), Remaining 12
  remaining_5.jpg        Video_Project_13 30.0 s  Remaining 5
  remaining_8.jpg        Video_Project_13  9.7 s  Remaining 8 (on screen for 0.2 s)
  helmets_6v6.jpg        Video_Project_13 20.0 s  2 blue and 4 red helmets gray, Remaining 6
  remaining_3_r15.jpg    2026-10-04 22-55-47  1157.0 s  round 15, Remaining 3 (scored 0.78-0.81 on the single old "3"
                         template, under the 0.80 cut-off, so most of its 1.3 s on screen read as unreadable)
  remaining_11_r4.jpg    2026-10-04 22-55-47  262.3 s  Remaining 11 over bright trees (the old library could not read it)
  remaining_3_20_27.jpg  2026-10-04 20-27-36  270.4 s  Remaining 3; remaining_11_20_27.jpg  4.5 s  Remaining 11
                         (the old library could not read either; this match was not used to cut any digit)
  weapon_*_10_01.jpg     2026-10-01 23-12-52  65.3 s grenade, 67.8 s M416, 385.2 s DBS: one knock row each, from a
                         match the weapon templates were NOT built from (docs/weapons.md)
  round_end_dimmed.jpg   Video_Project_9  69.5 s  round-end overlay
  between_rounds.jpg     Video_Project_9  76.0 s  after the board, banner not up yet
  feed_knock_row.jpg     Video_Project_9  22.5 s  one knock row
"""
import cv2
from _util import FIX
from pwt import profiles
from pwt.readers.counters import CounterReader
from pwt.readers.screens import ScreenReader
from pwt.readers.feed import FeedReader

P = profiles.load()
img = lambda n: cv2.imread(str(FIX / f"{n}.jpg"))


def test_screen_states():
    S = ScreenReader(P, CounterReader(P))
    assert S.state(img("helmets_6v6")) == "live"
    assert S.state(img("live_score_10")) == "live"          # missed by the old three-pixel banner check
    assert S.state(img("round_end_dimmed")) == "dimmed"
    assert S.state(img("between_rounds")) == "other"
    assert S.state(img("round_board_6v6")) == "scoreboard"


def test_remaining_every_digit_seen_in_a_6v6_room():
    for frame, v in [("live_score_10", 12), ("helmets_6v6", 6), ("remaining_5", 5), ("remaining_8", 8),
                     ("remaining_3_r15", 3), ("remaining_11_r4", 11),
                     ("remaining_3_20_27", 3), ("remaining_11_20_27", 11)]:   # the last two: a match no digit was harvested from
        assert CounterReader(P).read_remaining(img(frame)) == v, frame


def test_helmets_two_rows_per_team():
    h = CounterReader(P).helmets(img("helmets_6v6"), 6)
    assert h == {"blue": ["dead", "alive", "alive", "alive", "alive", "dead"],
                 "red": ["alive", "alive", "dead", "dead", "dead", "dead"]}
    assert sum(s == "alive" for v in h.values() for s in v) == 6          # = Remaining on that frame


def test_feed_row_grammar():
    rows = FeedReader(P).rows(img("feed_knock_row"), fallback=False)
    assert [r.etype for r in rows] == ["knock"]
    assert rows[0].row_mask is not None and rows[0].row_mask.shape[0] > 5


def test_knock_row_gun_comes_from_the_weapon_library():
    # Three different guns on rows of a match the templates were not built from.
    for frame, gun in [("weapon_grenade_10_01", "Grenade"), ("weapon_m416_10_01", "M416"), ("weapon_dbs_10_01", "DBS")]:
        rows = [r for r in FeedReader(P).rows(img(frame), fallback=False) if r.etype == "knock"]
        assert [r.weapon for r in rows] == [gun], frame


def test_weapon_library_refuses_a_guess():
    from pwt.readers.weapons import WeaponReader
    import numpy as np
    W = WeaponReader(P.templates / "weapons")
    assert len(W.templates) >= 28 and {"M416", "ACE32", "G36C", "S1897", "Molotov", "Car"} <= set(W.templates)
    assert W.read(np.zeros((40, 300), np.uint8), 200) is None          # no icon: unknown, not a guess

"""Readers on single frames of the one layout (6v6 first-person spectator, GameLoop 1080p).

Fixtures (tests/fixtures), cut from the clips named:
  live_score_10.jpg      Video_Project_13 80.0 s  round 16, blue score "10" (two digits), Remaining 12
  remaining_5.jpg        Video_Project_13 30.0 s  Remaining 5
  remaining_8.jpg        Video_Project_13  9.7 s  Remaining 8 (on screen for 0.2 s)
  helmets_6v6.jpg        Video_Project_13 20.0 s  2 blue and 4 red helmets gray, Remaining 6
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
    for frame, v in [("live_score_10", 12), ("helmets_6v6", 6), ("remaining_5", 5), ("remaining_8", 8)]:
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

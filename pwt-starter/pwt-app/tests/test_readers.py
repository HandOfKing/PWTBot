"""Readers on fixture frames cut from the 2026-10-01 test clip (tools/cut_templates.py)."""
import cv2
from _util import FIX, has_tesseract, skip
from pwt import profiles
from pwt.readers.counters import CounterReader
from pwt.readers.screens import ScreenReader, ScoreboardStitcher
from pwt.readers.feed import FeedReader

P = profiles.load("gameloop-windowed-1080p")
C = CounterReader(P)
S = ScreenReader(P, C)
img = lambda n: cv2.imread(str(FIX / f"{n}.jpg"))


def test_screen_states():
    assert S.state(img("live_knock_row")) == "live"
    assert S.state(img("round_end_dimmed")) == "dimmed"
    assert S.state(img("scoreboard_a")) == "scoreboard"
    assert S.state(img("remaining_2_helmets_gray")) == "other"          # banner gone after the round was won


def test_remaining_and_banner_digits():
    assert CounterReader(P).read_remaining(img("live_knock_row")) == 4
    assert CounterReader(P).read_remaining(img("remaining_3")) == 3
    assert CounterReader(P).read_remaining(img("remaining_2_helmets_gray")) == 2
    assert C.scores(img("live_knock_row")) == {"blue": 0, "red": 0}


def test_helmets_alive_while_knocked():
    assert C.helmets(img("live_knock_row"), 2) == {"blue": ["alive", "alive"], "red": ["alive", "alive"]}


def test_scoreboard_values_by_digit_templates():
    """Numbers never touch OCR. One frame may leave a cell blank (score under the bar) but never wrong;
    voting across frames (as the engine does) fills the table."""
    truth = [[2, 2, 2, 2, 200], [0, 0, 0, 0, 0], [0, 0, 0, 0, 52], [0, 0, 0, 0, 0]]
    reads = []
    for n in ("scoreboard_a", "scoreboard_b"):
        im = img(n)
        v = [[S.digits.read(im[yc - 20:yc + 20, a:b])[0] for a, b in P["scoreboard"]["value_cols"].values()]
             for yc in (287, 369, 451, 533)]
        assert all(c is None or c == t for row, trow in zip(v, truth) for c, t in zip(row, trow)), v
        reads.append(v)
    voted = [[next((r[i][j] for r in reads if r[i][j] is not None), None) for j in range(5)] for i in range(4)]
    assert voted == truth


def test_scoreboard_rows_names_and_teams():
    if not has_tesseract(): skip("tesseract not installed")
    st = ScoreboardStitcher(expected=4)
    for n in ("scoreboard_a", "scoreboard_b"):
        st.add(S.read_rows(img(n), roster=[]))
    res = {r["ign"]: r for r in st.result(P["scoreboard"]["value_cols"])}
    assert set(res) == {"TheWolverine", "PARAbloodthirs", "RGODxEMPEROR", "Makjets69"}
    assert res["RGODxEMPEROR"]["team"] == 2 and res["TheWolverine"]["team"] == 1
    assert res["RGODxEMPEROR"]["values"]["damage_dealt"] == 52


def test_feed_row_grammar():
    rows = FeedReader(P).rows(img("live_knock_row"))
    assert [(r.etype, r.weapon) for r in rows] == [("knock", "UMP45")]
    assert rows[0].row_mask is not None and rows[0].row_mask.shape[0] > 5

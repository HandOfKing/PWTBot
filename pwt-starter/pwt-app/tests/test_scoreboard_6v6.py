"""The 6v6 scoreboards: names, five value columns, teams -- on frames, no video needed.

Fixtures (tests/fixtures):
  match_board_top / _mid / _bottom.jpg   end-of-match board, scrolled (Video_Project_11, 0 / 4 / 8 s)
  round_board_6v6.jpg                    round 1 board (Video_Project_9, 73 s) -- its values were
                                         NOT used to harvest the digit templates: held out
True values were read off the frames: match_board_vp11.csv, round_board_vp9_r1.csv.

The rule above all: a number is right or blank, never wrong.
"""
import csv
import cv2
from _util import FIX
from pwt import profiles
from pwt.readers.counters import CounterReader
from pwt.readers.screens import ScreenReader, ScoreboardStitcher

P = profiles.load("gameloop-spectator-6v6-1080p")
S = ScreenReader(P, CounterReader(P))
ROSTER = ["Sarthakkkd", "RGODxEMPEROR", "KG696969", "KhajwaKILL3R", "PARABloodthirs", "OmkarKurhade",
          "TheWolverine", "Strike333", "DeathwishツSpy", "Makjets69", "StarJohnnysins", "Vatsal099999",
          "InnocentDevil", "enriquelatin", "Anoydyne15op", "TrishaSingh", "BruceWayne³", "WonderWoman888"]


def truth(name):
    with open(FIX / name, encoding="utf-8") as fh:
        return {r["player"]: {k: int(v) for k, v in r.items() if k != "player"} for r in csv.DictReader(fh)}


MATCH = truth("match_board_vp11.csv")
TEAM = {n: (1 if i < 6 else 2) for i, n in enumerate(MATCH)}       # file lists team 1 first
img = lambda n: cv2.imread(str(FIX / f"{n}.jpg"))


def test_columns_are_the_five_on_screen():
    assert list(P["scoreboard"]["value_cols"]) == ["eliminations", "assists", "damage_dealt",
                                                   "damage_taken", "knock_outs"]


def test_every_frame_is_right_or_blank_never_wrong():
    seen = right = 0
    for frame, t in [("match_board_top", MATCH), ("match_board_mid", MATCH), ("match_board_bottom", MATCH),
                     ("round_board_6v6", truth("round_board_vp9_r1.csv"))]:
        im = img(frame)
        assert S.state(im) == "scoreboard", frame
        for r in S.read_rows(im, ROSTER, team_size=6):
            if r["name"] not in t: continue
            for c, v in r["values"].items():
                seen += 1
                assert v is None or v == t[r["name"]][c], f"{frame} {r['name']} {c}: {v} != {t[r['name']][c]}"
                right += v is not None
            if frame.startswith("match") and r["team"] is not None:
                assert r["team"] == TEAM[r["name"]], f"{frame} {r['name']} team {r['team']}"
    assert right >= 0.85 * seen, f"only {right}/{seen} cells read"


def test_scrolled_board_stitches_to_all_twelve():
    st = ScoreboardStitcher(12)
    for frame in ("match_board_top", "match_board_mid", "match_board_bottom"):
        st.add(S.read_rows(img(frame), ROSTER, team_size=6))
    res = {r["ign"]: r for r in st.result(P["scoreboard"]["value_cols"])}
    assert set(res) == set(MATCH), sorted(set(res) ^ set(MATCH))
    # never a wrong team. Three JPEG frames are thinner evidence than the engine gets (a re-read
    # every 0.5 s of video gives all 12): the top frame's badge loses its score to compression.
    assert all(res[n]["team"] in (None, TEAM[n]) for n in MATCH)
    assert sum(res[n]["team"] == TEAM[n] for n in MATCH) >= 10
    cells = [(n, c) for n in MATCH for c in MATCH[n]]
    got = [res[n]["values"][c] for n, c in cells]
    assert all(v is None or v == MATCH[n][c] for (n, c), v in zip(cells, got))
    # 54/60 from these three JPEGs; the engine's 0.5 s re-reads of the video give 59/60
    assert sum(v is not None for v in got) >= 52, f"{sum(v is not None for v in got)}/60 cells"


def test_team_badge_does_not_reach_the_other_block():
    # 4.0 s: team 1's badge is on screen, team 2's has not scrolled in yet. KG696969 and
    # StarJohnnysins (team 2) used to take team 1's number.
    rows = {r["name"]: r["team"] for r in S.read_rows(img("match_board_mid"), ROSTER, team_size=6)}
    assert rows.get("KG696969") in (None, 2) and rows.get("StarJohnnysins") in (None, 2)
    assert rows.get("TheWolverine") == 1

"""pwt.awards -- match highlight roles on a synthetic event set, and the one-file workbook.

No recording needed: every number below is built by hand, so a changed rule shows up as a changed test.
"""
import tempfile
from pathlib import Path
import _util  # noqa: F401  (puts the app root on sys.path)
from openpyxl import load_workbook
from pwt import awards, db, export_excel

BLUE = ["B1", "B2", "B3", "B4", "B5", "B6"]
RED = ["R1", "R2", "R3", "R4", "R5", "R6"]
TEAMS = {**{p: "blue" for p in BLUE}, **{p: "red" for p in RED}}


def knock(t, killer, victim, weapon=None, rnd=1):
    return dict(event_type="knock", killer=killer, victim=victim, weapon=weapon, round_no=rnd, true_time_s=t,
                victim_team=TEAMS.get(victim), flag=None)


def death(t, victim, killer=None, rnd=1, flag=None, team="auto"):
    return dict(event_type="kill", killer=killer, victim=victim, weapon=None, round_no=rnd, true_time_s=t,
                victim_team=TEAMS.get(victim) if team == "auto" else team, flag=flag)


def roles(aw, role):
    return {r.player: r.detail for r in aw.roles if r.role == role}


def test_top_three_rival_and_top_three_dominating_pairs_no_minimums():
    pairs = {("B1", "R1"): 9, ("B2", "R2"): 7, ("B3", "R3"): 5, ("B4", "R4"): 2, ("B5", "R5"): 1,   # one-sided
             ("B6", "R6"): 3, ("R6", "B6"): 3}                                                      # an even trade
    ev = [knock(t, k, v) for (k, v), n in pairs.items() for t in range(n)]
    ev += [knock(50 + t, "R5", "B5") for t in range(4)] + [knock(60 + t, "B5", "R5") for t in range(3)]   # 4 : 4 with the 1 above
    aw = awards.compute(ev, TEAMS)
    dom = roles(aw, "Dominating")
    assert set(dom) == {"B1", "B2", "B3"}, dom                     # the 3 biggest leads; B4 (2 knocks) is 4th
    assert "R1 9 times" in dom["B1"] and "100% of the 9 times R1 was knocked" in dom["B1"] and "never knocked back" in dom["B1"]
    riv = roles(aw, "Rival")
    assert set(riv) == {"B6", "R6", "B5", "R5"}, riv               # only two pairs traded knocks at all; no padding to 3
    assert "knocked R6 3 times, was knocked by R6 3 times" in riv["B6"]
    assert not set(dom) & set(riv)                                 # a pair is Rival or Dominating, not both


def test_rival_ranks_even_trades_above_blowouts_and_a_small_pair_still_counts():
    ev = ([knock(i, "B1", "R1") for i in range(10)] + [knock(20, "R1", "B1")]                 # 10 : 1
          + [knock(30 + i, "B2", "R2") for i in range(3)] + [knock(40 + i, "R2", "B2") for i in range(3)]   # 3 : 3
          + [knock(50, "B3", "R3"), knock(51, "R3", "B3")])                                    # 1 : 1, no minimum
    aw = awards.compute(ev, TEAMS)
    riv = roles(aw, "Rival")
    assert set(riv) == {"B1", "R1", "B2", "R2", "B3", "R3"}        # every pair that traded at all, three pairs
    assert not roles(aw, "Dominating")                             # all three pairs are rivals; none repeated as Dominating
    four = ev + [knock(60 + i, "B4", "R4") for i in range(2)] + [knock(70, "R4", "B4")]   # a 4th pair: outranked, dropped
    assert set(roles(awards.compute(four, TEAMS), "Rival")) == {"B1", "R1", "B2", "R2", "B4", "R4"}


def test_grenade_and_molotov_are_separate_roles():
    ev = ([knock(i, "B1", "R1", "Grenade") for i in range(3)] + [knock(10 + i, "B2", "R2", "Grenade") for i in range(2)]
          + [knock(20 + i, "R3", "B4", "Molotov") for i in range(2)] + [knock(30, "R4", "B5", "Molotov")])
    aw = awards.compute(ev, TEAMS)
    assert set(roles(aw, "Grenadier")) == {"B1"}                     # 3 beats 2; Molotov knocks are not grenades
    assert set(roles(aw, "Molotov specialist")) == {"R3"}
    assert "3 grenade knocks" in roles(aw, "Grenadier")["B1"]


def test_one_grenade_is_not_a_grenadier():
    aw = awards.compute([knock(1, "B1", "R1", "Grenade")], TEAMS)
    assert not roles(aw, "Grenadier")


def test_car_knocks_are_credited_to_the_driver_and_zone_to_nobody():
    ev = [knock(1, "B1", "R1", "Car"), knock(5, "B1", "R2", "Car"),
          knock(9, None, "R3", "Zone"), knock(11, "B2", "R4", "Zone")]
    aw = awards.compute(ev, TEAMS)
    assert "2 car knocks" in roles(aw, "Driver")["B1"] and "credited to the driver" in roles(aw, "Driver")["B1"]
    assert aw.knocks_used == 2 and aw.knock_counts == {"B1": 2}      # both Zone rows left out


def test_weapon_class_roles_one_player_per_class():
    ev = ([knock(i, "B1", "R1", "M416") for i in range(6)] + [knock(10, "B1", "R1", "UMP45")]            # AR 6 of 7
          + [knock(20 + i, "B2", "R1", "M416") for i in range(4)] + [knock(25 + i, "B2", "R1", "AKM") for i in range(4)]   # AR 8 of 8
          + [knock(100 + i, "B6", "R1", "M416") for i in range(9)] + [knock(120 + i, "B6", "R1", "UMP45") for i in range(11)]   # AR 9 of 20
          + [knock(30 + i, "B3", "R1", "S12K") for i in range(3)] + [knock(35, "B3", "R1", "M416")]          # shotgun 3 of 4
          + [knock(40 + i, "B4", "R1", "AWM") for i in range(2)]                                            # 2 sniper knocks: too few
          + [knock(50 + i, "B5", "R1", "UMP45") for i in range(3)] + [knock(55, "B5", "R1", "M416")])       # SMG 3 of 4
    aw = awards.compute(ev, TEAMS)
    ar = roles(aw, "AR player")
    assert set(ar) == {"B6"} and "9 knocks with an AR, 45% of their 20" in ar["B6"], ar   # most AR knocks wins, share only shown
    assert set(roles(aw, "SMG player")) == {"B6"} and "11 knocks" in roles(aw, "SMG player")["B6"]   # one player may hold two
    assert set(roles(aw, "Shotgun specialist")) == {"B3"}
    assert not roles(aw, "Sniper player")                                       # 2 knocks is not enough to name one


def test_kills_do_not_count_and_unnamed_or_friendly_rows_are_skipped():
    ev = ([death(i, "R1", killer="B1") for i in range(6)]            # kills only
          + [knock(1, "B1", "R1"), knock(2, None, "R1"), knock(3, "B1", None), knock(4, "B1", "B1"), knock(5, "B1", "B2")])
    aw = awards.compute(ev, TEAMS)
    assert aw.knocks_used == 1 and aw.knocks_seen == 5               # only B1 -> R1 is a usable knock; no board read
    assert list(roles(aw, "Dominating")) == ["B1"] and "R1 1 time" in roles(aw, "Dominating")["B1"]   # the six kills add nothing


def test_basis_line_says_n_of_m():
    ev = [knock(i, "B1", "R1") for i in range(4)]
    assert "Based on 4 of 5 knocks read" in awards.compute(ev, TEAMS, board_knocks=5).basis()
    assert "4 of 4 knock rows seen" in awards.compute(ev, TEAMS).basis()
    assert "board counts 3" in awards.compute(ev, TEAMS, board_knocks=3).basis()   # more rows than the board


def squad(dead_blue, dead_red, t=10.0, step=1.0, rnd=1):
    """Deaths before the clutch: the first `dead_blue` blue players and `dead_red` red players (B6 downwards)."""
    ev, k = [], 0
    for i in range(dead_blue):
        ev.append(death(t + k * step, BLUE[5 - i], rnd=rnd)); k += 1
    for i in range(dead_red):
        ev.append(death(t + k * step, RED[5 - i], rnd=rnd)); k += 1
    return ev


def test_clutch_is_knocking_every_remaining_enemy_when_not_ahead():
    # 2v2, B1 knocks both: a clutch
    aw = awards.compute(squad(4, 4) + [knock(40, "B1", "R1"), knock(41, "B1", "R2")], TEAMS)
    assert "Round 1: knocked all 2 remaining enemies (2 alive against 2)" in roles(aw, "Clutch")["B1"]
    # 3v3 and three knocks
    aw = awards.compute(squad(3, 3) + [knock(40 + i, "B1", f"R{i + 1}") for i in range(3)], TEAMS)
    assert "knocked all 3 remaining enemies (3 alive against 3)" in roles(aw, "Clutch")["B1"]
    # 1v3 and all three; 2v3 and all three
    aw = awards.compute(squad(5, 3) + [knock(40 + i, "B1", f"R{i + 1}") for i in range(3)], TEAMS)
    assert "knocked all 3 remaining enemies (1 alive against 3)" in roles(aw, "Clutch")["B1"]
    aw = awards.compute(squad(4, 3) + [knock(40 + i, "B1", f"R{i + 1}") for i in range(3)], TEAMS)
    assert "(2 alive against 3)" in roles(aw, "Clutch")["B1"]


def test_not_a_clutch():
    two = [knock(40, "B1", "R1"), knock(41, "B1", "R2")]
    assert not roles(awards.compute(squad(3, 4) + two, TEAMS), "Clutch")                # 3v2: the team was ahead
    assert not roles(awards.compute(squad(4, 3) + two, TEAMS), "Clutch")                # 2v3 but only 2 of the 3 knocked
    assert not roles(awards.compute(squad(5, 5) + [knock(40, "B1", "R1")], TEAMS), "Clutch")   # 1v1: one enemy is not a clutch
    assert not roles(awards.compute(squad(4, 4) + [knock(40, "B1", "R1"), knock(41, "B2", "R2")], TEAMS), "Clutch")   # shared
    assert not roles(awards.compute(squad(4, 4) + [knock(40, "B1", "R1"), knock(41, "B1", "R1")], TEAMS), "Clutch")   # one enemy twice
    assert not roles(awards.compute(squad(0, 0) + [knock(40, "B1", "R1"), knock(41, "B1", "R2")], TEAMS), "Clutch")   # 6v6, 2 of 6


def test_clutch_is_judged_per_round_and_kills_do_not_count():
    ev = squad(4, 4, rnd=1) + [knock(40, "B1", "R1", rnd=1), knock(60, "B1", "R2", rnd=2)]       # one knock in each round
    assert not roles(awards.compute(ev, TEAMS), "Clutch")
    kills = squad(4, 4) + [death(40, "R1", killer="B1"), death(41, "R2", killer="B1")]           # kills only
    assert not roles(awards.compute(kills, TEAMS), "Clutch")


def test_clutch_gives_every_doubt_to_the_claim():
    two = [knock(40, "B1", "R1"), knock(41, "B1", "R2")]
    # a death with no team could be an enemy's (so an enemy was left to knock) or ours: 2v2 is not certain any more
    blur = squad(4, 3) + [death(30, None, team=None)]
    assert not roles(awards.compute(blur + two, TEAMS), "Clutch")
    # a blue death 1.5 s before the feed line may have happened after the knock: blue was not certainly down to 2
    soon = squad(3, 4) + [death(38.5, "B5")]
    assert not roles(awards.compute(soon + two, TEAMS), "Clutch")
    # an enemy death 1 s before the line may have come after the knock, so the knocker may owe a third knock
    late_enemy = squad(4, 3) + [death(39.0, "R3")]
    assert not roles(awards.compute(late_enemy + two, TEAMS), "Clutch")
    # a repeated kill row the Remaining counter saw no death for shrinks nobody's team
    dup = [death(10, "B6"), death(11, "B5"), death(12, "B4", flag="NO_DROP"), death(13, "B3", flag="NO_DROP"),
           death(14, "R6"), death(15, "R5"), death(16, "R4"), death(17, "R3")]
    assert not roles(awards.compute(dup + two, TEAMS), "Clutch")                              # blue really lost 2, so it is 4v2: ahead


def test_only_one_clutch_per_match_the_biggest():
    ev = (squad(4, 4, rnd=1) + [knock(40, "B1", "R1", rnd=1), knock(41, "B1", "R2", rnd=1)]                 # 2v2 clutch
          + squad(3, 3, rnd=2, t=110) + [knock(140 + i, "R1", f"B{i + 1}", rnd=2) for i in range(3)])     # 3v3 clutch, red
    aw = awards.compute(ev, TEAMS)
    assert set(roles(aw, "Clutch")) == {"R1"} and "all 3 remaining enemies" in roles(aw, "Clutch")["R1"]


def _match(conn):
    players = [dict(ign=p, team=TEAMS[p]) for p in BLUE[:3] + RED[:3]]
    rounds = [dict(round_no=1, start_s=0, end_s=100)]
    ev = [dict(e, feed_time_s=e["true_time_s"], time_source="test", confidence=1.0) for e in
          [knock(t, "B1", "R1", "M416") for t in range(10, 15)] + [death(20, "R1", killer="B1")]]
    stats = [dict(ign="B1", round_no=None, stat_name="eliminations", value=1),
             dict(ign="B1", round_no=None, stat_name="knock_outs", value=5),
             ] + [dict(ign=i, round_no=None, stat_name="knock_outs", value=0) for i in ("B2", "B3", "R1", "R2", "R3")]
    match = dict(recorded_at="2026-10-10 20:00:00", source_file="synthetic.mkv", team_size=3, mode="rounds")
    return db.save_match(conn, match, players, rounds, ev, stats)


def test_one_workbook_with_four_sheets():
    d = Path(tempfile.mkdtemp())
    conn = db.connect(d / "pwt.db")
    mid = _match(conn)
    wb = load_workbook(export_excel.export_match(conn, mid, d / "m.xlsx", log_lines=["line one", "line two"]))
    assert wb.sheetnames == ["Scoreboard", "Highlights", "Players", "Head to head", "Events", "Run log"]
    assert [c.value for c in wb["Run log"]["A"]][:3] == ["Run log", "line one", "line two"]
    hl = [[c.value for c in row] for row in wb["Highlights"].iter_rows()]
    text = " ".join(str(v) for row in hl for v in row if v)
    assert "Based on 5 of 5 knocks read" in text and "Dominating" in text and "Clutch is the least certain" in text
    assert any(r[0] == "B2" and r[2] == "-" for r in hl)             # players without a role are still listed
    sb = [[c.value for c in row] for row in wb["Scoreboard"].iter_rows()]
    head = next(r for r in sb if r[0] == "Player")
    assert head[:2] == ["Player", "Team"] and "Knock outs" in head and head[-3:] == ["PWT eliminations", "PWT knocks", "Check"]
    assert wb["Events"].max_row == 7
    no_log = load_workbook(export_excel.export_match(conn, mid, d / "n.xlsx"))
    assert no_log.sheetnames == ["Scoreboard", "Highlights", "Players", "Head to head", "Events"]


def test_basis_when_the_board_was_only_partly_read():
    ev = [knock(i, "B1", "R1") for i in range(4)]
    assert "lower bound" in awards.compute(ev, TEAMS, board_knocks=3, board_complete=False).basis()
    assert "Based on 4 of 0" not in awards.compute(ev, TEAMS, board_knocks=0).basis()


def test_scoreboard_check_never_says_ok_without_evidence_and_keeps_teamless_board_rows():
    d = Path(tempfile.mkdtemp())
    conn = db.connect(d / "pwt.db")
    players = [dict(ign="B1", team="blue"), dict(ign="R1", team="red"), dict(ign="B2", team="blue")]
    stats = [dict(ign="B1", round_no=None, stat_name="eliminations", value=0),
             dict(ign="B1", round_no=None, stat_name="knock_outs", value=None),
             dict(ign="Guest", round_no=None, stat_name="eliminations", value=3),
             dict(ign="Guest", round_no=None, stat_name="knock_outs", value=2)]
    mid = db.save_match(conn, dict(recorded_at="2026-10-10 21:00:00", source_file="s2.mkv", team_size=3),
                        players, [dict(round_no=1, start_s=0, end_s=9)], [], stats)
    wb = load_workbook(export_excel.export_match(conn, mid, d / "c.xlsx"))
    rows = {r[0]: r for r in (tuple(c.value for c in row) for row in wb["Scoreboard"].iter_rows()) if r[0]}
    assert "unreadable" in rows["B1"][-1] and rows["B1"][-1] != "OK"
    assert rows["B2"][-1] == "not on the board"
    assert "not in this match's player list" in rows["Guest"][-1] and rows["Guest"][2] == 3


def test_a_failing_highlights_sheet_does_not_lose_the_workbook():
    d = Path(tempfile.mkdtemp())
    conn = db.connect(d / "pwt.db")
    mid = _match(conn)
    real = awards.from_detail
    awards.from_detail = lambda detail: 1 / 0
    try:
        log = ["a"]
        wb = load_workbook(export_excel.export_match(conn, mid, d / "f.xlsx", log_lines=log))
    finally:
        awards.from_detail = real
    assert wb.sheetnames == ["Scoreboard", "Highlights", "Players", "Head to head", "Events", "Run log"]
    assert "could not be built" in wb["Highlights"]["A1"].value and "ZeroDivisionError" in log[-1]
    assert wb["Events"].max_row == 7

"""End-to-end: replay the test clip through the engine and check docs/PWT_BRIEF.md §11 ground truth."""
from _util import CLIP, fresh_db, has_tesseract, skip
from pwt import db, profiles
from pwt.capture.sources import FileReplaySource
from pwt.engine.engine import Engine
from pwt.engine.runner import run


def _replay(roster=()):
    if not CLIP.exists(): skip(f"test clip not found at {CLIP}")
    if not has_tesseract(): skip("tesseract not installed")
    conn, d = fresh_db()
    eng = Engine(profiles.load(), conn, roster=roster, source_file=CLIP.name, recorded_at="2026-10-01 22:53:00",
                 data_dir=d, log=None)
    s = run(FileReplaySource(CLIP, fps=12), eng)
    return conn, s


def _check(conn, s):
    d = db.match_detail(conn, s["match_id"])
    assert s["rounds"] == 1 and s["dropped"] == 0
    r = d["rounds"][0]
    assert r["winner_team"] == "blue" and abs(r["start_s"] - 2.2) < 0.2 and abs(r["end_s"] - 13.46) < 0.1
    ev = [(e["event_type"], e["killer"], e["victim"], e["weapon"]) for e in d["events"]]
    assert ev == [("knock", "TheWolverine", "RGODxEMPEROR", "UMP45"),
                  ("eliminated_knocked", "TheWolverine", "RGODxEMPEROR", None),
                  ("kill", "TheWolverine", "Makjets69", "UMP45")]
    knock, tomb, kill = d["events"]
    assert abs(knock["true_time_s"] - 12.5) <= 0.1 and knock["time_source"] == "feed (approx)"
    assert abs(tomb["true_time_s"] - 13.25) <= 0.1 and 14.5 <= tomb["feed_time_s"] <= 14.8
    assert abs(kill["true_time_s"] - 13.25) <= 0.1 and abs(kill["feed_time_s"] - 16.75) <= 0.1
    assert all(e["flag"] is None for e in d["events"])
    p = {x["ign"]: x for x in d["players"]}
    assert (p["TheWolverine"]["team"], p["Makjets69"]["team"]) == ("blue", "red")
    for x in p.values():                                    # feed eliminations reconcile with the round board
        assert x["eliminations"] == int(x["scoreboard_eliminations"])
    assert p["RGODxEMPEROR"]["damage_dealt"] == 52 and p["TheWolverine"]["damage_dealt"] == 200


def test_replay_with_roster():
    conn, s = _replay(roster=["TheWolverine", "PARAbloodthirs", "RGODxEMPEROR", "Makjets69"])
    _check(conn, s)


def test_replay_without_roster_learns_names_from_scoreboard():
    conn, s = _replay()
    _check(conn, s)

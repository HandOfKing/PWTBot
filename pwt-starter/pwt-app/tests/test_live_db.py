"""LiveMatch (writes during a match), crash recovery, rename/alias."""
from _util import fresh_db
from pwt import db


def _match(conn):
    lm = db.LiveMatch(conn, recorded_at="2026-10-01 22:53:00", mode="rounds", team_size=2)
    for ign, team in [("TheWolverine", "blue"), ("PARAbloodthirs", "blue"), ("RGODxEMPEROR", "red"), ("Makjets69", "red")]:
        lm.set_player(ign, team)
    lm.start_round(1, start_s=2.17)
    e = dict(time_source="feed (approx)", killer="TheWolverine", confidence=0.8)
    lm.add_event(dict(e, true_time_s=12.58, feed_time_s=12.58, event_type="knock", victim="RGODxEMPEROR", weapon="UMP45"))
    a = lm.add_event(dict(e, true_time_s=14.67, feed_time_s=14.67, event_type="eliminated_knocked", victim="RGODxEMPEROR"))
    b = lm.add_event(dict(e, true_time_s=16.75, feed_time_s=16.75, event_type="kill", victim="Makjets69", weapon="UMP45"))
    for eid in (a, b): lm.update_event_time(eid, 13.25, "Remaining drop + helmet")
    lm.end_round(1, end_s=13.5, winner_team="blue", blue_score=1, red_score=0)
    lm.add_stats([{"ign": "TheWolverine", "stat_name": "eliminations", "value": 2},
                  {"ign": "RGODxEMPEROR", "stat_name": "damage_dealt", "value": 52}], round_no=1)
    lm.add_stats([{"ign": "TheWolverine", "stat_name": "eliminations", "value": 2}], round_no=None)
    return lm


def test_live_match_end_to_end():
    conn, _ = fresh_db()
    lm = _match(conn); lm.finish(duration_s=21.5)
    d = db.match_detail(conn, lm.id)
    assert d["match"]["status"] == "processed" and d["match"]["rounds_played"] == 1
    w = {p["ign"]: p for p in d["players"]}["TheWolverine"]
    assert (w["eliminations"], w["knocks"], w["scoreboard_eliminations"]) == (2, 1, 2)
    assert sorted(e["true_time_s"] for e in d["events"]) == [12.58, 13.25, 13.25]
    assert any(s["round_no"] is None for s in d["stats"])


def test_crash_keeps_data():
    conn, _ = fresh_db()
    _match(conn)                                   # no finish(): the app died mid-match
    assert db.recover_interrupted(conn) == 1
    m = db.list_matches(conn)[0]
    assert m["status"] == "interrupted" and m["eliminations"] == 2


def test_rename_keeps_alias_and_merges():
    conn, _ = fresh_db()
    lm = _match(conn); lm.finish()
    db.get_or_create_player(conn, "Makjats69"); conn.commit()      # a misread duplicate
    db.rename_player(conn, "Makjats69", "Makjets69")                # merge into the real one
    assert "Makjats69" in db.known_names(conn) and db.canonical(conn, "Makjats69") == "Makjets69"
    db.rename_player(conn, "PARAbloodthirs", "PARA")                 # plain rename
    assert db.canonical(conn, "PARAbloodthirs") == "PARA"
    assert {p["ign"] for p in db.match_detail(conn, lm.id)["players"]} >= {"PARA", "Makjets69"}

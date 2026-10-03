"""Turn pipeline output into a saved match.

Today the pipeline (pwt/pipeline/killfeed.py + counters.py) writes CSVs; this module reads them.
Phase 1 replaces the CSV hop with direct function calls (see docs/SPEC.md).
"""
import csv
from .db import save_match


def events_from_aligned_csv(path):
    out = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        out.append(dict(true_time_s=float(r["true_time_s"]), feed_time_s=float(r["feed_first_seen_s"]),
                        time_source=r["time_source"], event_type=r["type"], killer=r["killer"] or None,
                        victim=r["victim"] or None, weapon=r["weapon"] or None, victim_team=r["victim_team"] or None,
                        confidence=float(r["name_conf"]) if r["name_conf"] else None, flag=r["flag"] or None))
    return out


def import_test_clip(conn, events_csv):
    """The 21.5 s test clip from 2026-10-01 (round 1 of a 2v2 round-based room)."""
    players = [dict(ign="TheWolverine", team="blue"), dict(ign="PARAbloodthirs", team="blue"),
               dict(ign="RGODxEMPEROR", team="red"), dict(ign="Makjets69", team="red")]
    rounds = [dict(round_no=1, start_s=2.0, end_s=13.46, winner_team="blue", result_text="DRAW",
                   blue_score=1, red_score=0)]
    board = {"TheWolverine": (2, 200), "PARAbloodthirs": (0, 0), "RGODxEMPEROR": (0, 52), "Makjets69": (0, 0)}
    stats = []
    for ign, (el, dmg) in board.items():
        stats += [dict(ign=ign, round_no=1, stat_name="eliminations", value=el),
                  dict(ign=ign, round_no=1, stat_name="damage_dealt", value=dmg)]
    match = dict(recorded_at="2026-10-01 22:53:00", source_file="Video_Project_7.mp4", duration_s=21.5,
                 room_code="26884524", mode="rounds", team_size=2, rounds_played=1, winner_team="blue",
                 layout_profile="gameloop-windowed-1080p", pipeline_version="0.1-prototype")
    return save_match(conn, match, players, rounds, events_from_aligned_csv(events_csv), stats)

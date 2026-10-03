"""Run: python -m pytest tests   (or: python tests/test_db_export.py)"""
import os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openpyxl import load_workbook
from pwt import db, ingest, export_excel

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "test_clip_events.csv"


def _fresh():
    d = tempfile.mkdtemp()
    return db.connect(Path(d) / "pwt.db"), Path(d)


def test_import_is_idempotent_and_reconciles():
    conn, _ = _fresh()
    a = ingest.import_test_clip(conn, SAMPLE)
    b = ingest.import_test_clip(conn, SAMPLE)
    assert a == b
    players = {p["ign"]: p for p in db.match_detail(conn, a)["players"]}
    w = players["TheWolverine"]
    assert (w["eliminations"], w["knocks"], w["deaths"]) == (2, 1, 0)
    assert players["RGODxEMPEROR"]["times_knocked"] == 1 and players["RGODxEMPEROR"]["deaths"] == 1
    for p in players.values():            # feed eliminations must match the round scoreboard
        assert p["eliminations"] == int(p["scoreboard_eliminations"])


def test_events_carry_true_and_feed_time():
    conn, _ = _fresh()
    mid = ingest.import_test_clip(conn, SAMPLE)
    ev = db.match_detail(conn, mid)["events"]
    kill = [e for e in ev if e["victim"] == "Makjets69"][0]
    assert kill["true_time_s"] == 13.25 and kill["feed_delay_s"] == 3.5 and kill["round_no"] == 1


def test_alias_and_list_filters():
    conn, _ = _fresh()
    mid = ingest.import_test_clip(conn, SAMPLE)
    assert db.get_or_create_player(conn, "TheWølverine") == db.get_or_create_player(conn, "TheWolverine")
    assert len(db.list_matches(conn, "2026-10-01", "2026-10-01")) == 1
    assert len(db.list_matches(conn, "2026-10-02")) == 0
    assert len(db.list_matches(conn, player="wolver")) == 1


def test_excel_exports():
    conn, d = _fresh()
    mid = ingest.import_test_clip(conn, SAMPLE)
    wb = load_workbook(export_excel.export_match(conn, mid, d / "m.xlsx"))
    assert wb.sheetnames == ["Summary", "Events", "Rounds", "Scoreboard"]
    assert wb["Events"].max_row == 4
    wb = load_workbook(export_excel.export_range(conn, d / "r.xlsx", "2026-10-01", "2026-10-31"))
    assert wb.sheetnames == ["Matches", "Player totals", "Player per match", "All events"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"): fn(); print("ok", name)

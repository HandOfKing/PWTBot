"""The names a run matches against, and the one-time clean-up of the old command-line results.

2026-10-04 22-55-47 (Chirag's first full-match run of the app): the database still held ~120
misread names from a 2v2-layout run of the old command-line version. The app matched kill-feed
text against all of them; real names lost the margin rule to near-copies and junk like "Pyn"
and "kB" reached the table. Re-matching the same 385 feed rows: 179 named with that list, 312
with the 18-name roster.
"""
import sqlite3, tempfile
from pathlib import Path
import _util  # noqa: F401
from pwt import db, process
from pwt.readers.feed import row_names

ROSTER = ["PARABloodthirs", "RGODxEMPEROR", "Makjets69", "TrishaSingh", "TheWolverine", "KhajwaKILL3R",
          "Anoydyne15op", "KG696969", "StarJohnnysins", "WonderWoman888", "BruceWayne³", "DeathwishツSpy"]
JUNK = ["PARAhJJdrv", "PARABJJdrl", "IARABJJdr", "KGB9O963", "kgG9", "Pyn", "kB", "IABJodrl", "WJgdvrWOOO",
        "SrJJhgglgv", "ThgWygrgv", "Mvkjgl69", "Anoydyneloop", "AnoydynelSop", "DeathwishYSpy"]


def _fresh():
    d = Path(tempfile.mkdtemp())
    return db.connect(d / "pwt.db"), d


def test_roster_names_are_the_roster_and_its_aliases_only():
    conn, _ = _fresh()
    for n in JUNK: db.get_or_create_player(conn, n)
    db.add_alias(conn, "Makjets69", "Makjats69")
    names = db.roster_names(conn, ROSTER)
    assert names == set(ROSTER) | {"Makjats69"}
    assert not names & set(JUNK)


def test_real_feed_readings_resolve_with_the_roster_not_with_stored_junk():
    # Tesseract readings of feed rows of 2026-10-04 22-55-47 (evidence crops ev_296/304/418/494/517),
    # each checked by eye against its crop
    reads = {"AnoydynelSop PPR md PARAblandthirs .": ("Anoydyne15op", "PARABloodthirs"),
             "RGOOxEMPEROR y= — => AnoydynelSop": ("RGODxEMPEROR", "Anoydyne15op"),
             "AnoydyrelSop 7M ef RGODxEMPEROR": ("Anoydyne15op", "RGODxEMPEROR"),
             "Makjets69 Fe Anoydyne!Sop": ("Makjets69", "Anoydyne15op"),
             "-PARAbLondthirs PAR = te KGBSESES": ("PARABloodthirs", "KG696969")}
    for raw, (k, v) in reads.items():
        got = row_names(raw, ROSTER)
        assert (got[0], got[2]) == (k, v), (raw, got)
        junk = row_names(raw, ROSTER + JUNK)                   # the same row against a polluted list
        assert (junk[0], junk[2]) != (k, v), raw                # loses at least one name


def test_default_names_are_last_used_else_bundled_never_the_database():
    conn, d = _fresh()
    for n in JUNK: db.get_or_create_player(conn, n)
    assert "Pyn" not in process.default_roster(d)
    assert "Anoydyne15op" in process.default_roster(d)          # docs/roster.md
    db.save_roster(["A1", "B2"], d)
    assert process.default_roster(d) == ["A1", "B2"]


def test_upgrade_removes_old_command_line_results_and_their_names():
    d = Path(tempfile.mkdtemp())
    conn = db.connect(d / "pwt.db")
    old = db.LiveMatch(conn, recorded_at="2026-10-01 23:12:52", source_file="old.mkv", pipeline_version="0.1-live")
    old.add_event(dict(true_time_s=1, feed_time_s=1, time_source="feed (approx)", event_type="kill",
                       killer="Pyn", victim="kB"))
    old.finish()
    new = db.LiveMatch(conn, recorded_at="2026-10-04 22:55:47", source_file="new.mkv", pipeline_version="0.2-stageA")
    new.add_event(dict(true_time_s=1, feed_time_s=1, time_source="feed (approx)", event_type="kill",
                       killer="TheWolverine", victim="KG696969"))
    new.finish()
    (d / "evidence" / f"match_{old.id}").mkdir(parents=True)
    conn.execute("PRAGMA user_version = 2"); conn.commit(); conn.close()

    conn = db.connect(d / "pwt.db")                              # the new app opens the old database
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert [r[0] for r in conn.execute("SELECT source_file FROM matches")] == ["new.mkv"]
    players = {r[0] for r in conn.execute("SELECT ign FROM players")}
    assert players == {"TheWolverine", "KG696969"}
    assert not (d / "evidence" / f"match_{old.id}").exists()


def test_deleting_a_match_drops_names_only_it_used():
    conn, _ = _fresh()
    lm = db.LiveMatch(conn, recorded_at="2026-10-04 22:55:47", source_file="m.mkv")
    lm.add_event(dict(true_time_s=1, feed_time_s=1, time_source="feed (approx)", event_type="kill",
                      killer="TheWolverine", victim="Pyn"))
    lm.finish()
    db.get_or_create_player(conn, "KG696969"); conn.commit()     # on the roster, in no match yet
    db.delete_match(conn, lm.id, keep_players=ROSTER)
    assert {r[0] for r in conn.execute("SELECT ign FROM players")} == {"KG696969", "TheWolverine"}

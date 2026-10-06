"""Command line: python -m pwt <command>

  python -m pwt replay clips/Video_Project_7.mp4 [--fps 12] [--roster A B ...] [--profile NAME]
  python -m pwt live [--seconds N] [--profile NAME]       Windows; run as admin if GameLoop is elevated
  python -m pwt list [--from D] [--to D] [--player NAME]
  python -m pwt show MATCH_ID
  python -m pwt export --match ID out.xlsx  |  --from 2026-10-01 --to 2026-10-31 out.xlsx
  python -m pwt players [--add NAME ...]   the saved roster (names are matched against it)
  python -m pwt rename OLD NEW             fix a misread name; OLD is kept as an alias
  python -m pwt import-sample              load the old CSV sample (tests of the data layer)
  python -m pwt where                      where the database lives
"""
import argparse, datetime as dt, sys, threading
from pathlib import Path
from . import db, ingest, export_excel, profiles


def _print_match(conn, mid):
    d = db.match_detail(conn, mid)
    m = d["match"]
    print(f"\nMatch #{m['id']}  {m['recorded_at']}  status={m['status']}  rounds={m['rounds_played']}  "
          f"team size={m['team_size']}  ({m['source_file']})")
    if m["notes"]: print("  notes:", m["notes"])
    print("\nRounds:")
    for r in d["rounds"]:
        print(f"  {r['round_no']:>3}  {r['start_s']:7.2f}s -> {r['end_s'] if r['end_s'] is None else format(r['end_s'], '7.2f')}s"
              f"  winner={r['winner_team']}  score {r['blue_score']}-{r['red_score']}")
    print("\nEvents (true time = Remaining drop for eliminations; knocks keep feed time):")
    for e in d["events"]:
        print(f"  r{e['round_no'] or '-'}  true {e['true_time_s']:7.2f}s  feed {e['feed_time_s']:7.2f}s  "
              f"{(e['killer'] or '?'):>16} --{e['event_type']}/{e['weapon'] or '-'}--> {(e['victim'] or '?'):<16} "
              f"[{e['time_source']}]{'  FLAG ' + e['flag'] if e['flag'] else ''}")
    print("\nPlayers (feed vs scoreboard):")
    for p in d["players"]:
        sb = p["scoreboard_eliminations"]
        ok = "" if sb is None else ("OK" if int(sb) == p["eliminations"] else f"MISMATCH board {int(sb)}")
        print(f"  {p['ign']:>16} {p['team'] or '?':<5} elims {p['eliminations']}  knocks {p['knocks']}  deaths {p['deaths']}"
              f"  knocked {p['times_knocked']}  revives>={p['revives_inferred']}  dmg {p['damage_dealt']}  {ok}")
    by_round = {}
    for s in d["stats"]:
        by_round.setdefault(s["round_no"], {}).setdefault(s["ign"], {})[s["stat_name"]] = s["value"]
    for rn, rows in by_round.items():
        print(f"\nScoreboard {'round ' + str(rn) if rn else 'match'}:")
        for ign, v in rows.items():
            print(f"  {ign:>16}  " + "  ".join(f"{k}={v[k]}" for k in sorted(v)))


def _write_csv(conn, mid, out):
    """Flat events table: one row per knock/kill, true time first."""
    import csv as _csv
    d = db.match_detail(conn, mid)
    cols = ["round_no", "true_time_s", "feed_time_s", "time_source", "killer", "event_type",
            "weapon", "victim", "victim_team", "flag"]
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = _csv.writer(fh)
        w.writerow(cols)
        for e in d["events"]:
            w.writerow([e[c] if c in e.keys() else "" for c in cols])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pwt")
    ap.add_argument("--db", help="database file (default: app data folder)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("where")
    s = sub.add_parser("replay"); s.add_argument("file"); s.add_argument("--fps", type=float, default=12)
    s.add_argument("--csv", help="also write the events table to this CSV")
    s.add_argument("--profile", default="gameloop-windowed-1080p"); s.add_argument("--roster", nargs="*", default=[])
    s.add_argument("--recorded-at"); s.add_argument("--realtime", action="store_true"); s.add_argument("--quiet", action="store_true")
    s.add_argument("--team-size", type=int, default=6, help="players per team, for the helmet check")
    s.add_argument("--force", action="store_true",
                   help="run even if the profile does not fit the footage (every row suspect)")
    s.add_argument("--skip-hud-check", action="store_true", help=argparse.SUPPRESS)
    s = sub.add_parser("live"); s.add_argument("--fps", type=float, default=12); s.add_argument("--seconds", type=float)
    s.add_argument("--profile", default="gameloop-windowed-1080p"); s.add_argument("--roster", nargs="*", default=[])
    s = sub.add_parser("show"); s.add_argument("match_id", type=int)
    s = sub.add_parser("players"); s.add_argument("--add", nargs="*", default=[])
    s = sub.add_parser("rename"); s.add_argument("old"); s.add_argument("new")
    s = sub.add_parser("import-sample"); s.add_argument("--csv", default=str(Path(__file__).parent.parent / "samples" / "test_clip_events.csv"))
    s = sub.add_parser("list"); s.add_argument("--from", dest="date_from"); s.add_argument("--to", dest="date_to"); s.add_argument("--player")
    s = sub.add_parser("export"); s.add_argument("out"); s.add_argument("--match", type=int)
    s.add_argument("--from", dest="date_from"); s.add_argument("--to", dest="date_to")
    a = ap.parse_args(argv)

    if a.cmd == "where":
        print(Path(a.db) if a.db else db.data_dir() / "pwt.db"); return
    conn = db.connect(a.db)
    n = db.recover_interrupted(conn)
    if n: print(f"{n} interrupted match(es) from an earlier run were kept and marked 'interrupted'")

    if a.cmd in ("replay", "live"):
        from .engine.engine import Engine
        from .engine.runner import run
        from .capture.sources import FileReplaySource, LiveScreenSource
        prof = profiles.load(a.profile)
        log = (lambda *x: None) if getattr(a, "quiet", False) else print
        if a.cmd == "replay":
            # Stage 0 (ARCHITECTURE.md §3): does this profile fit this footage?
            # Invariant 8 -- mismatched input must fail loudly. Without this the
            # run completes and emits plausible, wrong data (gap 8.5).
            if not a.skip_hud_check:
                from .readers import hud
                roster = list(a.roster) or [r["ign"] for r in
                                            conn.execute("SELECT ign FROM players ORDER BY ign")]
                chk = hud.check(prof, a.file, team_size=a.team_size, roster=roster)
                if not chk.ok or not getattr(a, "quiet", False):
                    print(chk.report())
                if not chk.ok and not a.force:
                    print("\nRefusing to run. Use --force to override.")
                    return 2
                if not chk.ok:
                    print("\n--force given: continuing. Treat every row as suspect.")
            src = FileReplaySource(a.file, fps=a.fps, realtime=a.realtime)
            rec = a.recorded_at or db.recorded_at_from_file(a.file)
            eng = Engine(prof, conn, roster=a.roster, source_file=Path(a.file).name, recorded_at=rec, log=log)
            summary = run(src, eng)
        else:
            src = LiveScreenSource(region=prof.get("capture_region"), fps=a.fps)
            eng = Engine(prof, conn, roster=a.roster, source_file="live",
                         recorded_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), log=print,
                         on_scoreboard=lambda have, exp, done: print(
                             f"   SCOREBOARD {have}/{exp or '?'} rows" + ("  - all captured" if done else "  - SCROLL DOWN")))
            stop = threading.Event()
            if a.seconds: threading.Timer(a.seconds, lambda: (stop.set(), src.stop())).start()
            try:
                summary = run(src, eng, stop_event=stop)
            except KeyboardInterrupt:
                src.stop(); summary = eng.finish()
        print("\nSummary:", summary)
        if summary.get("match_id"):
            _print_match(conn, summary["match_id"])
            if getattr(a, "csv", None):
                print("wrote", _write_csv(conn, summary["match_id"], a.csv))
    elif a.cmd == "show":
        _print_match(conn, a.match_id)
    elif a.cmd == "players":
        for n in a.add: db.get_or_create_player(conn, n)
        conn.commit()
        for r in conn.execute("""SELECT p.ign, p.nickname, GROUP_CONCAT(a.alias, ', ') AS aliases FROM players p
                                 LEFT JOIN player_aliases a ON a.player_id = p.id GROUP BY p.id ORDER BY p.ign"""):
            print(f"  {r['ign']:<20} {r['nickname'] or '':<12} {('aka ' + r['aliases']) if r['aliases'] else ''}")
    elif a.cmd == "rename":
        db.rename_player(conn, a.old, a.new); print(f"{a.old} -> {a.new} (kept as alias)")
    elif a.cmd == "import-sample":
        print("match id", ingest.import_test_clip(conn, a.csv))
    elif a.cmd == "list":
        for m in db.list_matches(conn, a.date_from, a.date_to, a.player):
            print(f"#{m['id']:<4} {m['recorded_at']}  room {m['room_code'] or '-':<10} {m['players']} players  "
                  f"{m['eliminations']} elims  {m['to_review']} to review  [{m['status']}]")
    elif a.cmd == "export":
        if a.match: print(export_excel.export_match(conn, a.match, a.out))
        else:       print(export_excel.export_range(conn, a.out, a.date_from, a.date_to))


if __name__ == "__main__":
    sys.exit(main())

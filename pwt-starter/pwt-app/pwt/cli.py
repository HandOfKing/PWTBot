"""Command line: python -m pwt <command>. `replay` runs exactly what the desktop app runs (pwt.process).

  python -m pwt replay clips/Video_Project_9.mp4 [--fps 12] [--roster A B ...] [--replace] [--force]
  python -m pwt list [--from D] [--to D] [--player NAME]
  python -m pwt show MATCH_ID
  python -m pwt export --match ID out.xlsx  |  --from 2026-10-01 --to 2026-10-31 out.xlsx
  python -m pwt players                    stored players and their aliases
  python -m pwt rename OLD NEW             fix a misread name; OLD is kept as an alias
  python -m pwt where                      where the database lives

Without --roster, replay uses the names of the last run (the app's list), else docs/roster.md.
"""
import argparse, sys
from pathlib import Path
from . import db, export_excel, process


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


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pwt")
    ap.add_argument("--db", help="database file (default: app data folder)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("where")
    s = sub.add_parser("replay"); s.add_argument("file"); s.add_argument("--fps", type=float, default=process.DEFAULT_FPS)
    s.add_argument("--roster", nargs="*", default=[])
    s.add_argument("--out", help="folder for the xlsx / csv / log (default: next to the recording)")
    s.add_argument("--replace", action="store_true", help="replace an earlier result for this recording")
    s.add_argument("--force", action="store_true",
                   help="run even if the layout does not fit the footage (every row suspect)")
    s.add_argument("--quiet", action="store_true")
    s = sub.add_parser("show"); s.add_argument("match_id", type=int)
    sub.add_parser("players")
    s = sub.add_parser("rename"); s.add_argument("old"); s.add_argument("new")
    s = sub.add_parser("list"); s.add_argument("--from", dest="date_from"); s.add_argument("--to", dest="date_to"); s.add_argument("--player")
    s = sub.add_parser("export"); s.add_argument("out"); s.add_argument("--match", type=int)
    s.add_argument("--from", dest="date_from"); s.add_argument("--to", dest="date_to")
    a = ap.parse_args(argv)

    if a.cmd == "where":
        print(Path(a.db) if a.db else db.data_dir() / "pwt.db"); return
    conn = db.connect(a.db)
    n = db.recover_interrupted(conn)
    if n: print(f"{n} interrupted match(es) from an earlier run were kept and marked 'interrupted'")

    if a.cmd == "replay":
        r = process.process(a.file, roster=a.roster, fps=a.fps, out_dir=a.out, force=a.force, replace=a.replace,
                            db_path=a.db, on_log=None if a.quiet else print)
        if r.earlier_match is not None:
            print(f"This recording was processed before (match #{r.earlier_match}). Use --replace."); return 2
        if not r.layout_ok and not r.ok:
            print(r.layout_report + "\n\nRefusing to run. Use --force to override."); return 2
        if not r.ok:
            print(r.error or "No table was produced."); return 1
        print("\nSummary:", r.summary)
        _print_match(conn, r.match_id)
        print("\nwrote", r.xlsx_path, "\n     ", r.csv_path, "\n     ", r.log_path)
    elif a.cmd == "show":
        _print_match(conn, a.match_id)
    elif a.cmd == "players":
        for r in conn.execute("""SELECT p.ign, p.nickname, GROUP_CONCAT(a.alias, ', ') AS aliases FROM players p
                                 LEFT JOIN player_aliases a ON a.player_id = p.id GROUP BY p.id ORDER BY p.ign"""):
            print(f"  {r['ign']:<20} {r['nickname'] or '':<12} {('aka ' + r['aliases']) if r['aliases'] else ''}")
    elif a.cmd == "rename":
        db.rename_player(conn, a.old, a.new); print(f"{a.old} -> {a.new} (kept as alias)")
    elif a.cmd == "list":
        for m in db.list_matches(conn, a.date_from, a.date_to, a.player):
            print(f"#{m['id']:<4} {m['recorded_at']}  room {m['room_code'] or '-':<10} {m['players']} players  "
                  f"{m['eliminations']} elims  {m['to_review']} to review  [{m['status']}]")
    elif a.cmd == "export":
        if a.match: print(export_excel.export_match(conn, a.match, a.out))
        else:       print(export_excel.export_range(conn, a.out, a.date_from, a.date_to))


if __name__ == "__main__":
    sys.exit(main())

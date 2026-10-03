"""Command line: python -m pwt <command>

  python -m pwt import-sample            load the test clip into the database
  python -m pwt list [--from D] [--to D] [--player NAME]
  python -m pwt export --match ID out.xlsx
  python -m pwt export --from 2026-10-01 --to 2026-10-31 out.xlsx
  python -m pwt where                    show where the database lives
"""
import argparse, sys
from pathlib import Path
from . import db, ingest, export_excel


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pwt")
    ap.add_argument("--db", help="database file (default: app data folder)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("where")
    s = sub.add_parser("import-sample"); s.add_argument("--csv", default=str(Path(__file__).parent.parent / "samples" / "test_clip_events.csv"))
    s = sub.add_parser("list"); s.add_argument("--from", dest="date_from"); s.add_argument("--to", dest="date_to"); s.add_argument("--player")
    s = sub.add_parser("export"); s.add_argument("out"); s.add_argument("--match", type=int)
    s.add_argument("--from", dest="date_from"); s.add_argument("--to", dest="date_to")
    a = ap.parse_args(argv)

    if a.cmd == "where":
        print(Path(a.db) if a.db else db.data_dir() / "pwt.db"); return
    conn = db.connect(a.db)
    if a.cmd == "import-sample":
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

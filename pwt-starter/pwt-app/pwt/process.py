"""One recording in, one table out: the whole pipeline behind a single call.

The desktop app (app/main.py) calls `process()` on a worker thread. The steps
are the CLI's (`python -m pwt replay`), in the same order:

  1. layout check (ARCHITECTURE stage 0) -- refuse a profile that does not fit
  2. replay through the engine, reporting progress, stoppable
  3. write the events CSV, the Excel workbook and a log next to the recording

Nothing here knows about Tk; it is tested on its own (tests/test_process.py).
"""
from __future__ import annotations
import csv, datetime as dt, threading, time
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from . import db, export_excel, profiles

DEFAULT_PROFILE = "gameloop-spectator-6v6-1080p"
DEFAULT_FPS = 12


@dataclass
class Result:
    ok: bool                                   # a table was produced
    match_id: int | None = None
    csv_path: Path | None = None
    xlsx_path: Path | None = None
    log_path: Path | None = None
    summary: dict = field(default_factory=dict)
    counts: dict = field(default_factory=dict)
    layout_ok: bool = True
    layout_report: str = ""
    cancelled: bool = False
    error: str = ""
    earlier_match: int | None = None           # set when the recording was processed before (see replace)


def video_info(path):
    """(duration_s, width, height) of a recording, or raise if it can't be opened."""
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise OSError(f"cannot open {path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        return n / fps, int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        cap.release()


def profile_names():
    """Built-in layout profiles, the 6v6 spectator one first."""
    names = sorted(p.stem for p in profiles.BUILTIN.glob("*.json"))
    return sorted(names, key=lambda n: n != DEFAULT_PROFILE)


def saved_roster(conn):
    return [r[0] for r in conn.execute("SELECT ign FROM players ORDER BY ign COLLATE NOCASE")]


def write_events_csv(conn, match_id, out):
    """Flat events table: one row per knock / kill, true time first."""
    d = db.match_detail(conn, match_id)
    cols = ["round_no", "true_time_s", "feed_time_s", "time_source", "killer", "event_type",
            "weapon", "victim", "victim_team", "flag"]
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:     # BOM: Excel reads ツ and ³ right
        w = csv.writer(fh)
        w.writerow(cols)
        for e in d["events"]:
            w.writerow([e[c] if c in e.keys() else "" for c in cols])
    return Path(out)


def match_counts(conn, match_id):
    """Headline numbers for the result panel."""
    q = lambda sql: conn.execute(sql, (match_id,)).fetchone()[0]
    elim = "event_type IN ('kill','eliminated_knocked')"
    return dict(
        eliminations=q(f"SELECT COUNT(*) FROM events WHERE match_id=? AND {elim}"),
        named=q(f"SELECT COUNT(*) FROM events WHERE match_id=? AND {elim} AND killer_id IS NOT NULL "
                f"AND victim_id IS NOT NULL AND flag IS NULL"),
        no_feed_row=q("SELECT COUNT(*) FROM events WHERE match_id=? AND flag='NO_FEED_ROW'"),
        knocks=q("SELECT COUNT(*) FROM events WHERE match_id=? AND event_type='knock'"),
        to_review=q("SELECT COUNT(*) FROM events WHERE match_id=? AND flag IS NOT NULL AND reviewed=0"),
        rounds=q("SELECT COUNT(*) FROM rounds WHERE match_id=?"),
        # end-of-match board: players read, and cells left blank (unreadable, never guessed)
        board_players=q("SELECT COUNT(DISTINCT player_id) FROM scoreboard_stats WHERE match_id=? AND round_id IS NULL"),
        board_blank=q("SELECT COUNT(*) FROM scoreboard_stats WHERE match_id=? AND round_id IS NULL AND value IS NULL"),
    )


def _outputs(path, out_dir):
    """<recording> - PWT.xlsx etc., next to the recording; the data folder if that isn't writable."""
    stem = Path(path).stem
    for d in ([Path(out_dir)] if out_dir else []) + [Path(path).parent, db.data_dir() / "exports"]:
        try:
            d.mkdir(parents=True, exist_ok=True)
            probe = d / ".pwt_write_test"
            probe.write_text("x"); probe.unlink()
            return (d / f"{stem} - PWT.xlsx", d / f"{stem} - PWT events.csv", d / f"{stem} - PWT log.txt")
        except OSError:
            continue
    raise OSError("no writable folder for the results")


def process(path, *, profile_name=DEFAULT_PROFILE, roster=(), fps=DEFAULT_FPS, team_size=6,
            out_dir=None, force=False, replace=False, on_progress=None, on_log=None, stop_event=None,
            db_path=None) -> Result:
    """Run one recording end to end. Safe to call from a worker thread (opens its own DB connection).

    on_progress(done_s, total_s): video seconds processed so far; called often, keep it cheap.
    on_log(line): engine log lines.
    stop_event: set it to stop early; the partial match is kept and marked 'interrupted'.
    replace: the recording was processed before -- delete that result first. Without it the
        call returns at once with earlier_match set (matches are unique per file + time).
    """
    from .engine.engine import Engine
    from .engine.runner import run
    from .capture.sources import FileReplaySource
    from .readers import hud, names

    path = Path(path)
    lines = []
    def log(*a):
        line = " ".join(str(x) for x in a)
        lines.append(line)
        if on_log: on_log(line)

    duration, w, h = video_info(path)
    conn = db.connect(db_path)
    db.recover_interrupted(conn)
    earlier = db.find_match(conn, path.name, db.recorded_at_from_file(path))
    if earlier is not None:
        if not replace:
            return Result(ok=False, earlier_match=earlier)
        db.delete_match(conn, earlier)
    for n in roster:
        if n.strip(): db.get_or_create_player(conn, n.strip())
    conn.commit()
    prof = profiles.load(profile_name)

    log(f"PWT  {dt.datetime.now():%Y-%m-%d %H:%M}  {path.name}  {w}x{h}  {duration / 60:.1f} min")
    log(f"layout {profile_name}  sampling {fps:g} fps  team size {team_size}")
    chk = hud.check(prof, path, team_size=team_size, roster=saved_roster(conn))
    log(chk.report())
    if not chk.ok and not force:
        return Result(ok=False, layout_ok=False, layout_report=chk.report())
    if not chk.ok:
        log("Layout check failed and the run was forced: treat every row as suspect.")

    names.reset_stats()
    src = FileReplaySource(path, fps=fps)
    eng = Engine(prof, conn, roster=[n for n in roster if n.strip()], source_file=path.name,
                 recorded_at=db.recorded_at_from_file(path), log=log, data_dir=db.db_folder(conn))
    last = [0.0]
    def frame_cb(n, t):
        if on_progress and (t - last[0] >= 1.0 or t == 0):       # ~once per video second
            last[0] = t
            on_progress(t, duration)
    t0 = time.perf_counter()
    summary = run(src, eng, stop_event=stop_event, on_frame=frame_cb)
    cancelled = bool(stop_event is not None and stop_event.is_set())
    if on_progress: on_progress(duration if not cancelled else last[0], duration)
    mid = summary.get("match_id")
    log(f"done in {time.perf_counter() - t0:.0f} s: {summary}")
    if mid is None:
        res = Result(ok=False, summary=summary, cancelled=cancelled,
                     error="No round was found in this recording." if not cancelled else "")
        res.log_path = _write_log(path, out_dir, lines)
        return res
    if cancelled:
        conn.execute("UPDATE matches SET status='interrupted', notes=COALESCE(notes || '; ', '') || ? "
                     "WHERE id=?", (f"stopped by the user at {last[0]:.0f} s", mid))
        conn.commit()

    xlsx, csv_path, log_path = _outputs(path, out_dir)
    export_excel.export_match(conn, mid, xlsx)
    write_events_csv(conn, mid, csv_path)
    counts = match_counts(conn, mid)
    log(f"eliminations {counts['eliminations']}  named {counts['named']}  "
        f"no feed row {counts['no_feed_row']}  knocks {counts['knocks']}  rows to review {counts['to_review']}")
    log_path.write_text("\n".join(lines), encoding="utf-8")
    return Result(ok=True, match_id=mid, csv_path=csv_path, xlsx_path=xlsx, log_path=log_path,
                  summary=summary, counts=counts, layout_ok=chk.ok, layout_report=chk.report(),
                  cancelled=cancelled)


def _write_log(path, out_dir, lines):
    try:
        _, _, log_path = _outputs(path, out_dir)
        log_path.write_text("\n".join(lines), encoding="utf-8")
        return log_path
    except OSError:
        return None

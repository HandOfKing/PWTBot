"""PWT data layer: one SQLite file (pwt.db) holds every processed match.

Where the data lives:
  - Portable mode: if a file named 'portable.txt' sits next to PWT.exe, data goes in ./data
  - Otherwise:     %LOCALAPPDATA%\\PWT  (Windows)   or  ~/.local/share/PWT  (Linux/macOS)
  - Override:      environment variable PWT_DATA_DIR
"""
import os, sys, sqlite3, re, datetime as dt
from pathlib import Path

SCHEMA_VERSION = 1
SCHEMA_FILE = Path(__file__).with_name("schema.sql")


def data_dir() -> Path:
    if os.environ.get("PWT_DATA_DIR"):
        d = Path(os.environ["PWT_DATA_DIR"])
    else:
        exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
        if (exe_dir / "portable.txt").exists():
            d = exe_dir / "data"
        elif os.name == "nt":
            d = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PWT"
        else:
            d = Path.home() / ".local" / "share" / "PWT"
    (d / "evidence").mkdir(parents=True, exist_ok=True)
    return d


def connect(path=None) -> sqlite3.Connection:
    path = Path(path) if path else data_dir() / "pwt.db"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    return conn


def init_db(conn):
    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    if ver == 0:
        conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    # future: elif ver < SCHEMA_VERSION: run migrations in order


# ---------- players ----------

def _norm(s):
    return re.sub(r"\s+", "", (s or "")).lower().replace("ø", "o").replace("0", "o")


def get_or_create_player(conn, ign, nickname=None):
    """Exact IGN, then alias, then normalised match; otherwise create."""
    row = conn.execute("SELECT id FROM players WHERE ign = ?", (ign,)).fetchone()
    if row: return row["id"]
    row = conn.execute("SELECT player_id FROM player_aliases WHERE alias = ?", (ign,)).fetchone()
    if row: return row["player_id"]
    for r in conn.execute("SELECT id, ign FROM players"):
        if _norm(r["ign"]) == _norm(ign):
            conn.execute("INSERT OR IGNORE INTO player_aliases(player_id, alias) VALUES (?,?)", (r["id"], ign))
            return r["id"]
    cur = conn.execute("INSERT INTO players(ign, nickname) VALUES (?,?)", (ign, nickname))
    return cur.lastrowid


def add_alias(conn, ign, alias):
    pid = get_or_create_player(conn, ign)
    conn.execute("INSERT OR IGNORE INTO player_aliases(player_id, alias) VALUES (?,?)", (pid, alias))
    conn.commit()


# ---------- matches ----------

OBS_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})[ _](\d{2})-(\d{2})-(\d{2})")


def recorded_at_from_file(path) -> str:
    """OBS default names look like '2026-10-01 22-52-10.mkv'; fall back to the file's modified time."""
    m = OBS_NAME.search(Path(path).name)
    if m:
        return f"{m.group(1)} {m.group(2)}:{m.group(3)}:{m.group(4)}"
    try:
        return dt.datetime.fromtimestamp(Path(path).stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def save_match(conn, match, players, rounds=(), events=(), stats=()):
    """Write one processed match in a single transaction. Returns match id.

    match:   dict with recorded_at, source_file, + optional matches columns
    players: [{'ign', 'team', 'slot'?, 'nickname'?}]
    rounds:  [{'round_no', 'start_s', 'end_s', 'winner_team', 'result_text', 'blue_score', 'red_score'}]
    events:  [{'true_time_s','feed_time_s','time_source','event_type','killer','victim','killer_raw',
               'victim_raw','weapon','victim_team','confidence','flag','round_no'?,'evidence_path'?}]
    stats:   [{'ign','stat_name','value','round_no' (None = end of match),'confidence'?}]
    """
    with conn:
        existing = conn.execute("SELECT id FROM matches WHERE source_file=? AND recorded_at=?",
                                (match["source_file"], match["recorded_at"])).fetchone()
        if existing:
            return existing["id"]
        cols = {k: v for k, v in match.items()}
        cols.setdefault("processed_at", dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        q = f"INSERT INTO matches({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
        mid = conn.execute(q, list(cols.values())).lastrowid

        pid = {}
        for p in players:
            pid[p["ign"]] = get_or_create_player(conn, p["ign"], p.get("nickname"))
            conn.execute("INSERT OR IGNORE INTO match_players(match_id, player_id, team, slot) VALUES (?,?,?,?)",
                         (mid, pid[p["ign"]], p["team"], p.get("slot")))

        rid = {}
        for r in rounds:
            rid[r["round_no"]] = conn.execute(
                "INSERT INTO rounds(match_id, round_no, start_s, end_s, winner_team, result_text, blue_score, red_score)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (mid, r["round_no"], r.get("start_s"), r.get("end_s"), r.get("winner_team"),
                 r.get("result_text"), r.get("blue_score"), r.get("red_score"))).lastrowid

        def player(name):
            if not name: return None
            if name not in pid: pid[name] = get_or_create_player(conn, name)
            return pid[name]

        def round_for(t, explicit):
            if explicit is not None: return rid.get(explicit)
            for r in rounds:
                if r.get("start_s") is not None and r.get("end_s") is not None and r["start_s"] <= t <= r["end_s"] + 6:
                    return rid[r["round_no"]]          # +6 s: feed lines can post after the round ends
            return None

        for e in events:
            t = float(e["true_time_s"])
            conn.execute(
                "INSERT INTO events(match_id, round_id, true_time_s, feed_time_s, time_source, event_type,"
                " killer_id, victim_id, killer_raw, victim_raw, weapon, victim_team, confidence, flag, evidence_path)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (mid, round_for(t, e.get("round_no")), t, float(e["feed_time_s"]), e["time_source"],
                 e["event_type"], player(e.get("killer")), player(e.get("victim")), e.get("killer_raw"),
                 e.get("victim_raw"), e.get("weapon") or None, e.get("victim_team"),
                 e.get("confidence"), e.get("flag") or None, e.get("evidence_path")))

        for s in stats:
            conn.execute(
                "INSERT OR REPLACE INTO scoreboard_stats(match_id, round_id, player_id, stat_name, value, confidence)"
                " VALUES (?,?,?,?,?,?)",
                (mid, rid.get(s.get("round_no")), player(s["ign"]), s["stat_name"], s["value"], s.get("confidence")))

        flagged = conn.execute("SELECT COUNT(*) FROM events WHERE match_id=? AND flag IS NOT NULL", (mid,)).fetchone()[0]
        if flagged and match.get("status") is None:
            conn.execute("UPDATE matches SET status='needs_review' WHERE id=?", (mid,))
    return mid


# ---------- queries for the app ----------

def list_matches(conn, date_from=None, date_to=None, player=None):
    """Matches newest first, with headline numbers. Dates are 'YYYY-MM-DD' (inclusive)."""
    q = """SELECT m.id, m.recorded_at, m.room_code, m.mode, m.team_size, m.rounds_played, m.winner_team, m.status,
                  (SELECT COUNT(*) FROM events e WHERE e.match_id = m.id AND e.event_type IN ('kill','eliminated_knocked')) AS eliminations,
                  (SELECT COUNT(*) FROM events e WHERE e.match_id = m.id AND e.flag IS NOT NULL AND e.reviewed = 0) AS to_review,
                  (SELECT COUNT(*) FROM match_players mp WHERE mp.match_id = m.id) AS players
           FROM matches m WHERE 1=1"""
    args = []
    if date_from: q += " AND date(m.recorded_at) >= ?"; args.append(date_from)
    if date_to:   q += " AND date(m.recorded_at) <= ?"; args.append(date_to)
    if player:
        q += """ AND m.id IN (SELECT mp.match_id FROM match_players mp JOIN players p ON p.id = mp.player_id
                              WHERE p.ign LIKE ? OR p.nickname LIKE ?)"""
        args += [f"%{player}%", f"%{player}%"]
    return conn.execute(q + " ORDER BY m.recorded_at DESC", args).fetchall()


def match_detail(conn, match_id):
    return {
        "match": conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone(),
        "players": conn.execute("SELECT * FROM v_player_match WHERE match_id=? ORDER BY team, eliminations DESC",
                                (match_id,)).fetchall(),
        "events": conn.execute("SELECT * FROM v_events WHERE match_id=? ORDER BY true_time_s, feed_time_s",
                               (match_id,)).fetchall(),
        "rounds": conn.execute("SELECT * FROM rounds WHERE match_id=? ORDER BY round_no", (match_id,)).fetchall(),
        "stats": conn.execute(
            """SELECT r.round_no, p.ign, s.stat_name, s.value, s.confidence
               FROM scoreboard_stats s JOIN players p ON p.id = s.player_id
               LEFT JOIN rounds r ON r.id = s.round_id
               WHERE s.match_id=? ORDER BY r.round_no, p.ign, s.stat_name""", (match_id,)).fetchall(),
    }


def correct_event(conn, event_id, **fields):
    """Used by the review screen: fix killer/victim/type/weapon and mark reviewed."""
    sets, args = [], []
    for k in ("killer", "victim"):
        if k in fields:
            sets.append(f"{k}_id = ?"); args.append(get_or_create_player(conn, fields.pop(k)))
    for k, v in fields.items():
        sets.append(f"{k} = ?"); args.append(v)
    sets.append("reviewed = 1")
    with conn:
        conn.execute(f"UPDATE events SET {', '.join(sets)} WHERE id = ?", args + [event_id])

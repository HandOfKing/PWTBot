"""PWT data layer: one SQLite file (pwt.db) holds every processed match.

Where the data lives:
  - Portable mode: if a file named 'portable.txt' sits next to PWT.exe, data goes in ./data
  - Otherwise:     %LOCALAPPDATA%\\PWT  (Windows)   or  ~/.local/share/PWT  (Linux/macOS)
  - Override:      environment variable PWT_DATA_DIR
"""
import os, sys, sqlite3, re, datetime as dt
from pathlib import Path

SCHEMA_VERSION = 3
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
    elif ver < SCHEMA_VERSION:
        _migrate(conn, ver)


# Views are derived, so a migration that only changes them just drops and rebuilds
# them. Tables are untouched: every CREATE TABLE in schema.sql is IF NOT EXISTS, so
# re-running the script is a no-op for data.
_VIEWS = ("v_events", "v_knock_outcomes", "v_elim_credit", "v_player_match", "v_player_career")


def _migrate(conn, ver):
    # Views are rebuilt on every upgrade. v2: eliminations credited to the latest un-revived
    # knocker (v_elim_credit). v3: scoreboard numbers from the end-of-match board (v_player_match).
    for v in _VIEWS:
        conn.execute(f"DROP VIEW IF EXISTS {v}")
    conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    if ver < 3:
        _drop_pre_app_results(conn)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


def _drop_pre_app_results(conn):
    """v3: one version. Results written by the command-line prototype before the desktop app
    (pipeline 0.1-*, e.g. a 2v2-layout run of a 6v6 file) are removed, with the player names
    they invented. On Chirag's machine that was ~120 misreads ("Pyn", "kB", "PARAhJJdrv") that
    the app then offered as the roster and matched kill-feed names against (2026-10-07)."""
    import shutil
    old = [r[0] for r in conn.execute("SELECT id FROM matches WHERE pipeline_version LIKE '0.1%'")]
    for mid in old:
        conn.execute("DELETE FROM matches WHERE id=?", (mid,))
        shutil.rmtree(db_folder(conn) / "evidence" / f"match_{mid}", ignore_errors=True)
    if old:
        prune_players(conn)


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


def prune_players(conn, keep=()):
    """Delete players nothing refers to any more (no event, scoreboard row or match), except `keep`.
    Their aliases go with them. Returns how many were removed."""
    keep = set(keep)
    gone = [r["id"] for r in conn.execute(
        """SELECT p.id, p.ign FROM players p
           WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.killer_id = p.id OR e.victim_id = p.id)
             AND NOT EXISTS (SELECT 1 FROM scoreboard_stats s WHERE s.player_id = p.id)
             AND NOT EXISTS (SELECT 1 FROM match_players mp WHERE mp.player_id = p.id)""").fetchall()
        if r["ign"] not in keep]
    for pid in gone:
        conn.execute("DELETE FROM players WHERE id=?", (pid,))
    conn.commit()
    return len(gone)


def roster_names(conn, roster):
    """The names to match kill-feed and scoreboard text against for one run: the roster given
    for it plus the aliases of those players -- never every name ever stored. Misreads stored
    by older runs used to sit in that list, steal matches ("PARABloodthirs --kill--> Pyn") and,
    being near-copies of real names, push real matches under the margin rule."""
    out = set()
    for n in roster:
        n = (n or "").strip()
        if not n: continue
        out.add(n)
        pid = get_or_create_player(conn, n)
        out |= {r[0] for r in conn.execute("SELECT alias FROM player_aliases WHERE player_id=?", (pid,))}
        out.add(conn.execute("SELECT ign FROM players WHERE id=?", (pid,)).fetchone()[0])
    conn.commit()
    return out


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


class LiveMatch:
    """Writes a match WHILE it is played (live capture). Every call commits, so a crash or a closed
    laptop keeps everything captured so far; on the next start recover_interrupted() marks it.

        lm = LiveMatch(conn, room_code="26884524", mode="rounds", team_size=8)
        lm.set_player("TheWolverine", "blue")
        lm.start_round(1, start_s=2.0)
        lm.add_event({...})                       # same keys as save_match events
        lm.end_round(1, end_s=13.46, winner_team="blue", blue_score=1, red_score=0)
        lm.add_stats([{"ign": ..., "stat_name": "damage_dealt", "value": 200}], round_no=1)
        lm.add_stats([...], round_no=None)        # end-of-match scoreboard
        lm.finish()
    """

    def __init__(self, conn, recorded_at=None, source_file="live", **cols):
        now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.conn, self.pid, self.rid, self.round_no = conn, {}, {}, None
        row = dict(recorded_at=recorded_at or now, source_file=source_file, processed_at=now, status="live", **cols)
        self.id = conn.execute(f"INSERT INTO matches({','.join(row)}) VALUES ({','.join('?' * len(row))})",
                               list(row.values())).lastrowid
        conn.commit()

    def _player(self, ign):
        if not ign: return None
        if ign not in self.pid: self.pid[ign] = get_or_create_player(self.conn, ign)
        return self.pid[ign]

    def set_player(self, ign, team, slot=None, nickname=None):
        pid = self._player(ign)
        if nickname: self.conn.execute("UPDATE players SET nickname=COALESCE(nickname, ?) WHERE id=?", (nickname, pid))
        self.conn.execute("""INSERT INTO match_players(match_id, player_id, team, slot) VALUES (?,?,?,?)
                             ON CONFLICT(match_id, player_id) DO UPDATE SET team=excluded.team,
                             slot=COALESCE(excluded.slot, match_players.slot)""", (self.id, pid, team, slot))
        self.conn.commit()

    def start_round(self, round_no, start_s=None):
        self.conn.execute("INSERT OR IGNORE INTO rounds(match_id, round_no, start_s) VALUES (?,?,?)",
                          (self.id, round_no, start_s))
        self.rid[round_no] = self.conn.execute("SELECT id FROM rounds WHERE match_id=? AND round_no=?",
                                               (self.id, round_no)).fetchone()["id"]
        self.round_no = round_no
        self.conn.commit()
        return self.rid[round_no]

    def end_round(self, round_no, end_s=None, winner_team=None, result_text=None, blue_score=None, red_score=None):
        if round_no not in self.rid: self.start_round(round_no)
        self.conn.execute("""UPDATE rounds SET end_s=?, winner_team=?, result_text=?, blue_score=?, red_score=?
                             WHERE id=?""", (end_s, winner_team, result_text, blue_score, red_score, self.rid[round_no]))
        self.conn.commit()

    def add_event(self, e):
        rn = e.get("round_no", self.round_no)
        eid = self.conn.execute(
            "INSERT INTO events(match_id, round_id, true_time_s, feed_time_s, time_source, event_type,"
            " killer_id, victim_id, killer_raw, victim_raw, weapon, victim_team, confidence, flag, evidence_path)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (self.id, self.rid.get(rn), float(e["true_time_s"]), float(e["feed_time_s"]), e["time_source"],
             e["event_type"], self._player(e.get("killer")), self._player(e.get("victim")), e.get("killer_raw"),
             e.get("victim_raw"), e.get("weapon") or None, e.get("victim_team"), e.get("confidence"),
             e.get("flag") or None, e.get("evidence_path"))).lastrowid
        self.conn.commit()
        return eid

    def move_events(self, event_ids, round_no):
        """Re-assign events to a round found after they were written (a round seen only by its board)."""
        if round_no not in self.rid: self.start_round(round_no)
        self.conn.executemany("UPDATE events SET round_id=? WHERE id=?", [(self.rid[round_no], i) for i in event_ids])
        self.conn.commit()

    def update_event_time(self, event_id, true_time_s, time_source):
        """Live alignment can improve a time after the line was saved (e.g. a Remaining drop matched later)."""
        self.conn.execute("UPDATE events SET true_time_s=?, time_source=? WHERE id=?", (true_time_s, time_source, event_id))
        self.conn.commit()

    def add_stats(self, stats, round_no=None):
        """round_no=None -> end-of-match scoreboard. A later end-of-match board replaces an earlier
        one (round_id NULL is never equal in SQL, so the UNIQUE key cannot do it)."""
        rid = self.rid.get(round_no) if round_no is not None else None
        if round_no is None:
            self.conn.execute("DELETE FROM scoreboard_stats WHERE match_id=? AND round_id IS NULL", (self.id,))
        for s in stats:
            self.conn.execute(
                "INSERT OR REPLACE INTO scoreboard_stats(match_id, round_id, player_id, stat_name, value, confidence)"
                " VALUES (?,?,?,?,?,?)",
                (self.id, rid, self._player(s["ign"]), s["stat_name"], s["value"], s.get("confidence")))
        self.conn.commit()

    def finish(self, status=None, **cols):
        c = self.conn
        flagged = c.execute("SELECT COUNT(*) FROM events WHERE match_id=? AND flag IS NOT NULL", (self.id,)).fetchone()[0]
        cols.setdefault("rounds_played", c.execute("SELECT COUNT(*) FROM rounds WHERE match_id=?", (self.id,)).fetchone()[0])
        cols["status"] = status or ("needs_review" if flagged else "processed")
        cols["processed_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute(f"UPDATE matches SET {', '.join(k + '=?' for k in cols)} WHERE id=?", list(cols.values()) + [self.id])
        c.commit()


def recover_interrupted(conn):
    """Call at app start: matches still 'live' were cut off (crash, closed app). Keep their data, mark them."""
    n = conn.execute("UPDATE matches SET status='interrupted' WHERE status='live'").rowcount
    conn.commit()
    return n


# ---------- queries for the app ----------

def list_matches(conn, date_from=None, date_to=None, player=None):
    """Matches newest first, with headline numbers. Dates are 'YYYY-MM-DD' (inclusive)."""
    q = """SELECT m.id, m.recorded_at, m.source_file, m.room_code, m.mode, m.team_size, m.rounds_played, m.winner_team, m.status,
                  (SELECT COUNT(*) FROM events e WHERE e.match_id = m.id AND e.event_type IN ('kill','eliminated_knocked')
                      AND IFNULL(e.flag, '') <> 'NO_DROP') AS eliminations,
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


def find_match(conn, source_file, recorded_at):
    """Id of an earlier result for the same recording, or None (matches are unique per file + time)."""
    r = conn.execute("SELECT id FROM matches WHERE source_file=? AND recorded_at=?",
                     (source_file, recorded_at)).fetchone()
    return r[0] if r else None


def db_folder(conn) -> Path:
    """The folder of this connection's database file; evidence images live beside it."""
    return Path(conn.execute("PRAGMA database_list").fetchone()[2]).parent


def delete_match(conn, match_id, keep_players=()):
    """Remove a match, everything hanging off it (cascade), its evidence images -- the ones
    beside THIS database, never another data folder's -- and players only it referred to
    (misread names), except `keep_players`."""
    import shutil
    with conn:
        conn.execute("DELETE FROM matches WHERE id=?", (match_id,))
    shutil.rmtree(db_folder(conn) / "evidence" / f"match_{match_id}", ignore_errors=True)
    prune_players(conn, keep_players)


# ---------- the player list used last time ----------

def last_roster(folder=None):
    """Names from the last run (roster.txt in the data folder), or [] if there was none."""
    p = Path(folder or data_dir()) / "roster.txt"
    if not p.exists(): return []
    return [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]


def save_roster(names, folder=None):
    p = Path(folder or data_dir()) / "roster.txt"
    p.write_text("# the player names used for the last run, one per line\n" + "\n".join(names) + "\n",
                 encoding="utf-8")


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


def rename_player(conn, old, new):
    """Fix a misread name once: events, scoreboards and match rows move to `new`; `old` becomes an alias so
    future matches resolve to `new` automatically. Merges if `new` already exists."""
    src = conn.execute("SELECT id FROM players WHERE ign=?", (old,)).fetchone()
    if not src: raise KeyError(old)
    dst = conn.execute("SELECT id FROM players WHERE ign=?", (new,)).fetchone()
    with conn:
        if not dst:
            conn.execute("UPDATE players SET ign=? WHERE id=?", (new, src["id"]))
            conn.execute("INSERT OR IGNORE INTO player_aliases(player_id, alias) VALUES (?,?)", (src["id"], old))
            return src["id"]
        a, b = src["id"], dst["id"]
        for col in ("killer_id", "victim_id"):
            conn.execute(f"UPDATE events SET {col}=? WHERE {col}=?", (b, a))
        conn.execute("UPDATE OR IGNORE scoreboard_stats SET player_id=? WHERE player_id=?", (b, a))
        conn.execute("UPDATE OR IGNORE match_players SET player_id=? WHERE player_id=?", (b, a))
        conn.execute("UPDATE player_aliases SET player_id=? WHERE player_id=?", (b, a))
        conn.execute("DELETE FROM scoreboard_stats WHERE player_id=?", (a,))
        conn.execute("DELETE FROM match_players WHERE player_id=?", (a,))
        conn.execute("DELETE FROM players WHERE id=?", (a,))
        conn.execute("INSERT OR IGNORE INTO player_aliases(player_id, alias) VALUES (?,?)", (b, old))
    return b


def known_names(conn):
    """Every exact IGN and alias on file: the roster the engine matches feed and scoreboard names against."""
    return {r[0] for r in conn.execute("SELECT ign FROM players UNION SELECT alias FROM player_aliases")}


def canonical(conn, name):
    """Alias -> its player's IGN (or the name itself)."""
    r = conn.execute("SELECT p.ign FROM player_aliases a JOIN players p ON p.id=a.player_id WHERE a.alias=?",
                     (name,)).fetchone()
    return r[0] if r else name


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

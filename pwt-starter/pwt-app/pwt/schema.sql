-- PWT database schema (SQLite). One file, pwt.db, holds every processed match.
-- Bump PRAGMA user_version and add a migration in db.py when this changes.

PRAGMA foreign_keys = ON;

-- One row per processed recording (= one room / match).
CREATE TABLE IF NOT EXISTS matches (
    id               INTEGER PRIMARY KEY,
    recorded_at      TEXT NOT NULL,              -- local date-time 'YYYY-MM-DD HH:MM:SS' (OBS filename, else file time)
    processed_at     TEXT NOT NULL,
    source_file      TEXT NOT NULL,              -- file name only, e.g. '2026-10-01 22-52-10.mkv'
    source_deleted   INTEGER NOT NULL DEFAULT 0, -- 1 once the app deleted the video
    duration_s       REAL,
    room_code        TEXT,                       -- WoW "Creation Code" shown on the HUD
    mode             TEXT,                       -- 'rounds' | 'classic' | ...
    team_size        INTEGER,                    -- 4 .. 8
    rounds_played    INTEGER,
    winner_team      TEXT,                       -- 'blue' | 'red' | 'draw'
    layout_profile   TEXT,                       -- calibration profile used
    pipeline_version TEXT,
    status           TEXT NOT NULL DEFAULT 'processed',  -- processed | needs_review | failed
    notes            TEXT,
    UNIQUE (source_file, recorded_at)            -- re-importing the same file is a no-op
);
CREATE INDEX IF NOT EXISTS ix_matches_recorded ON matches(recorded_at);

-- Every person ever seen. ign = exact in-game name as the scoreboard shows it.
CREATE TABLE IF NOT EXISTS players (
    id         INTEGER PRIMARY KEY,
    ign        TEXT NOT NULL UNIQUE,
    nickname   TEXT,                             -- what the group calls them
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- Other spellings that map to the same player (old IGNs, stylised characters, OCR variants).
CREATE TABLE IF NOT EXISTS player_aliases (
    id        INTEGER PRIMARY KEY,
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    alias     TEXT NOT NULL UNIQUE
);

-- Who played in which match, on which team.
CREATE TABLE IF NOT EXISTS match_players (
    match_id  INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    team      TEXT NOT NULL,                     -- 'blue' | 'red'
    slot      INTEGER,                           -- helmet slot in the banner, if known
    PRIMARY KEY (match_id, player_id)
);

-- Round-based rooms: one row per round. Classic rooms: a single round 1.
CREATE TABLE IF NOT EXISTS rounds (
    id          INTEGER PRIMARY KEY,
    match_id    INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    round_no    INTEGER NOT NULL,
    start_s     REAL,                            -- seconds from the start of the recording
    end_s       REAL,
    winner_team TEXT,
    result_text TEXT,                            -- banner text, e.g. 'DRAW'
    blue_score  INTEGER,
    red_score   INTEGER,
    UNIQUE (match_id, round_no)
);

-- Kill-feed events with their best-known true time.
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY,
    match_id      INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    round_id      INTEGER REFERENCES rounds(id) ON DELETE SET NULL,
    true_time_s   REAL NOT NULL,                 -- seconds from recording start
    feed_time_s   REAL NOT NULL,                 -- when the line appeared in the feed
    time_source   TEXT NOT NULL,                 -- 'Remaining drop + helmet' | 'Remaining drop' | 'feed (approx)'
    event_type    TEXT NOT NULL CHECK (event_type IN ('knock','kill','eliminated_knocked','other')),
    killer_id     INTEGER REFERENCES players(id),
    victim_id     INTEGER REFERENCES players(id),
    killer_raw    TEXT,                          -- what was read, before roster matching
    victim_raw    TEXT,
    weapon        TEXT,
    victim_team   TEXT,
    confidence    REAL,                          -- 0..1 name-match confidence
    flag          TEXT,                          -- e.g. 'LOW_CONF' -> shown for review
    reviewed      INTEGER NOT NULL DEFAULT 0,    -- 1 once a person checked / corrected it
    evidence_path TEXT                           -- small PNG of the feed line, relative to the data folder
);
CREATE INDEX IF NOT EXISTS ix_events_match ON events(match_id, true_time_s);

-- Scoreboard numbers in long form (column meanings vary by room, so stats are named, not fixed).
-- round_id NULL = end-of-match scoreboard.
CREATE TABLE IF NOT EXISTS scoreboard_stats (
    id         INTEGER PRIMARY KEY,
    match_id   INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    round_id   INTEGER REFERENCES rounds(id) ON DELETE CASCADE,
    player_id  INTEGER NOT NULL REFERENCES players(id),
    stat_name  TEXT NOT NULL,                    -- 'eliminations', 'damage_dealt', 'col_2', ...
    value      REAL,
    confidence REAL,
    UNIQUE (match_id, round_id, player_id, stat_name)
);

-- ---------- views used by the app and the Excel export ----------

CREATE VIEW IF NOT EXISTS v_events AS
SELECT e.id, e.match_id, m.recorded_at, r.round_no,
       e.true_time_s, e.feed_time_s, ROUND(e.feed_time_s - e.true_time_s, 2) AS feed_delay_s,
       e.time_source, e.event_type,
       pk.ign AS killer, pv.ign AS victim, e.weapon, e.victim_team,
       e.confidence, e.flag, e.reviewed, e.evidence_path
FROM events e
JOIN matches m       ON m.id = e.match_id
LEFT JOIN rounds r   ON r.id = e.round_id
LEFT JOIN players pk ON pk.id = e.killer_id
LEFT JOIN players pv ON pv.id = e.victim_id;

-- Per player per match. "eliminations" = kill + eliminated_knocked credited to the killer.
CREATE VIEW IF NOT EXISTS v_player_match AS
SELECT mp.match_id, m.recorded_at, p.id AS player_id, p.ign, p.nickname, mp.team,
  (SELECT COUNT(*) FROM events e WHERE e.match_id = mp.match_id AND e.killer_id = p.id
      AND e.event_type IN ('kill','eliminated_knocked'))                         AS eliminations,
  (SELECT COUNT(*) FROM events e WHERE e.match_id = mp.match_id AND e.killer_id = p.id
      AND e.event_type = 'knock')                                                 AS knocks,
  (SELECT COUNT(*) FROM events e WHERE e.match_id = mp.match_id AND e.victim_id = p.id
      AND e.event_type IN ('kill','eliminated_knocked'))                         AS deaths,
  (SELECT COUNT(*) FROM events e WHERE e.match_id = mp.match_id AND e.victim_id = p.id
      AND e.event_type = 'knock')                                                 AS times_knocked,
  (SELECT SUM(s.value) FROM scoreboard_stats s WHERE s.match_id = mp.match_id AND s.player_id = p.id
      AND s.stat_name = 'damage_dealt' AND s.round_id IS NOT NULL)               AS damage_dealt,
  (SELECT SUM(s.value) FROM scoreboard_stats s WHERE s.match_id = mp.match_id AND s.player_id = p.id
      AND s.stat_name = 'eliminations' AND s.round_id IS NOT NULL)               AS scoreboard_eliminations
FROM match_players mp
JOIN players p ON p.id = mp.player_id
JOIN matches m ON m.id = mp.match_id;

CREATE VIEW IF NOT EXISTS v_player_career AS
SELECT player_id, ign, nickname,
       COUNT(DISTINCT match_id) AS matches,
       SUM(eliminations) AS eliminations, SUM(knocks) AS knocks,
       SUM(deaths) AS deaths, SUM(times_knocked) AS times_knocked,
       SUM(damage_dealt) AS damage_dealt,
       ROUND(1.0 * SUM(eliminations) / MAX(SUM(deaths), 1), 2) AS elim_death_ratio
FROM v_player_match
GROUP BY player_id, ign, nickname;

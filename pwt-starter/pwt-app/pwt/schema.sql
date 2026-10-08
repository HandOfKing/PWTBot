-- PWT database schema (SQLite). One file, pwt.db, holds every processed match.
-- Bump PRAGMA user_version and add a migration in db.py when this changes.

PRAGMA foreign_keys = ON;

-- One row per processed recording (= one room / match).
CREATE TABLE IF NOT EXISTS matches (
    id               INTEGER PRIMARY KEY,
    recorded_at      TEXT NOT NULL,              -- local date-time 'YYYY-MM-DD HH:MM:SS' (OBS filename, else file time)
    processed_at     TEXT NOT NULL,
    source_file      TEXT NOT NULL,              -- 'live' for live capture, else the file name
    source_deleted   INTEGER NOT NULL DEFAULT 0, -- 1 once the app deleted the video
    duration_s       REAL,
    room_code        TEXT,                       -- WoW "Creation Code" shown on the HUD
    mode             TEXT,                       -- 'rounds' | 'classic' | ...
    team_size        INTEGER,                    -- 4 .. 8
    rounds_played    INTEGER,
    winner_team      TEXT,                       -- 'blue' | 'red' | 'draw'
    layout_profile   TEXT,                       -- calibration profile used
    pipeline_version TEXT,
    status           TEXT NOT NULL DEFAULT 'processed',  -- live | processed | needs_review | interrupted | failed
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

-- What happened after each knock, inferred from the feed (Chirag's rule: knocked again = revived).
-- Ordered by FEED time, because the feed is a first-in-first-out queue, while knocks only have feed time.
-- Scope = same round (round-based rooms) or whole match (classic, round_id NULL).
--   revived     : the knocked player shows up alive again first (knocked again, or knocks/kills someone)
--   eliminated  : their next appearance is their own elimination (could hide a revive followed by a no-knock kill -> revives are a lower bound)
--   unresolved  : nothing more about them that round (round ended with them knocked, or revived and survived)
-- A tombstone credit (eliminated_knocked) does NOT prove the killer was alive: it can land while they are knocked.
CREATE VIEW IF NOT EXISTS v_knock_outcomes AS
SELECT knock_id, match_id, round_id, victim_id, knocker_id, feed_time_s,
       CASE WHEN next_alive_feed IS NOT NULL AND (next_elim_feed IS NULL OR next_alive_feed < next_elim_feed) THEN 'revived'
            WHEN next_elim_feed IS NOT NULL THEN 'eliminated'
            ELSE 'unresolved' END AS outcome,
       CASE WHEN next_alive_feed IS NOT NULL AND (next_elim_feed IS NULL OR next_alive_feed < next_elim_feed)
            THEN next_alive_feed END AS revived_before_feed_s
FROM (
  SELECT k.id AS knock_id, k.match_id, k.round_id, k.victim_id, k.killer_id AS knocker_id, k.feed_time_s,
    (SELECT MIN(e.feed_time_s) FROM events e
      WHERE e.match_id = k.match_id AND IFNULL(e.round_id, -1) = IFNULL(k.round_id, -1)
        AND e.feed_time_s > k.feed_time_s AND e.victim_id = k.victim_id
        AND e.event_type IN ('kill','eliminated_knocked') AND IFNULL(e.flag, '') <> 'NO_DROP') AS next_elim_feed,
    (SELECT MIN(e.feed_time_s) FROM events e
      WHERE e.match_id = k.match_id AND IFNULL(e.round_id, -1) = IFNULL(k.round_id, -1)
        AND e.feed_time_s > k.feed_time_s AND e.id <> k.id
        AND ((e.victim_id = k.victim_id AND e.event_type = 'knock')
             OR (e.killer_id = k.victim_id AND e.event_type IN ('knock','kill'))))  AS next_alive_feed
  FROM events k WHERE k.event_type = 'knock'
);

-- Who the GAME credits with each elimination (Chirag's rule, confirmed against the
-- round-1 scoreboard: Khajwa 1 elim, Wolverine 1 elim).
--
-- The credit goes to whoever KNOCKED the victim, not whoever fired the finishing
-- shot. A knock creates a claim; a revive clears it; a later knock by someone else
-- replaces it, so the LATEST un-revived knocker is credited. Only an elimination
-- with no outstanding knock -- a kill from full health -- credits the shooter.
--
-- Worked example from Video_Project_9 round 1: KhajwaKILL3R knocks KG696969, then
-- TheWolverine finishes him. The feed row reads "TheWolverine [gun] KG696969", but
-- the elimination belongs to Khajwa. Counting the feed's killer_id credited the
-- wrong player on every assisted kill.
--
-- v_knock_outcomes already encodes the latest-knocker rule: being knocked again
-- marks the earlier knock 'revived', so the only knock left as 'eliminated' is the
-- most recent un-revived one. Ordering by feed_time_s DESC and taking the first is
-- belt and braces for a victim knocked more than once in a round.
--
-- An unattributed row (NO_FEED_ROW) has victim_id NULL, so the subquery matches
-- nothing and credited_id stays NULL: it is counted for no one, which is correct.
CREATE VIEW IF NOT EXISTS v_elim_credit AS
SELECT e.id AS event_id, e.match_id, e.round_id, e.victim_id,
       e.killer_id AS finisher_id,
       COALESCE(
         (SELECT o.knocker_id FROM v_knock_outcomes o
           WHERE o.match_id = e.match_id
             AND IFNULL(o.round_id, -1) = IFNULL(e.round_id, -1)
             AND o.victim_id = e.victim_id
             AND o.outcome = 'eliminated'
             AND o.feed_time_s < e.feed_time_s
           ORDER BY o.feed_time_s DESC LIMIT 1),
         e.killer_id)                                                            AS credited_id
FROM events e
WHERE e.event_type IN ('kill', 'eliminated_knocked')
  AND IFNULL(e.flag, '') <> 'NO_DROP';   -- a kill row the Remaining counter saw no death for: not counted

-- Per player per match. "eliminations" follows the game's crediting rule above;
-- "finishes" is what the feed literally showed, kept so the two can be compared.
CREATE VIEW IF NOT EXISTS v_player_match AS
SELECT mp.match_id, m.recorded_at, p.id AS player_id, p.ign, p.nickname, mp.team,
  (SELECT COUNT(*) FROM v_elim_credit c WHERE c.match_id = mp.match_id
      AND c.credited_id = p.id)                                                  AS eliminations,
  (SELECT COUNT(*) FROM v_elim_credit c WHERE c.match_id = mp.match_id
      AND c.finisher_id = p.id)                                                  AS finishes,
  (SELECT COUNT(*) FROM events e WHERE e.match_id = mp.match_id AND e.killer_id = p.id
      AND e.event_type = 'knock')                                                 AS knocks,
  (SELECT COUNT(*) FROM events e WHERE e.match_id = mp.match_id AND e.victim_id = p.id
      AND e.event_type IN ('kill','eliminated_knocked') AND IFNULL(e.flag, '') <> 'NO_DROP') AS deaths,
  (SELECT COUNT(*) FROM events e WHERE e.match_id = mp.match_id AND e.victim_id = p.id
      AND e.event_type = 'knock')                                                 AS times_knocked,
  (SELECT COUNT(*) FROM v_knock_outcomes o WHERE o.match_id = mp.match_id AND o.victim_id = p.id
      AND o.outcome = 'revived')                                                  AS revives_inferred,
  -- Scoreboard numbers: the end-of-match board (round_id NULL) when it was read -- it covers
  -- the whole match and every player -- else the sum of the round boards, which in 6v6 show
  -- only the rows on screen without scrolling (6 of 12).
  COALESCE((SELECT s.value FROM scoreboard_stats s WHERE s.match_id = mp.match_id AND s.player_id = p.id
      AND s.stat_name = 'damage_dealt' AND s.round_id IS NULL),
    (SELECT SUM(s.value) FROM scoreboard_stats s WHERE s.match_id = mp.match_id AND s.player_id = p.id
      AND s.stat_name = 'damage_dealt' AND s.round_id IS NOT NULL))              AS damage_dealt,
  COALESCE((SELECT s.value FROM scoreboard_stats s WHERE s.match_id = mp.match_id AND s.player_id = p.id
      AND s.stat_name = 'eliminations' AND s.round_id IS NULL),
    (SELECT SUM(s.value) FROM scoreboard_stats s WHERE s.match_id = mp.match_id AND s.player_id = p.id
      AND s.stat_name = 'eliminations' AND s.round_id IS NOT NULL))              AS scoreboard_eliminations,
  (SELECT s.value FROM scoreboard_stats s WHERE s.match_id = mp.match_id AND s.player_id = p.id
      AND s.stat_name = 'knock_outs' AND s.round_id IS NULL)                     AS scoreboard_knock_outs,
  EXISTS (SELECT 1 FROM scoreboard_stats s WHERE s.match_id = mp.match_id AND s.round_id IS NULL)
                                                                                 AS has_match_board
FROM match_players mp
JOIN players p ON p.id = mp.player_id
JOIN matches m ON m.id = mp.match_id;

CREATE VIEW IF NOT EXISTS v_player_career AS
SELECT player_id, ign, nickname,
       COUNT(DISTINCT match_id) AS matches,
       SUM(eliminations) AS eliminations, SUM(knocks) AS knocks,
       SUM(deaths) AS deaths, SUM(times_knocked) AS times_knocked, SUM(revives_inferred) AS revives_inferred,
       SUM(damage_dealt) AS damage_dealt,
       ROUND(1.0 * SUM(eliminations) / MAX(SUM(deaths), 1), 2) AS elim_death_ratio
FROM v_player_match
GROUP BY player_id, ign, nickname;

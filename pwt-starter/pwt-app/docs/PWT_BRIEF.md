# PWT: build brief for Claude Code

This file is the whole specification. It assumes an **empty repo**.

Everything under "Known facts" and "Algorithms" was measured on a real test recording and checked in a prototype (Oct 2026). Treat the numbers as starting values to calibrate, not guesses.

---

## 1. Goal

Chirag and his friends play PUBG Mobile **World of Wonder (WoW) custom rooms**:
- always squads, 4v4 up to 8v8
- usually round-based ("ROUND 01/29")

A dedicated **spectator account** sits in the room on Chirag's Windows laptop, running **GameLoop** (Tencent's official emulator). Everyone else plays on phones.

PWT runs on that laptop during the match and produces, for every match:
- **Events:** every knock, kill and death, with timestamps, killer, victim, weapon and type.
- **Rounds:** start, end, winner, score.
- **Round scoreboards:** each player's numbers for every round.
- **Match scoreboard:** each player's totals for the whole match.
- **Derived per-player stats:**
  - eliminations, knocks, deaths, times knocked
  - inferred revives
  - time alive per round, first bloods, weapon use

Everything is saved in SQLite, browsable by date and time, and exportable to Excel. A per-player "Impact" score will come later; Chirag is still defining it. Collect the data first.

**Target laptop:** Acer Nitro, i7-11800H (8 cores / 16 threads), RTX 3050 Ti, 16 GB RAM, Windows. GameLoop runs PUBG smoothly there. Chirag enlarged the kill feed in the in-game HUD settings. Run GameLoop fullscreen.

---

## 2. How it works (decisions already made)

- **Live capture, no recording.** PWT captures the screen itself with **DXcam** (Desktop Duplication API) at **12 fps** and analyses frames in real time. No OBS, no video files.
- **Replay mode** feeds a video file through the same engine. It's for development and tests only, using Chirag's test clip and his full 2 GB match.
- **Scoreboards need scrolling in 8v8.** About 8–9 rows fit and there are 16 players. The round scoreboard is visible only about 3 s.
  - **Prompt mode (default):** PWT detects the board, plays a chime and shows an overlay "SCROLL DOWN, n/16 captured", which turns green when complete. A person scrolls.
  - **Auto-scroll (opt-in):** PWT drags the list itself, only on scoreboards, with a kill switch and a warning, because PUBG Mobile does not allow macros.
- The **kill feed + Remaining counter + helmets** are the main data source. Scoreboards add per-round and match numbers, plus a cross-check of elimination counts.
- **No game modding, no memory reading, no network.** Only screen pixels, plus the optional scroll.

---

## 3. Known facts about the HUD (from the test clip)

Test clip: `Video_Project_7.mp4`, 21.47 s, 1920×1080 at 30 fps, recorded **windowed**. The game area is about x 100–1828, y 53–1025, so the HUD is scaled to about 90%. It's a 2v2 round-based room. All coordinates below are for this layout; fullscreen with the bigger feed must be recalibrated.

### 3.1 Kill feed (left side)
- **Box:** about x 100–760, y 215–480.
- **Row layout:**
  - Rows are left-aligned; the text starts at x ≈ 118.
  - The **newest row enters the bottom slot** (y ≈ 455), and older rows shift up about 46 px.
  - Each row is a translucent dark bar with white text and icons about 12 px tall.
  - A row slides in over about 2 frames and stays about **3.5 s**.
- **Row grammar** (left to right):

| Row layout | Meaning |
|---|---|
| killer · weapon icon · knock icon (crawling figure with stars) · victim | **knock** |
| killer · weapon icon · victim | **kill**; the last survivor of a team dies outright, with no knock |
| killer · tombstone icon · victim | **eliminated_knocked**: a knocked player died because their team was wiped. Credited to the killer; counts as an elimination. |

- Still unknown: headshot, grenade, vehicle, zone, fall, drowning, teamkill, revive lines, and a "finish" on a knocked player while teammates are alive. **Build an icon library that grows.**
- Weapon icons seen so far: UMP45.
- **Names use stylised characters** (TheWølverine, RGODxEMPERØR). Raw OCR is rough ("TheWalverine", "REDOxEMPEROR", "Makpets6d"). Always fuzzy-match to the roster.
- **The feed is paced.** New rows were posted about 2 s apart even when events happened together, so **the feed lags the real event**, by 3.5 s in the clip. Feed order can also differ from causal order inside a burst.

### 3.2 Counters and banner (true times)
- **Remaining** (top-left, digit box about x 184–210, y 60–88): players alive in the whole lobby.
  - Drops **at the true elimination time.** Knocks don't change it.
  - In the clip: 4 → 3 at 13.25 s, 3 → 2 at 13.29 s. The feed lines came at 14.58 s and 16.75 s.
- **Team Eliminations / per-player elims** panel (top-left, about x 100–330, y 55–205):
  - updates about 0.8 s after Remaining
  - shows only the spectated player's team
- **Round banner** (top centre: blue score · helmets · ROUND nn/29 + 2:00 countdown · helmets · red score):
  - Visible only while a round is live.
  - Hidden during the pre-round countdown, and from about 0.25 s after the round is won (the compass replaces it).
- **Banner helmets:** one per player. **White = alive, gray = dead. Knocked stays white.**
  - They tell **which team** lost a player, about 0.2 s after Remaining.
  - 2v2 positions: blue (666,76), (710,76); red (1218,76), (1262,76). They will differ for other team sizes.
- **Banner score:** blue digit box about x 772–808, red about x 1118–1156, y 66–116. It ticks up on the same frame the helmets turn gray (13.46 s).
- **Banner visible test:** the score boxes are solid colours.
  - Blue points (770,75), (805,110), (760,100): B − R > 80
  - Red points (1120,75), (1150,110), (1160,100): R − B > 70
- **Zone timer** under the minimap: always visible; not needed.
- **Other HUD text:**
  - Room **Creation Code** printed at the top (e.g. 26884524). Read it once per match.
  - Bottom-left watermark with the game's UTC timestamp.

### 3.3 Round end and scoreboards
- **Round end:**
  - The screen **dims to about 20% brightness for about 3 s** (median gray of the game area < 45).
  - Feed rows keep arriving during the dim, so keep reading the feed.
- **Round scoreboard:**
  - Full screen: result banner ("DRAW" / victory…), "Round 1/29", then a table.
  - Columns: Rank · Team · Wins · Player · 4 columns all labelled "No. of Eliminations" (meaning unknown) · Damage Dealt.
  - Visible **2.8 s** in the clip ("Next Round (n s)" button).
  - Row pitch about 82 px. About 8–9 rows fit, so **8v8 needs scrolling**.
  - In the clip, Damage Dealt showed for every player. Chirag believes the match scoreboard may show damage only for the spectated player; verify on a real match.
- **Match scoreboard (end):** totals for the whole match. The layout is not seen yet. It probably has no countdown, but confirm.
- **Table geometry (clip):**
  - Player column x 560–1090.
  - Value columns x (1100–1220), (1232–1352), (1364–1484), (1496–1616); damage x 1628–1750.
  - Table y 250–1010.
  - Header text "Rank Team Wins Player" at about y 195–232, x 180–900. Use it as the scoreboard-detection template.
- **The HUD font is condensed. Tesseract misreads its digits**: "52" → "2" from a clean binarised image, and lone "0"s are dropped. **Use digit templates.** OCR on names works well enough when it's fuzzy-matched to the roster.

### 3.4 Video quality notes (for replay files only)
At 6 Mbps, results were identical to 15 Mbps. At 3 Mbps, some names fell below the confidence bar. At 1.5 Mbps it was too low.

---

## 4. Architecture

```
pwt/
  capture/sources.py     FrameSource interface; LiveScreenSource (dxcam, mss fallback); FileReplaySource (OpenCV)
  engine/engine.py       threads, queue, state machine, alignment
  engine/state.py        IDLE / ROUND_LIVE / ROUND_END / ROUND_SCOREBOARD / MATCH_SCOREBOARD / FINISHED
  readers/mask.py        white top-hat mask
  readers/feed.py        kill-feed rows -> events, line tracking
  readers/counters.py    Remaining (digits), helmets, banner visible, banner score
  readers/screens.py     screen_state, scoreboard detection, row reading, stitcher, table_changed
  readers/digits.py      digit templates (+ harvest)
  readers/names.py       OCR + roster matching (later: name templates)
  profiles/              layout-profile JSON (+ calibration tool, Phase 2)
  assist/scroll.py       Prompt overlay + chime; Auto-scroll (SendInput) behind a setting (Phase 3)
  db.py, schema.sql      SQLite: LiveMatch (live writes), save_match (batch), queries
  export_excel.py        openpyxl export
  cli.py                 python -m pwt live | replay <file> | list | show | players | rename | export | where
app/main.py              PySide6 UI (Phase 4)
tools/capture_bench.py   Phase 1 laptop test
tests/                   pytest; fixtures = frames cut from the test clip
```

### 4.1 Frame sources (`frames() -> iterator of (t_seconds, BGR ndarray)`)
- **LiveScreenSource:**
  - `dxcam.create(output_color="BGR")`, then `start(target_fps=12, video_mode=True, region=<game area from profile>)`.
  - `t` = `time.perf_counter()` since match start.
  - Fall back to `mss` if dxcam fails.
  - On start, check the first frames aren't black. Black frames come from hybrid-GPU laptops or a privilege mismatch: tell the user to run as administrator (GameLoop runs elevated) or set Python to the same GPU as GameLoop (Windows Settings → Display → Graphics).
- **FileReplaySource:**
  - OpenCV `VideoCapture`, resampled to 12 fps, `t` = sample index / 12.
  - Runs as fast as possible by default; `--realtime` for live-like tests.

### 4.2 Threads
- **Capture thread:** pushes into a bounded queue (max 24 frames). Drop the oldest and count drops.
- **Analyser thread:** runs the per-frame work (§4.3). It must stay under the 83 ms frame budget, so it never runs OCR itself.
- **Name worker pool:** reads names for **new** feed lines only.
- **Scoreboard worker:** receives only **new scroll positions** (`table_changed`) and reads rows.
- **Writer:** `LiveMatch` commits each confirmed item.

**Measured** on a weak 2-core cloud VM, replaying the clip at 12 fps: analysis averaged 16 ms per frame (p95 28 ms), about 11% CPU. Reading a scoreboard (3 positions × 4 rows) took 1.8 s, which is why it's a worker. The i7 laptop will be faster; GameLoop is the heavy load.

### 4.3 Per frame
1. `screen_state(frame)`: `scoreboard` (header template), `dimmed` (median gray < 45), `live` (banner visible), or `other`.
2. **live:**
   - **Remaining:** read with digit templates only when the box's pixels changed.
   - **Helmets** and **banner score.**
   - **Feed:** mask + row scan every frame (cheap). Icon matching only for rows not seen before.
   - **Track lines:** a line keeps its identity while it moves up the stack. Key = icon signature + rough text width + row position history. Read its names once.
3. **dimmed:** keep the feed running; close the round.
4. **scoreboard:** hand new scroll positions to the scoreboard worker, and drive the scroll assist.

### 4.4 State machine and alignment
- **Round number:** read from the banner "ROUND nn/29", else counted.
- **Match start:** `ROUND 01`, or the first live frame after IDLE.
- **Match end:** the match scoreboard (calibrate its look from a real one), or the round count reached, or more than N minutes in `other`.
- **Players in room** = Remaining at the start of round 1. That's also the number of scoreboard rows to expect.
- **Remaining changes:**
  - Accept a new value after 2 consecutive equal reads. Stamp it with the **first frame that left the old value**, so a one-frame 3 inside 4 → 3 → 2 is absorbed.
  - A drop of k means k eliminations at that time.
- **Helmets:**
  - A slot is dead after 2 consecutive gray reads.
  - If the banner vanishes right after a single gray read (a round-ending death), accept it.
  - Each Remaining drop takes its team from the next unused helmet death within 1.0 s.
- **Alignment:** each confirmed feed elimination (kill / eliminated_knocked), in feed order, takes the **earliest unused Remaining drop at or before its feed time whose team matches the victim's team**. Then call `update_event_time(..., time_source="Remaining drop + helmet")`.
- **Knocks:** keep the feed time, `time_source="feed (approx)"`. Planned: a min/max window from feed order, since the feed is first-in, first-out.

### 4.5 Scoreboards and scroll assist
- On `scoreboard` state, start a `ScoreboardStitcher(expected=players_in_room)`.
- For every new scroll position:
  - Read the rows: name by OCR + roster match; each value cell by digit templates.
  - Merge by player name, **majority-voting each cell** across sightings.
- When the board closes, save it: `add_stats(rows, round_no=n)` for a round board, `round_no=None` for the match board. Flag missing rows or cells.
- **Prompt mode (default):**
  - When the board shows fewer rows than `expected`: chime plus an always-on-top overlay "SCROLL DOWN, 9/16 captured".
  - It turns green at "All 16 captured ✓".
  - A person scrolls.
- **Auto-scroll (setting, OFF by default):**
  - `SendInput` drag inside the list: press near the bottom, move up about one screen over about 150 ms, release, wait about 250 ms.
  - Repeat until every row is captured or the board closes, then restore the mouse.
  - Drag points and timing come from the profile.
  - **Only** in `scoreboard` state. F8 kill switch. Log every action.
  - Settings warning: *"PUBG Mobile does not allow macros. Use only on the dedicated spectator account; the risk is a ban of that account."*
  - Must run at the same privilege level as GameLoop.
  - The round board is up only about 3 s, so start within about 0.5 s.

### 4.6 Evidence (replaces video)
- One PNG per feed line (a crop of the row).
- One JPEG per scoreboard scroll position.
- Store paths relative to the data folder. That's about 10–20 MB per match.
- The review screen shows them so a person can fix flagged rows.

---

## 5. Algorithms (tested values)

### 5.1 White text mask: survives the round-end dim
```python
mn = crop.min(axis=2); mx = crop.max(axis=2)
th = cv2.morphologyEx(mn, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (23, 23)))
t = max(18, 0.45 * np.percentile(th, 99.8))
mask = (th > t) & ((mx - mn) < 45)          # bright, near-neutral, brighter than local background
```
During the dim, text is about 49 against a background of about 7–20. A fixed threshold fails; this relative one works.

### 5.2 Feed rows
- **Projection:** horizontal projection of the mask over crop columns 14–440 (skips the window edge). A row starts where the count is ≥ 3, continues while ≥ 2, and is kept if 9–26 px tall.
- **Left-alignment filter:** the first text column must sit at absolute x 105–140. That rejects in-world name tags.
- **Icons:** slide each icon template (top-hat masks padded by 3 px) along the row band (y0−6 … y1+6) with `TM_CCOEFF_NORMED`. Keep peaks ≥ 0.62, suppress overlaps, sort by x. **No icon = not a feed row.**
- **Killer and victim:**
  - Killer = text columns from crop x 12 up to the first icon's left edge.
  - Victim = text starting after the last icon's right edge, extended while gaps are ≤ 14 px. That stops at background clutter.
  - Both must be at least 12 px wide.
- **Names:** mask ×255, upscale 4× (cubic), invert, 20 px white border, then `tesseract --psm 7`.
  - Normalise (ø→o, 0→o, strip spaces) and fuzzy-match to the roster (`difflib` ratio).
  - Drop the row if either score is < 0.5. Flag `LOW_CONF` if < 0.75.
- **Type:** knock icon → knock; tombstone → eliminated_knocked; else kill. Weapon = the matched `weapon_*` icon, decided by majority vote across sightings.
- **Dedupe (replay/batch):**
  - key = (killer, type, victim); per-frame count increases = new events.
  - A sighting continues if the key was seen within 1.0 s.
  - Keep events seen for ≥ 0.5 s (≥ 6 frames at 12 fps). That drops slide-in and shift glitches.
- **Icon templates in the clip:** frame at 14.83 s. UMP45 x 214–248, y 400–418; knock x 271–299, y 400–418; tombstone x 225–241, y 444–462 (absolute coordinates). Re-cut them in fullscreen.

### 5.3 Helmets
- State = 90th percentile of the min-channel in a 26×22 box at the helmet centre: > 190 = alive, > 80 = dead (gray), else not visible.
- Read only while the banner-visible test passes.

### 5.4 Digits (Remaining, banner score, scoreboard cells)
- **Glyphs:** Otsu-binarise the cell (white glyphs), take connected components that are ≥ 10 px tall, ≥ 15 px area and not wider than 1.2 × height, left to right.
- **Match:** normalise each glyph to 16×24 and compare against templates by zero-mean correlation. Accept if ≥ 0.80, else return None and flag.
- **`harvest(cell, known_text)`** saves the glyphs of a confirmed value as new templates, so the library grows from review fixes.
- **Proven:** with 0/1/2/5 templates cut from one frame, it read 52 (score 0.99) and 200 on a different frame. Tesseract read "2".

### 5.5 Scoreboard
- **Detect:** `matchTemplate` (grayscale, `TM_CCOEFF_NORMED`) of the header crop within y 120–330. Score ≥ 0.70 means it's on screen. It was 0.999 on the board and ≤ 0.61 elsewhere in the clip.
- **Rows:** horizontal projection of (gray > 170) in the Player column; bands 12–40 px tall; one centre y per row.
- **New scroll position:** mean absolute difference of the table area (grayscale, ¼ scale) > 6 against the last kept frame.
- **Stitch:** one entry per player name. Each cell takes the majority value across sightings, with an agreement share kept for QA.

### 5.6 Revive inference (Chirag's rule)
A player knocked who then shows up alive again in the same round (knocked again, or knocking or killing someone) was revived.

- Order by **feed time**, because knocks only have feed time and the feed is first-in, first-out.
- A tombstone credit doesn't prove they were alive: it can land while they're knocked.
- Each knock's outcome is revived, eliminated, or unresolved.
- Revives are a **lower bound**, and the reviver is unknown.
- Implemented as the SQL view `v_knock_outcomes` (§6).

---

## 6. Database (use this schema)

```sql
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
        AND e.event_type IN ('kill','eliminated_knocked'))                       AS next_elim_feed,
    (SELECT MIN(e.feed_time_s) FROM events e
      WHERE e.match_id = k.match_id AND IFNULL(e.round_id, -1) = IFNULL(k.round_id, -1)
        AND e.feed_time_s > k.feed_time_s AND e.id <> k.id
        AND ((e.victim_id = k.victim_id AND e.event_type = 'knock')
             OR (e.killer_id = k.victim_id AND e.event_type IN ('knock','kill'))))  AS next_alive_feed
  FROM events k WHERE k.event_type = 'knock'
);

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
  (SELECT COUNT(*) FROM v_knock_outcomes o WHERE o.match_id = mp.match_id AND o.victim_id = p.id
      AND o.outcome = 'revived')                                                  AS revives_inferred,
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
       SUM(deaths) AS deaths, SUM(times_knocked) AS times_knocked, SUM(revives_inferred) AS revives_inferred,
       SUM(damage_dealt) AS damage_dealt,
       ROUND(1.0 * SUM(eliminations) / MAX(SUM(deaths), 1), 2) AS elim_death_ratio
FROM v_player_match
GROUP BY player_id, ign, nickname;
```

**DB API (`pwt/db.py`):**
- `data_dir()`:
  - `%LOCALAPPDATA%\PWT` by default
  - `./data` if `portable.txt` sits next to the exe
  - override with `PWT_DATA_DIR`
- `connect(path=None)` creates the schema and sets `user_version`.
- `get_or_create_player(conn, ign)` tries, in order: exact name → alias → normalised match (stored as an alias) → create.
- `LiveMatch(conn, recorded_at=None, source_file="live", **match_cols)`:
  - Methods: `set_player(ign, team, slot=None)`, `start_round(n, start_s)`, `end_round(n, end_s, winner_team, result_text, blue_score, red_score)`, `add_event(dict) -> id`, `update_event_time(id, t, source)`, `add_stats(list, round_no|None)`, `finish(**cols)`.
  - **Every call commits.**
  - `finish()` sets `processed`, or `needs_review` if any row is flagged.
- `recover_interrupted(conn)`: at app start, `live` → `interrupted`, data kept.
- `save_match(conn, match, players, rounds, events, stats)`: batch insert in one transaction. Idempotent on (source_file, recorded_at).
- Queries for the UI:
  - `list_matches(conn, date_from, date_to, player)`
  - `match_detail(conn, id)` → match / players / events / rounds / stats
  - `correct_event(conn, id, **fields)` → sets `reviewed=1`

---

## 7. Layout profile (JSON in `<data>/profiles/<name>.json`)
Example: the windowed test-clip profile. Make a new one for fullscreen with the bigger feed.
```json
{
  "name": "gameloop-windowed-1080p",
  "capture_region": [0, 0, 1920, 1080],
  "feed": {"box": [100, 215, 760, 480], "row_left_x": [105, 140], "icon_thresh": 0.62},
  "remaining_box": [184, 60, 210, 88],
  "banner": {"blue_pts": [[770,75],[805,110],[760,100]], "red_pts": [[1120,75],[1150,110],[1160,100]],
             "blue_score_box": [772,66,808,116], "red_score_box": [1118,66,1156,116],
             "helmets": {"2": {"blue": [[666,76],[710,76]], "red": [[1218,76],[1262,76]]}}},
  "dim_median_below": 45,
  "scoreboard": {"header_template": "scoreboard_header.png", "header_band": [100,120,1830,330], "header_thresh": 0.70,
                 "player_col": [560,1090], "table_y": [250,1010],
                 "value_cols": {"col_1":[1100,1220],"col_2":[1232,1352],"col_3":[1364,1484],"col_4":[1496,1616],"damage_dealt":[1628,1750]},
                 "scroll_drag": {"from": [1200, 950], "to": [1200, 350], "move_ms": 150, "settle_ms": 250}},
  "templates_dir": "templates/"
}
```
- `scroll_drag` values are placeholders. Set them from a real 8v8 scoreboard.
- **Calibration tool:** load a frame (live grab, or a PNG from `bench_out/`), drag a box for each element, then save.
- Helmet positions are needed for each team size (4v4 … 8v8).

---

## 8. Excel export (`openpyxl`)
- **One match:**
  - **Summary:** match info, plus a player table (eliminations, knocks, deaths, times knocked, revives "inferred, at least", scoreboard eliminations, check "OK / feed n vs board m").
  - **Events:** date & time, round, true time (s and mm:ss), feed time, feed delay, time source, type, killer, weapon, victim, victim team, confidence, flag, reviewed.
  - **Rounds**
  - **Round-by-round players:** pivoted from the round scoreboards.
  - **Match scoreboard**
- **Date range:** Matches, Player totals, Player per match, All events.
- **Formatting:** bold dark header row, frozen panes, auto-filter, sensible widths, flagged rows yellow.

## 9. UI (PySide6, Phase 4)
1. **Live:**
   - Start/Stop
   - capture health (fps achieved, drops, CPU)
   - state and round
   - rolling event list
   - scoreboard progress + overlay
2. **Matches:** newest first; filter by date range and player; Open, Export selected, Export range, Delete.
3. **Match detail**, with tabs:
   - Players
   - Events (flagged rows yellow; click to see the evidence image and fix)
   - Rounds
   - Scoreboards (per round + match)
   - Export
4. **Players:** nicknames, aliases, merge two players, career totals.
5. **Settings:**
   - profile + calibration
   - scroll-assist mode (with the warning) and kill-switch key
   - data folder, export folder
   - a developer "Replay a file" entry

## 10. Packaging
- PyInstaller **one-folder**, then zip it: `PWT-<version>-windows.zip`, built by GitHub Actions on a `windows-latest` runner when a `v*` tag is pushed, and attached to a Release.
- Include in the bundle:
  - `schema.sql` and `templates/`
  - Tesseract, until names move to templates (e.g. `choco install tesseract` on the runner, copied into `dist/PWT/vendor/tesseract`)
- Request admin rights if GameLoop runs elevated.
- Unsigned, so SmartScreen warns once; that's fine for the group.
- `requirements.txt`: numpy, opencv-python, openpyxl, dxcam (Windows), mss, psutil, PySide6, pytest. Plus Tesseract (UB Mannheim build) installed on the dev PC.

---

## 11. Test clip ground truth (`clips/Video_Project_7.mp4`)
Roster:

| Team | Player (ASCII) | On screen |
|---|---|---|
| blue | TheWolverine | TheWølverine |
| blue | PARAbloodthirs | |
| red | RGODxEMPEROR | RGODxEMPERØR |
| red | Makjets69 | |

The spectated player is TheWolverine. Room code 26884524. "ROUND 01/29".

| Time (s) | What happens |
|---|---|
| 0–2 | Pre-round countdown; banner hidden |
| ~2.2 | Banner visible (round live) |
| 12.50 | Feed: TheWolverine [UMP45] **knock** → RGODxEMPEROR |
| 13.25 / 13.29 | Remaining 4 → 3 → 2: **true time** of both eliminations |
| 13.46 | Both red helmets gray; blue score 0 → 1 |
| 13.71 | Banner hides |
| 14.08 | Team Eliminations 0 → 2 |
| 14.58–14.75 | Feed: TheWolverine [tombstone] → RGODxEMPEROR (**eliminated_knocked**) |
| ~15.0–17.9 | Screen dimmed |
| 16.75 | Feed: TheWolverine [UMP45] **kill** → Makjets69 |
| 18.25–21.08 | Round 1 scoreboard, "DRAW", Round 1/29 |

Round 1 scoreboard values:

| Player | 4 elimination columns | Damage Dealt |
|---|---|---|
| TheWolverine | 2, 2, 2, 2 | 200 |
| PARAbloodthirs | 0, 0, 0, 0 | 0 |
| RGODxEMPEROR | 0, 0, 0, 0 | 52 |
| Makjets69 | 0, 0, 0, 0 | 0 |

**Replay must produce:**
- 3 events:
  - knock at 12.5 s, feed (approx)
  - eliminated_knocked RGOD, true 13.25, feed about 14.7
  - kill Makjets69, true 13.25, feed 16.75
- 1 round, won by blue.
- Round scoreboard rows matching the table above.
- TheWolverine: feed eliminations 2 = board 2; knocks 1.
- Times within ±0.1 s at 12 fps.

Cut 4 frames as test fixtures: live with the knock row (12.9 s), dimmed (17.0 s), scoreboard (20.5 s and 21.0 s).

---

## 12. Phases (finish and show results before moving on)

| Phase | Build | Done when |
|---|---|---|
| **0 Foundation ✅ (branch `phase0-live-engine`)** | Repo scaffold, `schema.sql` + `db.py` (LiveMatch, save_match, queries), `export_excel.py`, CLI, readers ported from §5 working on numpy arrays, FileReplaySource, `python -m pwt replay`. pytest with the clip fixtures. | `pytest` green; replaying the test clip reproduces §11; Excel export opens with correct numbers |
| **1 Laptop capture test** | `tools/capture_bench.py`: dxcam at 12 fps for 3 min while Chirag spectates; runs the per-frame workload; reports achieved fps, late frames, analysis ms (mean/p95), CPU%, RAM, black frames; saves a full frame every 10 s and the first frame of each scoreboard (for calibration); times how long each scoreboard stays up. | ≥ 11.4 fps, < 1% late frames, analysis p95 < 42 ms, no black frames, no visible game stutter. Chirag also checks by hand whether the **mouse wheel** or only **drag** scrolls a scoreboard. |
| **2 Engine on replay** | Profile JSON + calibration tool (fullscreen, bigger feed); engine threads; state machine; Remaining by digits; line tracking; alignment; scoreboard worker + stitcher (round + match); evidence; LiveMatch writes. Run on Chirag's full 2 GB match in `clips/`. | Every round detected; at least 95% of feed eliminations reconcile with the round scoreboards; match scoreboard captured; faster than real time. Report all flagged rows with evidence paths. |
| **3 Live** | `python -m pwt live` with LiveScreenSource; Prompt scroll assist; then Auto-scroll behind the setting (rules in §4.5). | A full real match lands in the DB with every round board and the match board |
| **4 UI** | PySide6 screens (§9) with the engine in its own thread | A non-developer can run a live match, review, fix and export |
| **5 Release** | `app/main.py`, PyInstaller, GitHub Actions zip, admin manifest if needed | A clean Windows account: unzip, run, replay the test clip |
| 6 (optional) | Shared results: Google Sheet sync or a shared DB file | Friends see stats without the app |

## 13. Open questions (answer them in Phases 1–2 and update this file)
- How long are the round and match scoreboards up in 8v8? Does the mouse wheel scroll them, or only a drag?
- Match scoreboard: its title and columns. Damage for every player, or only the spectated one?
- What do the four columns labelled "No. of Eliminations" mean?
- Does each helmet slot map to a fixed player? Is blue always team 1?
- Does the feed show revive lines? Which icons exist for headshot, grenade, vehicle, zone, fall, teamkill?
- Does GameLoop run elevated? Do capture or input then need admin?

---

## 14. Prompts to paste into Claude Code (one per phase)

Phase 0 is already built. Start at Phase 1.

**Phase 0**
```
Read CLAUDE.md and docs/PWT_BRIEF.md completely. Build Phase 0 (§12) in this empty repo.
The test clip is at clips\Video_Project_7.mp4. Use §5 for the reader algorithms and §6 for the schema.
Cut the icon, header and digit templates from the clip at the coordinates given, and the 4 test fixtures.
Finish with: pytest output, `python -m pwt replay clips\Video_Project_7.mp4` matching §11, and an Excel export.
Show me the results before going further.
```

**Phase 1**
```
Phase 1 (§12). Write tools/capture_bench.py and help me run it as administrator while I spectate a room in GameLoop.
Then read bench_out/report.txt with me and say GO or NOT YET against the criteria.
```

**Phase 2**
```
Phase 2 (§12). My full match is at clips\<file>. First build the profile + calibration tool and calibrate the
fullscreen layout from the frames in bench_out/. Then build the engine (§4) and run replay on the full match.
Report rounds found, events per round, reconciliation vs the round scoreboards, and every flagged row.
Update §3 and §13 of docs/PWT_BRIEF.md with anything new you learn.
```

**Phase 3, 4, 5:** "Do Phase N of docs/PWT_BRIEF.md §12; follow its rules; show me the done-when results."


---

## 15. Phase 0 results and findings (2026-10-02)

**Replay of the test clip** (`python -m pwt replay clips/Video_Project_7.mp4`) matches §11:

| Check | Result |
|---|---|
| Round 1 | 2.17 s → 13.50 s, won by blue (1–0) |
| Knock | true = feed 12.58 s |
| Tombstone row | true 13.25 s (Remaining drop + helmet), feed 14.67 s |
| Kill row | true 13.25 s, feed 16.75 s |
| Round scoreboard | 4/4 rows; every value and team correct |
| Reconciliation | feed eliminations = board eliminations for all players |
| Evidence | one PNG per event, one JPEG per scoreboard read |

- This holds both with `--roster` and with an empty database, where names are learned from the scoreboard. `tests/test_replay_clip.py` checks both.

**Speed** (2-core cloud VM, `tools/capture_bench.py --replay` at real-time speed):
- 12.0 fps, 0 frames dropped
- engine 27 ms per frame mean, p95 49 ms
- about 22% CPU, 158 MB RAM

The p95 misses the < 42 ms bar only because the OCR threads share the 2 cores. Confirm on the 8-core laptop in Phase 1.

**Findings to carry forward:**
- **Tesseract is unreliable on these names.** The best scale changes frame to frame (single variants read 5–15 of 20 scoreboard names correctly).
  - Scoreboard names are therefore read 3 ways (Otsu ×4, Otsu ×5, grey ×4) and voted across variants and frames. That gave 20/20.
  - 12-px feed names are worse; treat them only as input to roster matching.
  - **Names come from the roster:** the DB players plus aliases plus `--roster`. The first time, they come from the scoreboard, and the match is noted "new player names, check spelling".
  - `python -m pwt rename OLD NEW` fixes a name once; the old spelling becomes an alias forever.
  - Future: character templates harvested from confirmed names.
- **The scoreboard fades in.** Skip the first 0.4 s (`settle_s`), then re-read every 0.5 s (`reread_s`) and on every scroll change, and vote per cell.
- **Room "Creation Code" can't be OCR'd:** it's translucent over the scene. `room_code` stays empty; enter it manually or template it later.
- **Digit templates read everything** (Remaining 4/3/2, banner 0/1, board cells, Team column) with no OCR. A single frame may leave a cell empty when its score is under 0.80, but never wrong; voting fills it.
- **Names before the first scoreboard:** feed names that aren't on the roster are saved with `flag='NAME?'` and resolved when the round board is read (score ≥ 0.6). Anything left unresolved at match end keeps the flag.
- **Team colours:** team 1 = blue, team 2 = red (`scoreboard.team_colors` in the profile). Verify in an 8v8 match.
- **A board followed by another board with no round in between is treated as the match scoreboard** (`round_no = NULL`). Calibrate the real match board's look in Phase 2.
- **The engine thread never waits on OCR:** feed names run on a 2-thread pool, and the scoreboard on its own worker, saved once idle.

# PWT app: specification

PWT turns OBS recordings of PUBG Mobile World of Wonder (WoW) custom rooms into match stats.

- Every processed match is saved by date and time.
- Matches can be browsed in the app.
- Data exports to Excel.
- The app runs on any Windows laptop from a zip downloaded from GitHub. No install, no internet.

## 1. Users and setup
- **Recording:** a spectator account in the WoW room on a Windows PC runs GameLoop, and OBS records the screen. Players are on phones. Rooms are always squads, 4v4 up to 8v8, and can be round-based (e.g. "ROUND 01/29").
- **Who uses the app:** whoever recorded, or anyone in the group they send recordings or the database to.

## 2. Distribution
- A GitHub Release holds `PWT-<version>-windows.zip`, a portable folder with `PWT.exe` and its libraries. Unzip, then double-click `PWT.exe`.
- Built with PyInstaller in **one-folder mode**. That starts faster and triggers fewer antivirus false positives than one-file mode.
- GitHub Actions (`.github/workflows/build-windows.yml`) builds it on a Windows runner whenever a tag `v*` is pushed.
- The app is unsigned, so Windows SmartScreen shows "Windows protected your PC" the first time; click More info, then Run anyway. A code-signing certificate removes this if we ever share widely.
- **Minimum PC:**
  - Windows 10/11, 64-bit
  - 4 cores, 8 GB RAM
  - about 0.5 GB for the app, plus room for the recording being processed
  - no GPU needed
- The app must work fully offline. No telemetry, no network calls.

## 3. Where the data goes
- One SQLite file, `pwt.db`, plus an `evidence/` folder of small PNGs (one image per kill-feed line, a few KB each).
- Default location is `%LOCALAPPDATA%\PWT\`.
  - Portable mode: if `portable.txt` sits next to `PWT.exe`, data goes in `.\data\`.
  - Override with the `PWT_DATA_DIR` environment variable.
- Tables (full DDL in `pwt/schema.sql`):

| Table | One row per |
|---|---|
| `matches` | Processed recording: date/time, room code, mode, team size, rounds, winner, status |
| `players` / `player_aliases` | Person (exact in-game name + nickname) / alternate spelling |
| `match_players` | Player in a match, with team (blue/red) and helmet slot |
| `rounds` | Round: start/end time, winner, banner score |
| `events` | Kill-feed event: true time, feed time, time source, type, killer, victim, weapon, confidence, flag, reviewed, evidence image |
| `scoreboard_stats` | Scoreboard number, stored long-form (stat_name, value), because column meanings vary by room |

- Views:
  - `v_events`: events with names joined in
  - `v_player_match`: eliminations, knocks, deaths, times knocked and damage per player per match
  - `v_player_career`: the same totals across all matches
- Re-importing the same recording is a no-op (unique on source_file + recorded_at).
- Videos are **not** kept by default (see 5).
- Backup = copy `pwt.db` plus `evidence/`.

## 4. Processing pipeline
Input is a recording (MKV or MP4, 1080p, any fps). Output is one saved match.

1. **Wait for OBS to finish.** The file size must be stable for 10 s and the file not locked.
2. **Decode** with OpenCV `VideoCapture`, sampling at **4 fps**. Timestamp = frame index / 4. That is the master clock.
3. **Kill feed** (`pipeline/killfeed.py`):
   - top-hat white mask
   - row detection
   - sliding icon templates (weapon / knock / tombstone)
   - killer = text left of the icons, victim = text right of them
   - names fuzzy-matched to the roster
   - dedupe by persistence (a line must stay at least 0.5 s)
   - Read each line once per appearance, not every frame.
4. **Counters** (`pipeline/counters.py`):
   - The **Remaining** counter gives the true elimination time.
   - **Banner helmets** (white = alive, gray = dead) give the team of each death.
   - The **banner score** gives the round winner.
5. **Align** each feed elimination, in feed order, to the earliest unused Remaining drop of the victim's team. Knocks keep the feed time and are marked approximate.
6. **Scoreboards:** detect each round-end and match-end scoreboard. Read names (which also provide the roster and teams) and numbers, using digit templates first and OCR as a fallback.
7. **Reconcile:** feed eliminations per player against scoreboard eliminations. Mismatches set `flag` on the event and set `status = needs_review` on the match.
8. **Save** via `db.save_match()` and write one evidence PNG per event.
9. **Delete or keep the video** according to Settings.

Rules:
- Flag low-confidence rows. Never guess.
- Never interact with the game client, its memory, or its files. Only read the recorded video.

Background on the HUD and timing is in `docs/kill-feed-reference.md`. The feed is paced about 2 s per line, so feed time lags the true time.

## 5. Video retention and recording settings
- Setting "After processing": **Delete video** (default), **Keep video**, or **Keep a small HUD-only copy** (ffmpeg crop of the feed and banner, about 50–100 MB).
- Recommended OBS settings:
  - about 6 Mbps video, no audio track (tested: identical results to 15 Mbps, about 0.8 GB per 18-minute match)
  - MKV container
  - GameLoop fullscreen
- A layout profile describes where each HUD element sits for one setup. Store them as JSON in the data folder (`profiles/<name>.json`) with:
  - kill-feed box
  - Remaining digit box
  - helmet positions for each team size
  - score boxes
  - scoreboard table grid
  - icon templates
- A **calibration wizard** builds a profile: pick a frame from a sample clip, then drag a box over each element.

## 6. Screens (PySide6)
1. **Matches** (home screen)
   - Table, newest first: date & time, room code, mode, team size, rounds, winner, players, eliminations, rows to review, status.
   - Filters: date range and player search.
   - Buttons: Open, Export selected, Export date range, Delete match.
2. **Match detail**, with tabs:
   - **Players:** per-player totals with a scoreboard check column.
   - **Events:** time-ordered table. Flagged rows are yellow. Clicking a row shows its evidence image and lets you fix killer, victim, type or weapon (`db.correct_event`).
   - **Rounds**
   - **Scoreboard**
   - "Export to Excel" button.
3. **Players**
   - Roster with nicknames.
   - Add aliases, or merge two players into one.
   - Career totals (`v_player_career`).
4. **Process**
   - Drop or select a recording.
   - Toggle "Watch my OBS folder".
   - Queue with a progress bar and an estimated time.
   - Log.
   - Processing runs on a worker thread so the window stays responsive.
5. **Settings**
   - watch folder
   - after-processing policy
   - layout profile + calibration
   - data folder (read-only display with an "Open folder" button)
   - default export folder

## 7. Excel export (done: `pwt/export_excel.py`)
- **One match:** Summary (match info + player table with the scoreboard check), Events, Rounds, Scoreboard.
- **Date range:** Matches, Player totals, Player per match, All events.
- Formatting:
  - bold header row, frozen panes, auto-filter
  - times shown both as seconds and as mm:ss
  - flagged rows highlighted

## 8. Phases and acceptance

| Phase | Scope | Done when |
|---|---|---|
| 0 ✅ | Prototype pipeline; SQLite schema + data layer; Excel export; CLI; tests | `python tests/test_db_export.py` passes |
| 1 | Pipeline as a library: `process_video(path, profile) -> MatchResult`. Layout profiles replace hard-coded coordinates. OpenCV decode. Roster and teams from the scoreboard. Round segmentation. Scoreboard digits. Evidence crops. Read each line once. | Test clip reproduces its 3 events. One real full match: at least 95% of feed eliminations reconcile with the scoreboards, and runtime is under 5 min on Chirag's laptop. |
| 2 | `python -m pwt process <file>`, watch-folder mode, retention policy | Drop a recording in the folder and it appears in `list` without anyone touching it |
| 3 | PySide6 app, screens 1–5 | A non-developer can process, browse, fix a flagged row and export |
| 4 | PyInstaller build + GitHub Actions release zip; bundle Tesseract (or remove the OCR dependency) | A fresh Windows PC: unzip, run, process the sample clip |
| 5 (optional) | Shared results (Google Sheet sync or shared DB file) | Friends see stats without the app |

## 9. Open questions (answer from real recordings)
- Does each helmet slot map to a fixed player?
- Is blue always team 1, or always the spectated player's team?
- What do the four scoreboard columns all labelled "No. of Eliminations" actually mean? Is damage taken ever shown?
- What do classic (non-round) rooms look like?
- Icons still needed: headshot, grenade, vehicle, zone, fall, teamkill, revive, and a finish while teammates are alive.
- How does the HUD change with a bigger kill feed and in fullscreen? Recalibrate.

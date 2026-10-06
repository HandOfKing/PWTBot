# PWT: notes for Claude Code

## What this is
- A tool that reads **OBS recordings** of PUBG Mobile World of Wonder (WoW) custom rooms and
  turns them into a table of eliminations.
- Chirag records the match himself and runs the tool afterwards. One command in, one CSV out.
- Events land in SQLite, browsable by date and exportable to Excel.

**Read `docs/ARCHITECTURE.md` first — it is the contract: the pipeline, the
invariants, and the definition of done. Then `docs/RUNBOOK.md` to run it, and
`docs/roster.md` for player spellings.**

## Scope — read this before proposing work
This tool analyses **recorded video only**. Do not build, restore or extend:
- live screen capture, real-time analysis, or anything that watches the game as it plays
- auto-scroll or any other input sent to the game
- a desktop GUI, a PyInstaller bundle, or a Releases zip
- folder watching

`pwt/capture/sources.py` still contains `LiveScreenSource` and `pwt live` still exists. They are
**legacy and unsupported**. Do not spend time on them. `FileReplaySource` is the only path that matters.

## Target footage
First-person **spectator**, round-based WoW room, 6v6, recorded with OBS from GameLoop.
The kill feed **cannot be enlarged** — that option only exists for a player in the match, not a
spectator. Plan for ~16px text at 1080p. Recording at 1440p or 2160p is the single biggest
lever on OCR accuracy. Replay samples at 12 fps by default (`--fps`); the recording's own
frame rate barely matters.

## Rules
- Read pixels only. Never touch the game's memory, files or network.
- **Flag, never guess.** A wrong name is far worse than a flagged one. Rows that cannot be
  resolved are emitted with `flag=UNRESOLVED` and their raw OCR, never dropped.
- **Icons classify, they never gate.** `templates/` holds a handful of weapons; a kill with any
  other gun matches nothing. A row with zero icon matches is still a valid feed row. Reinstating
  `if not icons: continue` takes a real recording from 30 kills to 0. (Narrow exception: the two
  paths that only *add* rows the main detector missed -- round-end text search and short lines --
  require an icon; see ARCHITECTURE invariant 2.)
- **The roster finds the names, it does not validate them.** OCR never reads these names
  correctly (`KG696969` → `KGBSEIES`). Fuzzy-match every token to the roster through the glyph
  fold in `names.py` and take the nearest, subject to a score threshold *and* a margin over the
  runner-up. Treating the roster as a membership test gives 0% accuracy.
- **Read numbers with digit templates, not tesseract.** It misreads this HUD font: `52` → `2`,
  `12` → `2`, `11` → `1`.
- HUD coordinates live in layout-profile JSON, never in code. Different footage needs a
  different profile — see "Profiles" below. Do not tune one profile to satisfy two recordings.
- Master clock = sampled frame index (t = index / fps). The in-game timer is a cross-check only.
  - The answer must not depend on `--fps`: eliminations must equal the Remaining counter's
    drops at every rate. Track and read on video time, never on frame counts.
  - Eliminations take their true time from drops in the **Remaining** counter.
  - Knocks keep the time their kill-feed line appeared, marked approximate.
  - Feed time is not event time: it lags up to 3.5s and can arrive out of causal order.
- Schema changes need a migration and a bump of `PRAGMA user_version`.
- Target Windows 10/11, fully offline. Use `pathlib`. Keep dependencies small.
- Never commit videos (`*.mp4`, `*.mkv`). Test recordings live in `clips/`, which is gitignored.

## Profiles
| Profile | Footage | Row detector |
|---|---|---|
| `gameloop-windowed-1080p` | the 2026-10-01 2v2 test clip | `text` (density scan) |
| `gameloop-spectator-6v6-1080p` | first-person spectator 6v6 | `panel` (dark-padding scan) |

`feed.row_detect` picks between them. `panel` is required when the feed overlays moving scenery,
because text density finds the scenery instead of the rows. `text` is required for the 2v2 clip,
whose rows sit close enough that `panel` merges two rows into one 70px run. **Neither setting
works for both.** Recording at a new resolution needs a new profile; `pwt calibrate` is the
intended way to measure one.

## Known gaps — do not paper over these
1. **Remaining digit templates are incomplete: 5, 8 and 9 are missing.**
   `digits_remaining` was harvested from the 2v2 clip, which never went above 4,
   so it held only {2,3,4}. 0,1,2,4,6,7 have since been harvested from the 6v6
   recording and Remaining now reads correctly on 84% of frames. The 6v6 clip
   never showed 5, 8 or 9, so those still need cutting from another recording.
   Until then a frame showing one reads `None` -- flagged, never wrong.
2. **6v6 helmet positions are not measured.** 6v6 draws helmets in two rows,
   4 above and 2 below. The profile says so explicitly instead of guessing.
   Without them an elimination has no team, so `_align` cannot use its team
   filter and leans on the round and max-lag guards instead. This is the single
   biggest remaining accuracy win.
3. **Weapon templates: only UMP45.** Everything else reads `unknown`, by design:
   an M416 matches the UMP45 template at 0.70, so a loose threshold invents
   weapons. AKM, M416 and a headshot crosshair still need cutting.
4. **The 6v6 scoreboard only captures 6 of 12 rows.** The rest need scrolling,
   which is out of scope, so reconciliation against the board is partial.
5. **Character templates for names (`chars_feed/`) do not exist yet.**
   `chars.py` and `tools/harvest_chars.py` are written and waiting. Finishing
   them removes the Tesseract dependency, which is what makes a self-contained
   .exe practical.

## Where things are
- `pwt/engine/engine.py`: the per-frame engine.
- `pwt/readers/`: feed, counters, screens, names, digits, chars, mask.
- `pwt/profiles/*.json`: coordinates.
- `pwt/templates/`: icons and digits. Rebuild with `tools/cut_templates.py`.
- `pwt/db.py`: `LiveMatch`, rename/alias.
- Status and findings: `docs/PWT_BRIEF.md` §12 and §15.

## Commands (keep these working)
```
python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt
python tests/run_all.py
python -m pwt replay clips\Video_Project_7.mp4 --profile gameloop-windowed-1080p
```
The 2v2 clip must keep reproducing the §11 ground truth. That is the regression test.

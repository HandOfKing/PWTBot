# PWT: notes for Claude Code

## What this is
- A tool that reads **OBS recordings** of PUBG Mobile World of Wonder (WoW) custom rooms and
  turns them into a table of eliminations.
- Chirag records the match himself and runs the tool afterwards: the desktop app (`app/main.py`,
  shipped as a Windows zip) or one command (`python -m pwt replay`). Recording in, tables out.
- Events land in SQLite, browsable by date and exportable to Excel.

**Read `docs/ARCHITECTURE.md` first — it is the contract: the pipeline, the
invariants, and the definition of done. Then `docs/DECISIONS.md` (what is decided and what was
already tried and rejected), the newest `docs/handoff/HANDOFF-*.md` (status and next steps),
`docs/RUNBOOK.md` to run it, and `docs/roster.md` for player spellings.**

## Scope — read this before proposing work
This tool analyses **recorded video only**. Do not build, restore or extend:
- live screen capture, real-time analysis, or anything that watches the game as it plays
- auto-scroll or any other input sent to the game
- folder watching

The desktop app IS in scope (Chirag, 2026-10-05): Tkinter, `app/main.py`, a thin window over
`pwt/process.py`. Keep logic out of the window so it can be tested without a display. It is
built and self-tested on a Windows runner by `.github/workflows/build-windows.yml` (repo root).

**One version (Chirag, 2026-10-07).** One layout, one pipeline (`pwt/process.py`, which both the app
and `python -m pwt replay` call), one branch (`main`). The 2v2 profile, live capture, the CSV-sample
importer and their tests were deleted. Do not reintroduce parallel paths; a second layout would need
Chirag's say-so and its own measured profile.

## Target footage
First-person **spectator**, round-based WoW room, 6v6, recorded with OBS from GameLoop.
The kill feed **cannot be enlarged** — that option only exists for a player in the match, not a
spectator. Plan for ~16px text at 1080p. Recording at 1440p or 2160p is the single biggest
lever on OCR accuracy. Replay samples at 12 fps by default (`--fps`); the recording's own
frame rate barely matters.

## Rules
- **Match names against the run's roster only** (the app's names box, plus those players'
  aliases: `db.roster_names`). Never against every name in the database: stored misreads
  steal matches and break the margin rule (2026-10-07: 179 vs 312 of 385 rows named).
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
- HUD coordinates live in the layout-profile JSON, never in code.
- Master clock = sampled frame index (t = index / fps). The in-game timer is a cross-check only.
  - The answer must not depend on `--fps`: eliminations must equal the Remaining counter's
    drops at every rate. Track and read on video time, never on frame counts.
  - Eliminations take their true time from drops in the **Remaining** counter.
  - Knocks keep the time their kill-feed line appeared, marked approximate.
  - Feed time is not event time: it lags up to 3.5s and can arrive out of causal order.
- Schema changes need a migration and a bump of `PRAGMA user_version`.
- Target Windows 10/11, fully offline. Use `pathlib`. Keep dependencies small.
- Never commit videos (`*.mp4`, `*.mkv`). Test recordings live in `clips/`, which is gitignored.

## The layout
`pwt/profiles/gameloop-spectator-6v6-1080p.json` (`profiles.DEFAULT`): first-person spectator,
6v6, GameLoop 1920x1080. The banner counts as up when >= 25% of each score box is team-coloured
(a two-digit score covers sample pixels; that lost rounds 16-25 of a match). A round also starts
on a Remaining reset after a board, and a round board for an unseen round creates that round.

## Known gaps — do not paper over these
1. **Weapon templates: only UMP45.** Everything else reads `unknown`, by design: an M416
   matches the UMP45 template at 0.70, so a loose threshold invents weapons. AKM, M416 and a
   headshot crosshair still need cutting (Video_Project_13 shows several).
2. **Banner score digits: only 0 and 1.** Round winners are not read yet. Video_Project_13
   shows 5, 9 and 10.
3. **The Remaining counter decides how many died.** A kill row that claims no drop (even after
   the end-of-recording pass that lets late rows of a wipe claim their round's deaths) is
   flagged `NO_DROP` and not counted. That is only safe while every Remaining digit reads:
   0-9 and "11" were harvested 2026-10-07 (0 WRONG on Video_Project_13). Re-check it on any
   new footage before trusting counts.
4. **Character templates for names (`chars_feed/`) do not exist yet.** `chars.py` and
   `tools/harvest_chars.py` are written and waiting. Finishing them removes Tesseract.

## Where things are
- `pwt/engine/engine.py`: the per-frame engine.
- `pwt/readers/`: feed, counters, screens, names, digits, chars, mask.
- `pwt/profiles/gameloop-spectator-6v6-1080p.json`: coordinates.
- `pwt/templates/`: icons and digits. Add digit shapes with `tools/harvest_board_digits.py` / `tools/harvest_remaining_digits.py`.
- `pwt/db.py`: `LiveMatch`, rename/alias.
- Status: the newest `docs/handoff/HANDOFF-*.md`. Why things are the way they are, and the ideas
  already rejected with their numbers: `docs/DECISIONS.md`. Numbers over time: `docs/METRICS.md`.
- `docs/PWT_BRIEF.md` is the SUPERSEDED live-capture design (2026-10-02). Historical only; do not build from it.
- Claude Code helpers (repo root `.claude/`): agents `pwt-verifier`, `pwt-reviewer`, `pwt-calibrator`,
  `pwt-run-analyst`; skills `/start-session`, `/handoff`, `/experiment`, `/measure`, `/cut-clip`,
  `/harvest-templates`. Hooks in `.claude/hooks/` block out-of-scope code and ask before contract files change.

## Commands (keep these working)
```
python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt
python tests/run_all.py
python -m pwt replay clips\Video_Project_9.mp4 --roster <names>
python app\main.py                                   # the desktop app from source
```
`Video_Project_9.mp4` must give 14 eliminations at --fps 4, 12 and 24 (ARCHITECTURE §6).

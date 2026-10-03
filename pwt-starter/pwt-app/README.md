# PWT: live stats for PUBG Mobile WoW custom rooms

PWT watches a World of Wonder room **live**. It captures the GameLoop screen at 12 fps and reads every frame as it arrives, then saves:
- every knock, kill and death, with **true times**, killer, victim and weapon
- round results
- **round-by-round and match scoreboards**

Everything goes into SQLite, browsable by date and time, and exportable to Excel. No OBS, no recordings.

Full spec and phases: [`docs/PWT_BRIEF.md`](docs/PWT_BRIEF.md). Rules for Claude Code: [`CLAUDE.md`](CLAUDE.md).

## Status
- **Phase 0: done.** The engine reproduces the test clip's ground truth end to end:
  - 3 events with true and feed times
  - round 1 won by blue
  - 4/4 scoreboard rows with values and teams
  - feed eliminations reconcile with the board
  - names learned from the scoreboard, with or without a roster
- **Next: Phase 1,** the capture test on the laptop (`tools/capture_bench.py`).

## Setup (Windows, VS Code)
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
Also install **Tesseract OCR** (UB Mannheim build). Put it on PATH, or set `PWT_TESSERACT=C:\Program Files\Tesseract-OCR\tesseract.exe`.

Put the test clip at `clips\Video_Project_7.mp4`. `clips/` is gitignored; never commit videos.

## Commands
```
pytest -q                                   # or: python tests/run_all.py
python -m pwt replay clips\Video_Project_7.mp4          # run the engine on a recording, print the match
python -m pwt live --seconds 600                        # live capture (run as admin if GameLoop is elevated)
python -m pwt list | python -m pwt show 1
python -m pwt players --add TheWolverine Makjets69      # saved roster; names are matched against it
python -m pwt rename Makjats69 Makjets69                # fix a misread name once; the old spelling becomes an alias
python -m pwt export --match 1 match.xlsx               # or: --from 2026-10-01 --to 2026-10-31 october.xlsx
python tools/capture_bench.py --seconds 180             # Phase 1: laptop capture test while spectating
python tools/cut_templates.py clips\Video_Project_7.mp4 # rebuild templates and fixtures from the clip
```
The database lives in `%LOCALAPPDATA%\PWT\pwt.db`; `python -m pwt where` shows the path. Evidence images (a crop of every feed line, and the scoreboard frames) go next to it.

## Layout
```
pwt/capture/sources.py   LiveScreenSource (dxcam -> mss) and FileReplaySource: same (t, frame) stream
pwt/engine/engine.py     state machine, Remaining/helmet timing, feed line tracking, alignment, scoreboards
pwt/engine/runner.py     capture thread -> bounded queue -> engine
pwt/readers/             mask, feed, counters, screens (scoreboard), digits (templates), names (OCR + roster)
pwt/profiles/*.json      every HUD coordinate (windowed test-clip layout today; recalibrate for fullscreen)
pwt/templates/           kill-feed icons, scoreboard header, digit glyphs per font
pwt/db.py, schema.sql    SQLite: LiveMatch (live writes), queries, rename/alias, inferred revives view
pwt/export_excel.py      per match (incl. round-by-round scoreboards) and per date range
tools/                   capture_bench.py (Phase 1), cut_templates.py
tests/                   pytest; fixtures are frames from the test clip
```

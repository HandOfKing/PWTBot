# PWT: video analysis for PUBG Mobile WoW custom rooms

PWT analyses recorded spectator footage from World of Wonder custom rooms and extracts:
- every knock, kill and death, with **true times**, killer, victim and weapon
- round results
- **round-by-round and match scoreboards**

Results go into SQLite and export to Excel/CSV.

Full spec: [`docs/PWT_BRIEF.md`](docs/PWT_BRIEF.md). Rules for Claude Code: [`CLAUDE.md`](CLAUDE.md).

## Setup (Windows, VS Code)
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Put recordings at `clips\`. `clips/` is gitignored; never commit videos.

## Commands
```
pytest -q                                               # or: python tests/run_all.py
python -m pwt replay clips\Video_Project_7.mp4          # run the engine on a recording, print the match
python -m pwt list | python -m pwt show 1
python -m pwt players --add TheWolverine Makjets69      # saved roster; names are matched against it
python -m pwt rename Makjats69 Makjets69                # fix a misread name once; the old spelling becomes an alias
python -m pwt export --match 1 match.xlsx               # or: --from 2026-10-01 --to 2026-10-31 october.xlsx
python tools/cut_templates.py clips\Video_Project_7.mp4 # rebuild templates and fixtures from the clip
```
The database lives in `%LOCALAPPDATA%\PWT\pwt.db`; `python -m pwt where` shows the path. Evidence images (a crop of every feed line, and the scoreboard frames) go next to it.

## Layout
```
pwt/engine/engine.py     state machine, Remaining/helmet timing, feed line tracking, alignment, scoreboards
pwt/engine/runner.py     capture thread -> bounded queue -> engine
pwt/readers/             mask, feed, counters, screens (scoreboard), digits (templates), names (OCR + roster)
pwt/profiles/*.json      every HUD coordinate (windowed test-clip layout today; recalibrate for fullscreen)
pwt/templates/           kill-feed icons, scoreboard header, digit glyphs per font
pwt/db.py, schema.sql    SQLite: LiveMatch (live writes), queries, rename/alias, inferred revives view
pwt/export_excel.py      per match (incl. round-by-round scoreboards) and per date range
tools/                   cut_templates.py
tests/                   pytest; fixtures are frames from the test clip
```

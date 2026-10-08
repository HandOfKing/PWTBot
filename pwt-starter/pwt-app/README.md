# PWT: match stats from PUBG Mobile WoW recordings

PWT reads OBS recordings of World of Wonder custom rooms (first-person spectator, 6v6,
round-based, GameLoop 1920x1080) and produces:
- every knock and elimination, with **true times**, killer, victim and round
- the **end-of-match scoreboard** for every player (eliminations, assists, damage dealt and
  taken, knock outs), and the round boards
- an Excel workbook and CSV per match; every match is kept in SQLite

One version: one layout, one pipeline (`pwt/process.py`) behind both the desktop app and the
command line, one branch (`main`). Rules for Claude Code: [`CLAUDE.md`](CLAUDE.md).
Contract: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). How to run: [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

## The desktop app
Download the `PWT-windows` artifact from the latest `build-windows` run on GitHub, unzip,
double-click `PWT.exe`. `README.txt` beside it explains the rest.

## From source (Windows)
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app\main.py                                      # the desktop app
python -m pwt replay clips\Video_Project_9.mp4          # the same pipeline, printed
python tests\run_all.py
```
Test recordings go in `clips\` (gitignored; never commit videos).

## Layout
```
pwt/process.py           one recording in, xlsx / csv / log out (the app and `pwt replay` both call it)
pwt/engine/engine.py     screen state, rounds, Remaining timing, feed lines, alignment, scoreboards
pwt/readers/             feed rows, counters (Remaining, banner, helmets), screens (scoreboards),
                         digits (templates), names (OCR + roster matching)
pwt/profiles/gameloop-spectator-6v6-1080p.json   every HUD coordinate
pwt/templates/           kill-feed icons, scoreboard header, digit glyphs per font
pwt/db.py, schema.sql    SQLite: matches, events, scoreboards, players and aliases
pwt/export_excel.py      per match and per date range
app/main.py              the Tkinter window and its self-test
tools/                   template harvesting (board digits, Remaining digits, name characters)
tests/                   fixtures are frames from Video_Project_9 / _11 / _13
```

# PWT: notes for Claude Code

## What this is
- A Windows desktop app that turns OBS recordings of PUBG Mobile WoW custom rooms into match stats.
- Stats are kill-feed events with true times, round results and scoreboards.
- They're saved in SQLite, browsable by date/time, and exportable to Excel.
- Ships as a portable zip from GitHub Releases.
- Full spec: `docs/SPEC.md`. HUD and timing facts: `docs/kill-feed-reference.md`.

## Layout
- `pwt/pipeline/`: video → events.
  - `killfeed.py`: feed rows
  - `counters.py`: Remaining, helmets, alignment
  - `templates/`: icon masks
  - This is still prototype code, with hard-coded coordinates for the windowed test clip.
- `pwt/schema.sql`, `pwt/db.py`: data layer. `save_match()` writes one match in a single transaction.
- `pwt/ingest.py`: pipeline output → `save_match()` input.
- `pwt/export_excel.py`: one match, or a date range.
- `pwt/cli.py`: `python -m pwt where | import-sample | list | export`
- `tests/`: `python tests/test_db_export.py` (or pytest). Keep these green.
- `samples/`: test-clip events and example exports. Never commit recordings (*.mkv, *.mp4).

## Commands
```
python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt
python tests/test_db_export.py
python -m pwt import-sample && python -m pwt list && python -m pwt export --match 1 out.xlsx
```

## Rules
- Only read the recorded video. Never touch the game client, its memory, files or network: that breaks the terms of service and risks a ban.
- Flag low-confidence rows (`events.flag`). Never guess a name or a type.
- HUD coordinates belong in layout profiles (JSON), not in code. Recalibrate when the layout changes (fullscreen, bigger kill feed, team size).
- The frame index / 4 fps is the master clock. Eliminations take their true time from Remaining drops, knocks keep the feed time.
- Schema changes need a migration in `db.init_db` and a bump of `SCHEMA_VERSION`.
- Target Windows 10/11 and keep the app fully offline. Paths: use `pathlib`, and `db.data_dir()` for data.
- Keep dependencies small; every dependency adds weight to the PyInstaller bundle.

## Current phase
- Phase 0 is done.
- Next is Phase 1 (SPEC §8): make the pipeline a library, `process_video(path, profile) -> MatchResult`, with layout profiles, scoreboard reading and round segmentation, then test it on a real full match.

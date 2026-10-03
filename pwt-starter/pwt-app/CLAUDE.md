# PWT: notes for Claude Code

## What this is
- A Windows desktop app that watches a PUBG Mobile World of Wonder (WoW) custom room **live**.
- It captures the GameLoop screen at 12 fps and reads every frame as it arrives: kill feed, Remaining counter, team helmets, round banner, round and match scoreboards.
- It writes each event to SQLite as it happens. No OBS, no recordings.
- Matches are browsable by date/time and export to Excel.
- Ships as a portable zip from GitHub Releases.

**Full instructions: `docs/PWT_BRIEF.md`.** Read it before any work. §12 lists the phases and their acceptance checks.

## Rules
- Read pixels only. Never touch the game's memory, files or network.
- The only input PWT may ever send is the **opt-in auto-scroll** on scoreboards:
  - only in the `scoreboard` state
  - F8 kill switch
  - every action logged
  - off by default
  - for the dedicated spectator account only (PUBG Mobile bans macros)
- Live (screen) and replay (video file) frame sources must feed the **identical** engine. Develop and test on replay.
- The analyser thread never blocks. OCR and scoreboard reading run on worker threads.
- Commit each confirmed item to the DB as it happens (`LiveMatch`), so a crash loses nothing.
- Flag low-confidence rows or cells (`flag` column). Never guess a name, an event type or a number.
- Read numbers with **digit templates**, not tesseract: it misreads this HUD font ("52" → "2").
- HUD coordinates live in layout-profile JSON, never in code.
- Master clock = capture time since match start.
  - Eliminations take their true time from drops in the **Remaining** counter.
  - Knocks keep the time their kill-feed line appeared.
- Schema changes need a migration and a bump of `PRAGMA user_version`.
- Target Windows 10/11, fully offline. Use `pathlib`. Keep dependencies small, because they all end up in the PyInstaller bundle.
- Never commit videos (*.mp4, *.mkv). Test recordings live in `clips/`, which is gitignored.

## Commands (keep these working)
```
python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt
pytest -q                                            # or: python tests/run_all.py
python -m pwt replay clips\Video_Project_7.mp4       # test clip, must reproduce §11 ground truth
python tools/capture_bench.py --seconds 180          # Phase 1, on the laptop while spectating
```

## Where things are
- `pwt/engine/engine.py`: the per-frame engine.
- `pwt/readers/`: the readers.
- `pwt/profiles/*.json`: coordinates.
- `pwt/templates/`: icons and digits. Rebuild them with `tools/cut_templates.py`.
- `pwt/db.py`: `LiveMatch`, rename/alias.
- Status and findings: `docs/PWT_BRIEF.md` §12 and §15.

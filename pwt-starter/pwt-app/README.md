# PWT: PUBG Mobile WoW room stats

Turns OBS recordings of your World of Wonder custom rooms into stats:
- who knocked or killed whom
- with what weapon
- when
- round results and scoreboards

Every match is saved by date and time, and anything can be exported to Excel.

> Status: Phase 0. The data layer, Excel export and command line work. The video pipeline is a prototype, and the desktop app is next. See `docs/SPEC.md`.

## For players: running the app (from Phase 4)
1. Go to the repo's **Releases** page and download `PWT-<version>-windows.zip`.
2. Unzip it anywhere and double-click `PWT.exe`. The first time, Windows may show "Windows protected your PC": click More info, then Run anyway.
3. Point it at your OBS recordings folder, or drop in a recording.
4. Open a match to see the stats, then click **Export to Excel**.

Your data lives in `%LOCALAPPDATA%\PWT\pwt.db`. To keep everything next to the app instead, put an empty file named `portable.txt` beside `PWT.exe`.

Recommended OBS settings: about 6 Mbps video, no audio, MKV, GameLoop fullscreen.

## For developers (VS Code + Claude Code)
```
git clone <this repo> && cd pwt
python -m venv .venv
.venv\Scripts\activate          # Windows (Git Bash: source .venv/Scripts/activate)
pip install -r requirements.txt
python tests/test_db_export.py  # should print 4 x ok
python -m pwt import-sample     # loads the test clip into the database
python -m pwt list
python -m pwt export --match 1 match.xlsx
python -m pwt export --from 2026-10-01 --to 2026-10-31 october.xlsx
```
The prototype video pipeline also needs Tesseract OCR on your PATH (the UB Mannheim Windows build) until it moves to templates. Keep your test clip out of git; put it in a local `clips\` folder.

**Release build:** push a tag such as `v0.1.0`. GitHub Actions builds the Windows zip and attaches it to a Release (see `.github/workflows/build-windows.yml`).

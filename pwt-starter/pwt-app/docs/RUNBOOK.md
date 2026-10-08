# PWT runbook — how to run it

There is one version of everything: one layout (first-person spectator, 6v6, GameLoop
1920x1080), one pipeline (`pwt/process.py`), one branch (`main`). The desktop app and
`python -m pwt replay` run the same code and write the same files.

## The desktop app (Windows) — for anyone

Download the `PWT-windows` artifact from the latest `build-windows` run on GitHub (or the zip
on a Release), unzip, run `PWT.exe`. Pick the recording, check the player names, press Start.
Results land next to the recording: `<name> - PWT.xlsx`, `- PWT events.csv`, `- PWT log.txt`.
`README.txt` in the folder says the same for a non-developer.

**Player names.** One per line, spelled exactly as in the game (`docs/roster.md`). Kill-feed
names are matched against this list only. The box starts with the list used last time
(`roster.txt` in the data folder), or the bundled one on first run. A player missing from the
list goes unnamed in the feed; the result panel and the log name anyone the final scoreboard
showed who is not on the list, so you can add them and run again.

**Building it:** push to `main` or push a `v*` tag. `.github/workflows/build-windows.yml`
builds on a Windows runner, bundles an English-only Tesseract, and refuses to publish unless
`PWT.exe --selftest` passes. A tag also attaches the zip to a Release.

## From source

From `pwt-starter/pwt-app`:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python tests\run_all.py
python app\main.py
```

Tesseract must be on PATH (`tesseract --version`), or set `PWT_TESSERACT`.

The command line runs exactly what the app runs:

```
python -m pwt replay "D:\OBS\match.mkv"
```

| Flag | Default | Notes |
|---|---|---|
| `--roster A B ...` | the last run's list, else `docs/roster.md` | the names to match against |
| `--fps` | `12` | The table is the same at any rate, but rows on screen under ~0.25 s need 12+. On `Video_Project_9.mp4`: 4 fps names 9 of 14 eliminations, 12 and 24 fps all 14. |
| `--out DIR` | next to the recording | where the xlsx / csv / log go |
| `--replace` | off | the recording was processed before: replace that result |
| `--force` | off | run even though the layout check failed (every row suspect) |
| `--quiet` | off | no per-event log |

Afterwards: `python -m pwt list`, `show 1`, `export --match 1 match.xlsx`, `players`,
`rename OLD NEW` (fix a misread name; OLD becomes an alias), `where` (the database).

## Recording tips

- At the end of the match stay on the final scoreboard and scroll it slowly top to bottom, so
  every row is on screen for a second or two. That board covers the whole match.
- 1920x1080. Another resolution or emulator layout is refused by the layout check, not
  guessed at.

## Time

It streams the file. A 32-minute match took 20 minutes at 24 fps on Chirag's laptop
(i7-11800H); 12 fps takes about two thirds of that.

## Reading the output

Workbook sheets: **Summary** (per player: feed eliminations credited to the knocker, knocks,
deaths, and the end-of-match board's eliminations and knock outs beside them, with a Check
column), **Events**, **Rounds**, **Round scoreboards**, **Match scoreboard**.

| Column | Meaning |
|---|---|
| `true_time_s` | seconds from the start of the recording |
| `time_source` | `Remaining drop` = the true time of the death; `feed (approx)` = when the line appeared |
| `event_type` | `knock`, `kill`, `eliminated_knocked` (died while knocked when the team was wiped) |
| `flag` | blank = good; `UNRESOLVED` = a feed row whose name(s) did not read; `NO_FEED_ROW` = the Remaining counter dropped but no readable feed row said who; `NO_DROP` = a kill row the counter saw no death for (a repeat or a misread icon), kept but not counted |

## Scoreboards

Five columns on 6v6 boards: Eliminations, Assists, Damage Dealt, Damage Taken, Knock Outs.
A board up 5 s or more (or still up when the recording ends) is the end-of-match board; round
boards are up ~2.9 s. Numbers are read with digit templates (`pwt/templates/digits_board`).
To teach a new digit shape from a board whose values you know:
`python tools/harvest_board_digits.py <clip> <truth.csv>` (format:
`tests/fixtures/match_board_vp11.csv`), then `--check-only` on a different board: 0 WRONG.

## The Remaining counter

Read with `pwt/templates/digits_remaining` (all digits, plus an "11" shape: the two 1s often
touch). To add shapes from a clip whose values you know:
`python tools/harvest_remaining_digits.py <clip> <truth.csv> --harvest-before <s>`
(format: `tests/fixtures/remaining_vp13.csv`). It must report 0 WRONG.

## When it goes wrong

**"The layout does not fit this recording"** — not a 1080p first-person spectator recording of
the expected HUD. Do not force it unless you know why.

**Names consistently missing for one player** — they are not in the names list, or spelled
differently. Check the "on the scoreboard but not in the player list" line in the log.

**`tesseract` not found** — see setup above.

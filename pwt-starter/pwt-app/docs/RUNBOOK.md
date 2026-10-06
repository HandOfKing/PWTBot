# PWT runbook — how to actually run it

## One-time setup

From `pwt-starter/pwt-app`:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Tesseract must be on PATH. Check with `tesseract --version`. If it isn't:
`winget install UB-Mantiainen.Tesseract-OCR` (or the UB Mannheim installer), then reopen the terminal.

Save the roster once so you don't retype it. **Use the exact spellings in
`docs/roster.md`** — a wrong one silently costs you rows:

```
python -m pwt players --add Sarthakkkd RGODxEMPEROR KG696969 KhajwaKILL3R PARABloodthirs OmkarKurhade TheWolverine Strike333 DeathwishツSpy Makjets69 StarJohnnysins Vatsal099999 InnocentDevil enriquelatin Anoydyne15op TrishaSingh BruceWayne³ WonderWoman888
```

Check it works at all:

```
python tests\run_all.py
```

All tests should pass. Two `test_replay_clip` tests skip unless `clips\Video_Project_7.mp4` exists.

---

## The desktop app (Windows) -- for anyone

Download `PWT-<version>-windows.zip` from the repo's Releases page, unzip, run
`PWT.exe`. Pick the recording, check the player names, press Start. Results
land next to the recording (`<name> - PWT.xlsx`, `- PWT events.csv`,
`- PWT log.txt`). `README.txt` in the zip says the same for a non-developer.

Building it: push to `stage-a-fix` or push a `v*` tag. `.github/workflows/build-windows.yml`
builds the zip on a Windows runner, bundles an English-only Tesseract, and refuses to
publish unless `PWT.exe --selftest` passes. A tag also attaches the zip to a Release.

From source: `python app\main.py` (needs Tesseract installed or `PWT_TESSERACT` set).

## The command

```
python -m pwt replay "D:\OBS\match.mkv" ^
  --profile gameloop-spectator-6v6-1080p ^
  --csv events.csv
```

That's it. It prints rounds, events and a per-player table, writes `events.csv`, and stores the
match in SQLite. `^` is the line-continuation character in Windows CMD — in PowerShell use a
backtick `` ` ``, or just put it all on one line.

Afterwards:

```
python -m pwt list                        list every match
python -m pwt show 1                      re-print match 1
python -m pwt export --match 1 match.xlsx Excel
python -m pwt where                       where the database lives
```

### Flags worth knowing
| Flag | Default | Notes |
|---|---|---|
| `--fps` | `12` | Samples per second of video. The table is the same at any rate (rows are tracked and read on video time, not frame counts), but rows on screen under ~0.25 s -- the last rows of a round, as the camera cuts away -- need 12+. On `Video_Project_9.mp4`: 4 fps names 9 of 14 eliminations, 12 and 24 fps name all 14; 24 fps costs ~1.5x the time of 12 for one extra knock. |
| `--profile` | `gameloop-windowed-1080p` | **You must pass the spectator profile.** The default is the old 2v2 one. |
| `--csv` | off | Flat events table. |
| `--roster` | empty | Omit it and names are matched against the saved roster, or learned from the scoreboard. Passing it explicitly is more reliable. |
| `--quiet` | off | Suppresses the per-frame log. Useful on long files. |

---

## Running a full 2 GB match

It streams the file — it never loads the whole video into memory — so a 2 GB file is no
different from a short clip except in time.

**Measured:** 157 s of 1080p took **69 s** on this machine, 75 ms/frame, so roughly **0.45× the
video's duration**. A 2 GB file at 15.9 Mbps is about 17 minutes of video → **expect 8–10 minutes**.
At 2160p, decoding costs more; budget 2–3× that.

**Do a slice first.** Don't discover a bad profile 10 minutes in. Cut 60 seconds containing a
couple of kills and run that:

```
ffmpeg -ss 00:05:00 -t 60 -i "D:\OBS\match.mkv" -c copy slice.mkv
python -m pwt replay slice.mkv --profile gameloop-spectator-6v6-1080p --csv slice.csv
```

Open `slice.csv`. If the killer and victim columns are populated and the names are right, run the
full file. If most rows say `UNRESOLVED`, the profile needs recalibrating — don't run the 2 GB file yet.

**Then the full match:**

```
python -m pwt replay "D:\OBS\match.mkv" --profile gameloop-spectator-6v6-1080p --csv events.csv --quiet
```

You can leave it running; nothing needs watching. The database is written as it goes, so a crash
or Ctrl-C keeps whatever was found (the match is marked `interrupted`).

---

## Reading the output

`events.csv` columns:

| Column | Meaning |
|---|---|
| `round_no` | which round |
| `true_time_s` | seconds from match start |
| `feed_time_s` | when the feed line appeared |
| `time_source` | `remaining_drop` = true time; `feed (approx)` = the feed line's time |
| `killer`, `victim` | matched roster names |
| `event_type` | `knock`, `kill`, `eliminated_knocked` |
| `weapon` | blank unless a template matched strongly |
| `flag` | blank = good; `UNRESOLVED` = a row was there but names wouldn't read |

**Right now every row will say `feed (approx)`.** That is expected, not a bug: true times come
from the Remaining counter, which can't be read until digit templates exist (see `CLAUDE.md`,
Known gaps 1 and 2). Ordering within a round is still right; absolute times lag up to 3.5 s.

A few `UNRESOLVED` rows are normal. On the 6v6 test recording 140 of 218 detected rows resolved
both names. If nearly everything is `UNRESOLVED`, the profile is wrong for that footage.

---

## When it goes wrong

**Everything `UNRESOLVED`, or no events at all** — almost always the wrong profile. Check the
recording's resolution matches the profile's, and that you passed `--profile`.

**`no helmet_positions for team_size=N`** — printed as a NOTE, not a crash. Eliminations lose
team attribution; everything else works.

**Names consistently wrong** — check the roster spelling matches in-game exactly, including `Ø`
and trailing digits. `python -m pwt rename OLD NEW` fixes a misread name and keeps the old one
as an alias.

**`tesseract` not found** — see setup above.

**Recorded at a new resolution** — you need a new profile. Copy the spectator one, update
`resolution` and every pixel box, and verify on a 60 s slice before trusting it.

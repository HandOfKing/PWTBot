# PWT metrics log

Every accuracy claim lands here as a row, with the commit and the exact clip. "Better" without a
row in this table is not a result. Append new rows at the bottom of the right table; never edit
old rows (a wrong row gets a correcting row below it).

Rows marked *(from handoff)* were copied from the 2026-10-07 handoff, not re-measured on 10-08.

## Definition-of-done benchmarks (ARCHITECTURE §6)

Clips live in `pwt-starter/pwt-app/clips/` (gitignored). If a clip is missing the benchmark is
**NOT RUN**, never "pass".

| Date | Commit | Benchmark | Target | Result | Notes |
|---|---|---|---|---|---|
| 10-07 | 151b03d | `tests/run_all.py` | all pass | 37 pass *(from handoff)* | |
| 10-07 | 151b03d | VP9 eliminations, fps 4 / 12 / 24 | 14 / 14 / 14 | 14 / 14 / 14 *(from handoff)* | |
| 10-07 | 151b03d | VP9 eliminations named, 12 fps | — | 14 of 14 *(from handoff)* | 4 fps names 9 of 14 |
| 10-07 | 151b03d | VP13 rounds (`test_rounds.py`) | 3 rounds, elims {1:9, 2:6} | pass *(from handoff)* | also with banner off after 57 s |
| 10-07 | 151b03d | Remaining digits on VP13 (`harvest_remaining_digits.py --check-only`) | 0 WRONG | 0 WRONG; held out 2664/2701 read *(from handoff)* | |

## Full-match runs

Match `2026-10-04 22-55-47` (25 rounds, 12 players). Board truth:
`tests/fixtures/match_board_vp11.csv` — RGOD 30, Makjets 25, Khajwa 22, PARA 21, Wolverine 20,
KG 15, Star 11, Deathwish 8, Anoydyne 7, Trisha 7, Bruce 5, Wonder 0 (171 total).

| Date | App / commit | fps | Rounds | Elims counted | Named | NO_FEED_ROW | UNRESOLVED | NO_DROP | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 10-07 | 0.1.0 | 24 | 22 / 25 | 219 | 100 | 43 | — | — | roster polluted by 119 stored misreads *(from handoff)* |
| 10-07 | 0.2.0 (31beafb) | 12 | 25 / 25 | 171 = board | — | 30 | 16 | 22 | knocks = board Knock Outs for 5 players *(from handoff)* |
| | 151b03d | | | | | | | | **next run goes here** |

## Spot clips

| Date | Commit | Clip | Measure | Result | Notes |
|---|---|---|---|---|---|
| 10-07 | 151b03d | `Output/clips/r20_24-15_25-15.mp4` (round 20) | eliminations named | 4 of 5 (was 0 of 4) | 5th death at 31.3 s has no row on screen *(from handoff)* |
| 10-07 | 31beafb | 385 evidence crops of 22-55-47 | rows with both names | 179 → 312 | run roster instead of all DB names *(from handoff)* |

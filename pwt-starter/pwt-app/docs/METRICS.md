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
| 10-08 | ce397e1 | `tests/run_all.py` | all pass | 37 ok, 0 skipped, 0 FAIL | pwt-verifier; PWT_DATA_DIR scratch; no psutil needed |
| 10-08 | ce397e1 | VP9 eliminations, fps 4 / 12 / 24 | 14 / 14 / 14 | 14 / 14 / 14 | CSV rows kill+eliminated_knocked, flag != NO_DROP; 12 fps run twice, events CSV byte-identical |
| 10-08 | ce397e1 | VP9 eliminations named (both killer and victim), fps 4 / 12 / 24 | — | 9 of 14 / 13 of 14 / 13 of 14 | 12 fps: 1 elim row UNRESOLVED (KG696969 kill at 36.167 s, no victim); handoff said 14 of 14 at 12 fps. Rows with both names, all event types, 12 fps: 28 of 30 (target >=20) |
| 10-08 | ce397e1 | VP9 `KG696969` read | present | yes at all rates (3 / 3 / 4 elim rows at 4 / 12 / 24 fps) | |
| 10-08 | ce397e1 | VP13 rounds (`test_rounds.py`) | 3 rounds, elims {1:9, 2:6} | pass (part of the 37 ok) | |
| 10-08 | ce397e1 | Remaining digits on VP13 (`harvest_remaining_digits.py --check-only`) | 0 WRONG | 0 WRONG; 3978 frames, correct 3929, blank 49 | |
| 10-08 | ce397e1 | Unflagged self-kills (VP9, 4 / 12 / 24 fps) | 0 | 0 / 0 / 0 | |
| 10-08 | ce397e1 + dim fix | `tests/run_all.py` | all pass | 37 ok, 0 skipped, 0 FAIL | pwt-verifier; PWT_DATA_DIR scratch |
| 10-08 | ce397e1 + dim fix | VP9 eliminations, fps 4 / 12 / 24 | 14 / 14 / 14 | 14 / 14 / 14 | kill+eliminated_knocked, flag != NO_DROP; 12 fps run twice, events CSV byte-identical |
| 10-08 | ce397e1 + dim fix | VP9 eliminations named (both killer and victim), fps 4 / 12 / 24 | — | 13 of 14 / 13 of 14 / 13 of 14 | was 9 / 13 / 13; 12 fps: 1 elim row UNRESOLVED (KG696969 kill at 36.167 s, no victim). Rows with both names, all event types: 28 of 29 / 28 of 30 / 31 of 34 at 4 / 12 / 24 fps (target >=20) |
| 10-08 | ce397e1 + dim fix | VP9 `KG696969` read | present | yes at all rates (3 / 3 / 4 elim rows at 4 / 12 / 24 fps) | |
| 10-08 | ce397e1 + dim fix | VP13 rounds (`test_rounds.py`) | 3 rounds, elims {1:9, 2:6} | pass (part of the 37 ok) | |
| 10-08 | ce397e1 + dim fix | Remaining digits on VP13 (`harvest_remaining_digits.py --check-only`) | 0 WRONG | 0 WRONG; 3978 frames, correct 3929, blank 49 | |
| 10-08 | ce397e1 + dim fix | Unflagged self-kills (VP9, 4 / 12 / 24 fps) | 0 | 0 / 0 / 0 | |

## Full-match runs

Match `2026-10-04 22-55-47` (25 rounds, 12 players). Board truth:
`tests/fixtures/match_board_vp11.csv` — RGOD 30, Makjets 25, Khajwa 22, PARA 21, Wolverine 20,
KG 15, Star 11, Deathwish 8, Anoydyne 7, Trisha 7, Bruce 5, Wonder 0 (171 total).

| Date | App / commit | fps | Rounds | Elims counted | Named | NO_FEED_ROW | UNRESOLVED | NO_DROP | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 10-07 | 0.1.0 | 24 | 22 / 25 | 219 | 100 | 43 | — | — | roster polluted by 119 stored misreads *(from handoff)* |
| 10-07 | 0.2.0 (31beafb) | 12 | 25 / 25 | 171 = board | — | 30 | 16 | 22 | knocks = board Knock Outs for 5 players *(from handoff)* |
| 10-08 | 31beafb build (downloaded) | 24 | 25 / 25 | 171 = board | 123 | 30 | 27 | 22 | Chirag's run from the Actions artifact; same size as run 37712114825 |
| 10-08 | 151b03d (source run) | 12 | 25 / 25 | 170 (board 171) | 139 | 22 | 18 | 26 | round 15's last death lost: its Remaining "3" scored 0.78-0.81 on the single "3" template; credited to a player 144 of 171 |
| 10-08 | ce397e1 + dim fix | 12 | 25 / 25 | 170 | 151 | 12 | 16 | 29 | credited 155 of 171; 3 extra junk NO_DROP rows, not counted |
| 10-09 | ce397e1 + dim fix + digits + board guards | 12 | 25 / 25 | **171 = board** | 152 | 12 | 16 | 28 | credited 156 of 171; no player over the board; per round counted = Remaining drops |

"Named" = eliminations whose killer and victim are both named. "Credited" = eliminations credited to a
player by the knocker rule (`v_elim_credit`).

Match `2026-10-04 20-27-36` (19 rounds, 11 players: 6 + 5). Truth read by eye from the saved final-board
frames: Star 11, Bruce 6, Makjets 14, Trisha 7, Wolverine 17, KG 21, Anoydyne 3, Wonder 0, RGOD 16,
PARA 14, Khajwa 9 = 118; team scores 14 + 5 = 19 rounds. (The `h` row the board reader returns is junk.)

| Date | App / commit | fps | Rounds | Elims counted | Named | NO_FEED_ROW | UNRESOLVED | NO_DROP | Notes |
|---|---|---|---|---|---|---|---|---|---|
| 10-09 | ce397e1 + dim fix + digits | 12 | 20 / 19 | 119 (board 118) | 100 | 15 | 6 | 30 | phantom round 9: the board detector fired for 0.1 s after round 8's board; credited 101 of 118 |
| 10-09 | + board guards | 12 | 19 / 19 | 119 (board 118) | 100 | 15 | 6 | 30 | one more death counted than the board credits, unexplained (probably a death that is not an elimination); per round counted = drops |

Matches `2026-10-01 23-12-52` and `2026-10-03 00-55-11`: the recordings end without the end-of-match
board, so there is no truth. Only consistency is checked (counted eliminations = Remaining drops per round,
rounds <= 25, no self-kills).

| Date | Match | App / commit | fps | Rounds | Elims counted | Named | NO_FEED_ROW | UNRESOLVED | NO_DROP | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| 10-09 | 10-01 23-12-52 | + dim fix + digits | 12 | 19 | 147 | 137 | 9 | 4 | 19 | near-miss warning: digit 1 rejected 57 times, digit 8 rejected 20 times (8 has one template) |
| 10-09 | 10-03 00-55-11 | + dim fix + digits | 12 | 26 / 25 | 190 | 168 | 10 | 18 | 63 | phantom round 13 (board dipped 0.5 s); 37 junk NO_DROP rows in the last round after the match ended |
| 10-09 | 10-03 00-55-11 | + board guards | 12 | 25 | 190 | 169 | 9 | 18 | 25 | phantom round and the junk tail gone |

Remaining digits, unreadable frames while the HUD is live (frames in the dim are not read by the engine):
22-55-47 315 -> 18 of 15194; 20-27-36 1720 -> 72 of 15944 (a match no template was harvested from);
VP13 49 -> 2 of 3978. WRONG: 0 in all three.

Match `2026-10-17 00-54-26` (25 rounds, 15 players: 8 blue + 7 red, 23.976 fps, 39.6 min). OBS captured the
game alone at the frame's corner: refused by the layout check until the placement shift (M15). Truth: the
end-of-match board read by the run itself (15/15 rows; one Knock Outs cell blank, InnocentDevil).

| Date | App / commit | fps | Rounds | Elims counted | Named | Credited | NO_FEED_ROW | UNRESOLVED | NO_DROP | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| 10-17 | 9e31840 + placement (first version) | 12 | 25 / 25 | **245 = board** | 217 | 226 / 245 | 16 | 17 (12 kill, 5 knock) | 51 | Layout check without the shift: FAIL (banner 0%, Remaining 0%); with it: PASS (banner 79%, Remaining 92%, helmets 90%, names 28/28). Counted = Remaining drops in every one of the 25 rounds. Knock rows 307 (302 both names, 307 with a weapon); credited knocks 304 vs the board's Knock Outs >= 300. NO_DROP: 37 rows with no name read at all, 9 with both. Near-miss: digit 1 rejected for about 4.1 s. 8v7: no helmet positions for 7-8 a side, so no helmet team (as 20-27-36). 1322 s wall. Run with the first version of `placement.py`; the final version finds the same shift (+100,+53, 11 of 12 frames, measured 1729x974), so the frames read are identical. |

## Spot clips

| Date | Commit | Clip | Measure | Result | Notes |
|---|---|---|---|---|---|
| 10-07 | 151b03d | `Output/clips/r20_24-15_25-15.mp4` (round 20) | eliminations named | 4 of 5 (was 0 of 4) | 5th death at 31.3 s has no row on screen *(from handoff)* |
| 10-07 | 31beafb | 385 evidence crops of 22-55-47 | rows with both names | 179 → 312 | run roster instead of all DB names *(from handoff)* |

## Final state of the 2026-10-09 work (code commit d6519b1: dim fix + digit templates + board guards + after-match skip + weapons)

Definition of done on the final tree (pwt-verifier, scratch data folder):

| Date | Check | Target | Result | Notes |
|---|---|---|---|---|
| 10-09 | `tests/run_all.py` | all pass | 39 ok, 0 skipped, 0 FAIL | +2 weapon tests; reader tests include a "3" and an "11" from a match no digit was cut from |
| 10-09 | VP9 eliminations, fps 4 / 12 / 24 | 14 / 14 / 14 | 14 / 14 / 14 | 12 fps run twice, events CSV byte-identical |
| 10-09 | VP9 eliminations with both names, fps 4 / 12 / 24 | — | 13 / 13 / 13 of 14 | rows with both names: 28/29, 28/30, 31/34; KG696969 read in 3 / 3 / 4 elimination rows |
| 10-09 | VP13 Remaining digits (`--check-only`) | 0 WRONG | 0 WRONG; 3976 correct, 2 blank of 3978 | was 49 blank |
| 10-09 | Unflagged self-kills (VP9, 4 / 12 / 24) | 0 | 0 / 0 / 0 | |
| 10-09 | VP9 knock rows with a weapon, fps 4 / 12 / 24 | — | 15/15, 15/15, 15/17 | weapon of every knock/elimination row shared between rates is the same; the 2 extra 24 fps rows are duplicate/fragment rows with no weapon |
| 10-10 | `tests/run_all.py` (one-workbook change, tree dirty on 076f5f2, 15 files) | all pass | 54 ok, 0 skipped, 0 FAIL | includes 15 test_awards tests |
| 10-10 | VP9 eliminations, fps 4 / 12 / 24 (Events sheet of `- PWT.xlsx`, Type kill+eliminated_knocked, Flag != NO_DROP) | 14 / 14 / 14 | 14 / 14 / 14 | 12 fps run twice: True time (s), Type, Killer, Victim, Weapon, Flag identical over 30 rows |
| 10-10 | VP9 eliminations with both names, fps 4 / 12 / 24 | — | 13 / 13 / 13 of 14 | feed rows with both names: 28/29, 28/30, 31/34; KG696969 in 3 / 3 / 4 elimination rows (8 / 8 / 10 rows of any type); same as 10-09 |
| 10-10 | VP13 Remaining digits (`--check-only`) | 0 WRONG | 0 WRONG; 3976 correct, 2 blank of 3978 | same as 10-09 |
| 10-10 | Unflagged self-kills (VP9, 4 / 12 / 24) | 0 | 0 / 0 / 0 | |
| 10-10 | VP9 knock rows with a weapon, fps 4 / 12 / 24 | — | 15/15, 15/15, 15/17 | same as 10-09 |
| 10-10 | `app/main.py --selftest` | PASS | PASS (8 checks ok) | headless, PWT 0.2.0 |
| 10-10 | 22-55-47 full run through `python -m pwt replay` (12 fps), new pipeline | one workbook; eliminations = board 171 | one `- PWT.xlsx` (Scoreboard, Highlights, Events, Run log); 171 eliminations (Events sheet, Flag != NO_DROP), 198 knock rows, 188 usable for roles vs 186 on a partly read board | Highlights: 18 role rows for 12 players; roles not yet checked by Chirag. Clutch dropped from 5 claims to 1 once the 3.5 s feed lag was applied (pwt-reviewer finding) |
| 10-11 | `tests/run_all.py` (awards rewrite D13/D14, tree dirty on 076f5f2, 17 files) | all pass | 56 ok, 0 skipped, 0 FAIL | 17 test_awards tests (was 15); scratch PWT_DATA_DIR |
| 10-11 | VP9 eliminations, fps 4 / 12 / 24 (Events sheet of `- PWT.xlsx`, Type kill+eliminated_knocked, Flag != NO_DROP) | 14 / 14 / 14 | 14 / 14 / 14 | 12 fps run twice: True time (s), Type, Killer, Victim, Weapon, Flag identical over 30 rows; same as 10-10 |
| 10-11 | VP9 eliminations with both names, fps 4 / 12 / 24 | — | 13 / 13 / 13 of 14 | feed rows with both names: 28/29, 28/30, 31/34; KG696969 in 3 / 3 / 4 elimination rows (8 / 8 / 10 rows of any type); same as 10-10 |
| 10-11 | VP13 Remaining digits (`--check-only`) | 0 WRONG | 0 WRONG; 3976 correct, 2 blank of 3978 | same as 10-10 |
| 10-11 | Unflagged self-kills (VP9, 4 / 12 / 24) | 0 | 0 / 0 / 0 | |
| 10-11 | VP9 knock rows with a weapon, fps 4 / 12 / 24 | — | 15/15, 15/15, 15/17 | same as 10-10 |
| 10-11 | `app/main.py --selftest` | PASS | PASS (8 checks ok) | headless, PWT 0.2.0 |
| 10-13 | `tests/run_all.py` (Players + Head to head sheets, playerstats.py, tree dirty on 9705da5, 12 files) | all pass | 60 ok, 0 skipped, 0 FAIL | 4 new test_playerstats tests + test_db_export knock-outcomes test (was 56); scratch PWT_DATA_DIR; 19-name roster |
| 10-13 | VP9 eliminations, fps 4 / 12 / 24 (Events sheet of `- PWT.xlsx`, Type kill+eliminated_knocked, Flag != NO_DROP) | 14 / 14 / 14 | 14 / 14 / 14 | 12 fps run twice: True time (s), Type, Killer, Victim, Weapon, Flag identical over 30 rows; same as 10-11; roster = all 19 names of docs/roster.md |
| 10-13 | VP9 eliminations with both names, fps 4 / 12 / 24 | — | 13 / 13 / 13 of 14 | feed rows with both names: 28/29, 28/30, 31/34; KG696969 in 3 / 3 / 4 elimination rows (8 / 8 / 10 rows of any type); same as 10-11 |
| 10-13 | VP13 Remaining digits (`--check-only`) | 0 WRONG | 0 WRONG; 3976 correct, 2 blank of 3978 | same as 10-11 |
| 10-13 | Unflagged self-kills (VP9, 4 / 12 / 24) | 0 | 0 / 0 / 0 | |
| 10-13 | VP9 knock rows with a weapon, fps 4 / 12 / 24 | — | 15/15, 15/15, 15/17 | same as 10-11 |
| 10-13 | VP9 workbook sheet order (fps 4 / 12 / 24 / 12 repeat) | Scoreboard, Highlights, Players, Head to head, Events, Run log | exactly that, in all four workbooks | 12 fps: Players sheet 17 rows x 6 cols, Head to head 23 rows x 5 cols |
| 10-13 | `app/main.py --selftest` | PASS | PASS (8 checks ok) | headless, PWT 0.2.0; scratch PWT_DATA_DIR and output file |
| 10-17 | `tests/run_all.py` (tree dirty on 9e31840, placement shift M15) | all pass | 68 ok, 0 skipped, 0 FAIL | 8 new test_placement tests (was 60); scratch PWT_DATA_DIR |
| 10-17 | VP9 eliminations, fps 4 / 12 / 24 (Events sheet of `- PWT.xlsx`, Type kill+eliminated_knocked, Flag != NO_DROP; tree dirty on 9e31840, placement shift M15) | 14 / 14 / 14 | 14 / 14 / 14 | 12 fps run twice: True time (s), Type, Killer, Victim, Weapon, Flag identical over 30 rows; same as 10-13; roster = all 19 names of docs/roster.md |
| 10-17 | VP9 eliminations with both names, fps 4 / 12 / 24 (tree dirty on 9e31840, placement shift M15) | — | 13 / 13 / 13 of 14 | feed rows with both names: 28/29, 28/30, 31/34; KG696969 in 3 / 3 / 4 elimination rows (8 / 8 / 10 rows of any type); same as 10-13 |
| 10-17 | VP13 Remaining digits (`--check-only`; tree dirty on 9e31840, placement shift M15) | 0 WRONG | 0 WRONG; 3976 correct, 2 blank of 3978 | same as 10-13 |
| 10-17 | Unflagged self-kills (VP9, 4 / 12 / 24; tree dirty on 9e31840, placement shift M15) | 0 | 0 / 0 / 0 | |
| 10-17 | VP9 knock rows with a weapon, fps 4 / 12 / 24 (tree dirty on 9e31840, placement shift M15) | — | 15/15, 15/15, 15/17 | same as 10-13 |
| 10-17 | VP9 workbook sheet order (fps 4 / 12 / 24 / 12 repeat; tree dirty on 9e31840, placement shift M15) | Scoreboard, Highlights, Players, Head to head, Events, Run log | exactly that, in all four workbooks | 12 fps: Players sheet 17 rows x 6 cols, Head to head 23 rows x 5 cols; same as 10-13 |
| 10-17 | VP9 placement: "shifted by" note in the Run log sheet (fps 4 / 12 / 24 / 12 repeat; tree dirty on 9e31840, placement shift M15) | no note (reference recording sits at +0,+0) | no "shifted by" text in any of the four Run logs; "HUD check: PASS ... footage 1920x1080 profile measured at 1920x1080" in all four | reference placement takes the old path; every number above equals the 10-13 rows |
| 10-17 | `app/main.py --selftest` (tree dirty on 9e31840, placement shift M15) | PASS | PASS (8 checks ok) | headless, PWT 0.2.0; scratch PWT_DATA_DIR and output file |

Four full matches at 12 fps with the final code (`Output/final3`). Counted eliminations = Remaining drops in
every round of every match; no phantom rounds; no unflagged self-kills. "Credited" = to a player by the knocker
rule. Board truth exists only for 22-55-47 (171) and 20-27-36 (118); the two older recordings end without one.

| Match | Rounds | Elims counted | Both names | Credited | NO_FEED_ROW | UNRESOLVED | NO_DROP | Knock rows with a weapon |
|---|---|---|---|---|---|---|---|---|
| 22-55-47 (12 players) | 25 / 25 | **171 = board** | 152 | 156 / 171 | 12 | 16 | 28 | 196 / 198 |
| 20-27-36 (11 players) | 19 / 19 | 119 (board 118) | 100 | 101 / 118 | 15 | 6 | 30 | 133 / 134 |
| 10-01 23-12-52 | 19 | 147 | 137 | 137 | 9 | 4 | 19 | 155 / 155 |
| 10-03 00-55-11 | 25 | 190 | 169 | 178 | 9 | 18 | 25 | 216 / 216 |

Knocks against the board's Knock Outs (22-55-47, the only match with that column): 175 of 186 (94%); eleven short
(RGOD 4, PARA 3, KG 2, one each Makjets, Khajwa, Wolverine); TrishaSingh one over; Deathwish's board value was not read.
Near-miss digit notes (seconds of video a digit was rejected at 0.65-0.80): digit 1 in all four matches (1.7-4.7 s);
digit 8 on 10-01 (1.7 s). 10-03: "kill feed not read for about 211 s of video (2082-2293 s): the match was over".

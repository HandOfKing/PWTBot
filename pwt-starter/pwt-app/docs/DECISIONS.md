# PWT decisions and dead ends

**Read this before proposing any change.** It exists because the same ideas kept coming back
after they had been decided or measured and rejected. If what you are about to suggest is in
"Tried and rejected", do not propose it again unless you have new evidence, and say what the
new evidence is.

- **Decided** entries change only when Chirag says so. Record the date and his words.
- **Rejected** entries carry the number that killed them. An idea without a number goes under
  "Open questions", not here.
- Append; do not rewrite history. If an entry is overturned, mark it `SUPERSEDED (date): why`
  and add the new entry below it.

Where this sits: `ARCHITECTURE.md` is the contract (invariants, definition of done). This file
is the memory of *why*. `METRICS.md` holds the numbers over time. `handoff/` holds the status.

---

## Decided (Chirag's calls)

| # | Date | Decision |
|---|---|---|
| D1 | 10-04, reaffirmed 10-07 | **Recorded video only.** No live screen capture, real-time analysis, auto-scroll or other input to the game, folder watching, or memory reading. The 10-02 live-capture design (DXcam at 12 fps, scroll assist) is SUPERSEDED; its code was deleted 10-07. |
| D2 | 10-05 | **The desktop app is in scope:** Tkinter, `app/main.py`, a thin window over `pwt/process.py`. Built and self-tested by `.github/workflows/build-windows.yml`. (On 10-04 he had said no GUI; 10-05 overturned that.) |
| D3 | 10-07 | **One version.** One layout (`gameloop-spectator-6v6-1080p`), one pipeline (`pwt/process.py`), one branch (`main`). No parallel paths, no second profile without his say-so and a measured profile. |
| D4 | 10-04 | **Target footage:** first-person spectator, round-based WoW room, 6v6, 1920x1080. The aerial arena TDM mode is out of scope. |
| D5 | 10-04 | **The kill feed cannot be enlarged** as a spectator (the option exists only for a player in the match). Plan for ~16 px text at 1080p. |
| D6 | 10-04 | Scope of the data: kill feed and eliminations first, plus round and match scoreboards. The Impact score is deferred until the data is right. |
| D7 | 10-07 | **Names are matched against the run's roster only** (the app's names box plus those players' aliases), never every name in the database. |
| D8 | 10-05 | **Eliminations are credited to the knocker**, not the finisher (schema v2). |
| D9 | 10-05 | **Default sampling is 12 fps**, and the result must not depend on `--fps`. The project instructions' "~4 fps" is SUPERSEDED: on Video_Project_9, 4 fps names 9 of 14 eliminations, 12 and 24 fps name 14. |
| D10 | 10-07 | Handoffs live in the repo (`docs/handoff/`), so Claude Code can read them. The copies in the claude.ai project are mirrors. (Added 10-08.) |
| D12 | 10-10 | **One Excel file per run, with match highlights.** `<recording> - PWT.xlsx` holds Scoreboard, Highlights, Events and Run log; the events CSV and the log file are gone (a run that finds no round still writes a log file). Highlights are built from KNOCKS only. A grenade knock is a Grenade, a Molotov knock is a Molotov (two roles). Car knocks are credited to the driver (the killer named on the row); Zone knocks go to nobody. (Chirag: "grenade kills should count as grenade and the Molotov kills should count as Molotov. And the car knocks should be credited to the driver.") Module `pwt/awards.py`. |
| D13 | 10-11 | **Highlights are per match, not per player, and pairs are ranked, not thresholded.** Dominating = the top 3 one-sided pairs of the match, Rival = the top 3 pairs that traded knocks most evenly; no "at least n knocks" rules for either. Grenadier, Molotov specialist, Driver, the weapon-class roles and Clutch have one holder per match. (Chirag: "let's do it per match ... top three in the game and for rival let's also do top three in the game instead of using like at least three times or at least two times".) Weapon-class roles go to the player with the most knocks with that class (Chirag confirmed 10-11; share only shown; at least 3 knocks, Claude's floor). |
| D14 | 10-11 | **Clutch = one player knocks down every enemy still alive (at least two) while their team has the same number alive or fewer.** 2v2 and two knocks, 3v3 and three, 2v3 or 1v3 and all three. One Clutch per match. (Chirag: "if it's a 2v2 and one guy knocks out two people then that would be a clutch, if it's 3v3 one guy knocks out three people ... or it's 1v3 and he knocks all three of them".) Replaces the "several knocks while outnumbered" rule of D12. |
| D15 | 10-13 | **Per-player stats are KNOCKS only: who a player knocked, and who knocked them.** Kills are left out because a knocked player may be revived. Two sheets, Players (knocks, times knocked, full rankings of who they knocked most and who knocked them most) and Head to head (one row per pair), join the workbook; Highlights is unchanged. (Chirag: "Let's forget about kills ... who you are knocking the most in the game ... and who knocked you the most".) Revives (his rule: knocked again later in the round, or never finished before the round ended) are computed in `pwt/playerstats.py` but NOT written to the workbook: he parked them the same day ("let's not touch revive for now"). |

## Measured rules (keep unless new numbers say otherwise)

| # | Rule | Evidence |
|---|---|---|
| M1 | Name match needs score ≥ 0.55 **and** a margin ≥ 0.15 over the runner-up (`readers/names.py`). | Margin 0.15 cost no yield (10-05). Threshold alone let `KGBSEIES` become BruceWayne at 0.33. |
| M2 | OCR text is glyph-folded (`0oOQDØø`, `6GgbB8Ee`, ...) before matching. | Plain difflib scored every reading of `KG696969` under 0.40. With the fold all three collapse onto it. |
| M3 | Every number on the HUD and boards is read with digit templates. | Tesseract: `52`→`2`, `12`→`2`, `11`→`1`, lone `0`s dropped. Templates: 0 WRONG on VP13. |
| M4 | A weapon is named only at template score ≥ 0.80, else `unknown`. | An M416 matched `weapon_UMP45` at 0.70 (the old 0.62 threshold labelled every kill UMP45). |
| M5 | Banner counts as up when ≥ 25% of each score box is team-coloured. | Point-sampling lost rounds 16–25 once blue's score reached "10" (one digit 0.61–0.83, "10" 0.38–0.40, hidden 0.00). |
| M6 | A board up ≥ 5 s, or still up at the end, is the match board. | Round boards are up ~2.9 s. |
| M7 | The Remaining counter decides how many died. A kill row that claims no drop is `NO_DROP` and not counted. | Second full-match run: 171 eliminations = the board total. Only safe while every Remaining digit reads (0 WRONG on VP13). |
| M8 | Drop alignment is same-round only, within `max_align_lag_s` (12 s in the profile). A row may precede its drop by up to 1 s (`COUNTER_AFTER_S`). Inside a backlog (oldest free death > 3.5 s, `BACKLOG_S`) oldest-first stays. | Without the round guard a round-2 row claimed a round-1 drop 40 s earlier. 8 s left a VP9 row unaligned (backlog reached 8.9 s). |
| M9 | Two feed-row detectors exist: the dark-panel detector and the whole-box ink/text search (A12). Ink rows need a matched icon or a weapon-sized blob. | Panel alone: 3/16 → 23/37 over moving scenery, but missed round-20 rows whose panel starts at x=107. A12: r20 clip 4/5 named (was 0/4). |
| M10 | While the round-end dim is up the feed text mask uses a FIXED threshold (`feed.dim_mask_thr` = 22), not the relative one. | The DRAW/VICTORY banner stripes lift the 99.8th percentile of the top-hat to ~97, so the relative threshold (~44) sat above the greyed feed text (~25-40) and hid every wipe row printed during the dim. Dimmed samples with a row found: 3-8% -> 80-97% (5 wipes). 22-55-47: NO_FEED_ROW 22 -> 12, both names 139 -> 151, credited 144 -> 155 of 171. Cost: NO_DROP 26 -> 29 (flagged, not counted). VP9 4 fps named 9 -> 13 of 14. (2026-10-09, Chirag: keep) |
| M11 | A scoreboard detected again within `BOARD_REAPPEAR_S` (2.0 s) of one closing is its fade-out, not a new board. | 20-27-36 round 8's board fired again for 0.1 s and 10-03 a board dipped for 0.5 s: each made a phantom round (0 s long). Rounds 20 -> 19 (board scores 14 + 5 = 19) and 26 -> 25. The shortest real round seen is 19 s. |
| M12 | The feed is not read once the match is over (`Engine._match_over`): the last board closed more than 25 s ago AND since then no round banner, no Remaining drop and no Remaining reset. The skipped spans are written in the run notes. (2026-10-09, Chirag: skip them; "the game's default results screen, I don't care about it") | After the last board 10-03 runs on for ~230 s on the results screen (frozen scene, player list, in-world name tags): 700 of 2750 samples read as "feed rows", 37 junk rows, NO_DROP 63 -> 25. In all 2785 samples there was no banner. A first version (25 s after the last board, nothing else) could have switched off a round whose banner and reset were both missed (reviewer); a banner, a drop or a reset now turns the feed back on. Final run: 10-03 note "kill feed not read for about 211 s of video (2082-2293 s)", no change on the other three matches. |
| M13 | A Remaining digit under the 0.80 template score is rejected, but a score in 0.65-0.80 is counted as a "near miss" and the run notes name the digit at 20+ (`DigitReader.near_miss`). | 22-55-47 round 15: a "3" scored 0.78-0.81 against its single template and was unreadable on 41 of 46 frames, so the round's last death was lost (170 vs 171). Do NOT lower 0.80: the runner-up for that glyph was a 9 at 0.70 (margin 0.07-0.12). Fix = more templates (9 added; unreadable live frames 10.8% -> 0.5% on 20-27-36, 315 -> 18 on 22-55-47, 0 WRONG). |
| M14 | A knock row's gun is read by window search of 28 per-gun templates (`readers/weapons.py`, `templates/weapons/`): named at score >= 0.80 AND >= 0.05 ahead of the next gun, else empty. Knock rows only. (2026-10-09, Chirag: knocks only) | From the best image of each row: 697 of 703 knock rows named (was 6%, UMP45 only). In the full runs, with the tracker voting over every sighting of a row: 196/198, 133/134, 155/155 and 216/216 knock rows have a weapon. Held-out matches 220 of 225 agree with the labels; the 5 that do not are label errors in my groups. Every correct reading had a margin >= 0.08, so the 0.05 rule is free. The weapon column does not change with --fps (VP9 at 4/12/24). The ink-gap cut-out was tried first and left 109 of 703 rows without an icon (thin barrels split into pieces): rejected, see weapons.md. Six guns (G36C, ACE32, MP5K, S1897, Molotov, Car) rest on 1-4 sightings each. |
| M15 | A recording whose game picture is the reference size (`game_area`, 1728x972) but sits elsewhere in the frame is shifted back by whole pixels before the layout check and the replay (`capture/placement.py`; `placement` in the profile, `templates/layout_anchor.png`). The shift comes from the "Remaining" label found at one place on >= 3 of 12 sampled frames (score >= 0.75) and on most frames it was found on; it is taken only when the measured game picture (the part of the frame that changes) is the profile's size at the shifted place within 4 px, wholly inside a 1920x1080 frame. A HUD found elsewhere that fails any of these, or found at two places (the picture moved during the recording), is a layout-check blocker. Reference recordings find the label at +0,+0 and take the old path untouched. Asked for by Chirag 10-17 ("is it possible for you to fix this issue?"); NOT yet confirmed by him as a decision. | 2026-10-17 00-54-26 (8v7, 23.976 fps) has the game alone at the frame's corner, 1728x972: HUD landmarks register at exactly -100,-53 at opposite corners (0.99, 0.93; scale 1); label found at -100,-53 on 11 of 12 frames, picture measures 1729x974 at 0,0 (compression bleeds 1-2 px). Layout check FAIL (banner 0%, Remaining 0%) -> PASS (banner 79%, Remaining 92%, names 28/28), the same Remaining rate as VP9 (92%). Full run: 25 rounds, 245 eliminations = the board's 245 (METRICS 10-17). Label scores: true 0.82-0.98, best false 0.54; on a frame scaled by 0.97-1.03 it still scores 0.69-0.77, hence the size check. +0,+0 on VP9, VP13, 2026-10-01 23-12-52 and the two 2026-10-01 22-xx recordings in Downloads; 22-55-47, 20-27-36 and 10-03 could not be checked (the files are gone from `Spectator Videos`). |

## Tried and rejected — do not propose again without new evidence

| # | Idea | Why it died (number) |
|---|---|---|
| R1 | `if not icons: continue` — icons gate row acceptance. | A real recording went from 30 kills to **0**. Icons classify; they never gate (ARCHITECTURE invariant 2). |
| R2 | Roster as a membership test (is the OCR string in the list?). | **0%** by construction: OCR never reads these names exactly. |
| R3 | Matching feed names against every player in the DB. | 179 vs **312** of 385 rows named with the run's roster (stored misreads break the margin rule). |
| R4 | Two roster entries for one person (old + new spelling). | Resolution **68% → 17%**. Use `pwt rename OLD NEW` (alias). |
| R5 | Background normalisation / scene-clutter subtraction / waiting for a clean background behind the feed. | No relationship: rows over textured backgrounds resolved **70%**, over flat ones **49%**. Dead end. |
| R6 | Text-density row finder as the only detector over moving scenery. | **3/16** rows vs 23/37 with the panel detector. (Kept as the second path, see M9.) |
| R7 | Delaying OCR of ink-found rows until they have slid in (0.75 s). | Fixed VP9 36.2 s but made VP13 round-15's Trisha row unreadable (`KGGSE9SS` fell under threshold). |
| R8 | Tesseract for digits, any preprocessing. | See M3. Widening the crop does not fix the bare-stroke `1`. |
| R9 | OCR a row only on its first sighting. | Rows slide in over ~2 frames; the first reading is often half-rendered. Vote across sightings. |
| R10 | A partial character-template library for names. | Forbidden (invariant 4): `ocr_mask` abandons Tesseract once any library exists, so partial coverage is worse than none. |
| R11 | Enlarging the kill feed. | Not available to a spectator (D5). |
| R12 | Live capture at 12 fps with DXcam; auto-scroll on boards. | Out of scope (D1). |
| R13 | Six replays in parallel in the 2-CPU cloud container. | They crawled and were killed. Run replays one at a time. |
| R14 | One parameter set for two different footage layouts (the old 2v2 clip and the 6v6 one). | The 2v2 rows sit close enough that the panel detector merges them; 6v6 needs it. One profile per geometry (invariant 5). |
| R15 | `harvest_remaining_digits.py` saving whatever the worst-read frame cuts out, unchecked. | First harvest on 22-55-47 saved 3 non-digit blobs (`6_4`, `6_5`, `6_6`: the whole box when a bright background broke the cut-out) and the check showed 3 WRONG (5 read as 6, 4 read as 6). Deleted. Look at every harvested glyph before keeping it. |
| R16 | Rescaling a game picture of another size onto the reference placement (crop the game area, resize to 1728x972, paste at x=100, y=53). | 2026-10-15 20-40-55 (game ~1780x998 at y=59, 23.976 fps): the layout check passes, but the Remaining counter reads on 64% (INTER_AREA / INTER_LINEAR) or 82% (INTER_CUBIC) of frames against 92% on a native recording, and the digit templates are what decide every elimination count (M7). Rescaling to 1920x1080 instead: Remaining 0%. Rejected for accuracy, not because the guard stops it (64-82% clears the guard's 25%): M15 refuses a picture whose measured size differs. Record at the native size. |

## Open questions (need footage or Chirag)

- Weapons: 28 guns are in the library for KNOCK rows (docs/weapons.md). Kill and tombstone rows still read only UMP45, the headshot crosshair is not read, and AKM / S12K / ACE32 / Beryl M762 are close at ~16 px: Chirag's eye on a check sheet is the only ground truth for those.
- The game's results screen (after the last board; "View Statistics" shows the full table) lists each player's eliminations, assists and damage. It could be the missing truth for recordings that end without the final board (2026-10-01, 2026-10-03). Not tried.
- Banner score digits: only 0 and 1. VP13 shows 5, 9, 10. Until then round winners are not read.
- Character templates for names (`chars_feed/`): `chars.py` and `tools/harvest_chars.py` are written; no library yet. Must be complete before use (R10).
- Does each helmet slot map to a fixed player? Is blue always team 1?
- Does the feed show revive lines? Which icons exist for grenade, vehicle, zone, fall, teamkill?
- Who records now and on which machine (GameLoop was uninstalled from the laptop on 10-07; OBS on the desktop PC shows no recording in its logs of 09-30 and 10-13, checked 10-16, while the 10-15 and 10-17 MKVs exist, so those came from another OBS)? Any new machine or resolution must pass the layout guard; do not loosen the guard to make it pass. (Corrected 10-17: a game picture of the reference size at another place in the frame is now shifted back before the guard runs, M15; the guard's thresholds are unchanged.)
- 2026-10-17 00-54-26 is 8v7 (15 players). The profile has helmet positions for 6 a side only, so eliminations there get no helmet team (as on 20-27-36, 5v6); counts still come from Remaining. Bigger teams would need their positions measured (D4 says 6v6).

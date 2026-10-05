# PWT: Kill-feed reference

Source: test clip `Video_Project_7.mp4`, recorded 2026-10-01. It is a 4-player WoW room, round-based ("ROUND 01/29"), 2 v 2.

## Recording
- 21.5 s, 1920×1080, 30 fps, H.264 at about 15 Mbps, MP4. 30 fps is plenty, since we sample at 4 fps.
- GameLoop was **windowed**. The game area is about x 100–1828, y 53–1025, so the HUD is scaled to about 90%.
  - Feed text is only about 12 px tall.
  - All coordinates below are for this windowed layout. **Recalibrate after switching GameLoop to fullscreen.**
- The spectator camera follows one player. The bottom-centre panel shows only that player's stats.

## HUD regions (windowed layout)

| Region | Box (x0, y0, x1, y1) | Notes |
|---|---|---|
| Kill feed | 100, 215, 760, 480 | Rows left-aligned at x≈118. The newest row enters the bottom slot (y≈455); older rows shift up about 46 px. |
| Remaining (players alive, whole lobby) | digit at ~186, 60, 206, 88 | **The fastest signal.** Drops on every elimination at the true time. Knocks don't change it. |
| Team / Team Eliminations / per-player elims | 100, 55, 330, 205 | Updated about 0.8 s after Remaining. Shows only the spectated player's team. |
| Round banner (score, ROUND nn/29, countdown from 2:00) | top centre, ~650–1270, 55–130 | Visible only while a round is live. Hidden during the pre-round countdown and from about 0.25 s after the round is won (the compass replaces it). Visibility test: both score boxes are solidly blue / red. |
| Banner helmets: one per player, white = alive, gray = dead | blue at (666,76), (710,76); red at (1218,76), (1262,76) for 2v2 | **Tells which team lost a player**, about 0.2 s after Remaining drops. Knocked players stay white. Positions change with team size, so recalibrate for 4v4–8v8. |
| Banner round score (blue / red) | blue digit ~772–808, red ~1118–1156; y 66–116 | Ticks up at the round's end, on the same frame the helmets turn gray (blue 0→1 at 13.46 s). Gives the round winner. |
| Zone timer + stage | 1655, 240, 1828, 268 | Always visible. |
| Round scoreboard | full screen, after each round | Shows Rank, Team, Wins, Player, 4 columns all labelled "No. of Eliminations", and Damage Dealt. |

## Feed grammar seen so far

| Row layout | Meaning |
|---|---|
| killer · weapon icon · knock icon (crawling figure) · victim | Knock |
| killer · weapon icon · victim | Kill. The last survivor of a team dies outright, with no knock. |
| killer · tombstone icon · victim | Knocked player eliminated because their team was wiped. Credited to the killer and counts as an elimination. |

Still to capture:
- headshot
- grenade / molotov
- vehicle
- zone death
- fall damage
- drowning
- teamkill
- revive (if shown)
- a "finish" on a knocked player while their teammates are still alive

Weapon icons so far: UMP45.

Player names use stylised characters (TheWølverine, RGODxEMPERØR). Fuzzy-match the OCR output to the roster; never trust raw OCR.

## Timing behaviour (important)
- A new row slides in over about 2 frames and stays about 3.5 s.
- **Feed time is not event time.** New rows were posted about 2 s apart (12.50, 14.58, 16.75 s), even though the last two events happened together at 13.25 s. That looks like a pacing queue, so in a big fight the backlog grows by about 2 s per kill. One open question: is it really a ~2 s pacing rule, or a 2-row cap? A busier clip will settle it.
- For the Makjets69 kill, the same moment shows up at four different times:

| Signal | Time on video |
|---|---|
| Remaining 4→3→2 (true time) | 13.25–13.29 s |
| Both red helmets turn gray, and blue round score 0→1 | 13.46 s |
| Banner hides (round over) | 13.71 s |
| Team Eliminations 0→2 | 14.08 s |
| Feed: tombstone row | 14.58 s |
| Feed: kill row | 16.75 s |

- Feed order within a burst can differ from causal order.
- **Timing rule (implemented in counters.py):** the frame index is the master clock.
  1. Each drop in Remaining is one elimination at its true time.
  2. Each drop takes its team from the next helmet that turns gray within 1 s.
  3. Each feed elimination row (kill or tombstone), in feed order, takes the earliest unused drop that came before it and matches its victim's team. The team map comes from the round scoreboard.
  4. Knocks change neither Remaining nor the helmets, so they keep the feed time and are marked approximate.
- 4 fps edge case: when a round's final death happens, the helmets turn gray only about 0.25 s before the banner hides, so 4 fps may catch just one gray frame. The code accepts a single gray read if the banner disappears next.
- To verify:
  - Does each helmet slot map to a fixed player? That needs a clip where teammates die at different times.
  - Is blue always team 1, or always the spectated player's team?
- No setting found (PUBG Mobile or GameLoop) changes feed length, pacing, or the round-end screen. Modding the client would break the terms of service and risk a ban.
- At round end the screen dims to about 20% brightness for about 3 s while feed rows keep arriving. The extractor uses a local-contrast (top-hat) mask so it still reads them. The dim also marks the round boundary.

## Ground truth for the test clip (from the 24 fps review)

| Time on video (s) | Event |
|---|---|
| 0–2 | Round 1 countdown. Team 1: TheWølverine, PARAbloodthirs. Team 2: RGODxEMPERØR, Makjets69. |
| 12.50 | Feed: TheWølverine [UMP45] knocks RGODxEMPERØR |
| 13.25–13.29 | Remaining 4→3→2: Makjets69 killed and RGODxEMPERØR (knocked) eliminated. This is the true time. |
| 14.08 | Team Eliminations 0→2 (TheWølverine 2) |
| 14.58 | Feed: TheWølverine [tombstone] RGODxEMPERØR |
| 16.75 | Feed: TheWølverine [UMP45] Makjets69. Posted 3.5 s after the true time. |
| ~18.5 | Round 1 scoreboard: TheWølverine 2 elims, 200 dmg. RGODxEMPERØR 0 elims, 52 dmg. Others 0 / 0. |

Reconciliation: the feed gives 2 eliminations for TheWølverine (tombstone + kill), which matches the scoreboard. Knocks are not eliminations.

## Prototype status (killfeed.py v0.1 + counters.py v0.1)
- 4 fps aligned output for the test clip:
  - The two eliminations get a true time of 13.25 s, from the Remaining drop plus the red helmets.
  - The feed was 1.5 s late (tombstone row) and 3.5 s late (Makjets69 kill row).
  - The knock keeps its feed time of 12.50 s.
- Pipeline:
  1. Crop the feed.
  2. Apply the top-hat white mask.
  3. Find rows, using left alignment as a filter.
  4. Slide icon templates (UMP45, knock, tombstone) along each row.
  5. Treat text left of the first icon as the killer and text right of the last icon as the victim.
  6. OCR both with tesseract, then fuzzy-match to the roster.
  7. Dedupe by row key and persistence. A row must be seen for at least 0.5 s, and both names must match the roster with a score of at least 0.5.
- Results:
  - 4 fps found the same 3 events as 24 fps, within ±0.25 s. Each row was seen 6–14 times.
  - Raw OCR is rough ("TheWalverine", "REDOxEMPEROR", "Makpets6d"); the roster match fixes it.
  - Runs at about 0.5× real time unoptimised.
- Scoreboard OCR test:
  - Names read correctly.
  - Lone digits are unreliable (some 0s were missed, and 52 was read as 2). The next step is digit templates.
- Templates are cut from the clip at frame 357 (24 fps numbering, about 14.83 s):
  - UMP45: x 214–248, y 400–418
  - knock: x 271–299, y 400–418
  - tombstone: x 225–241, y 444–462
  - Each is padded by 3 px and saved as a top-hat mask PNG.

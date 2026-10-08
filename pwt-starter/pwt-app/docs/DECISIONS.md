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

## Open questions (need footage or Chirag)

- Weapon templates: only UMP45 exists. AKM-type rifles, M416 and a headshot crosshair are visible in Video_Project_13.
- Banner score digits: only 0 and 1. VP13 shows 5, 9, 10. Until then round winners are not read.
- Character templates for names (`chars_feed/`): `chars.py` and `tools/harvest_chars.py` are written; no library yet. Must be complete before use (R10).
- Does each helmet slot map to a fixed player? Is blue always team 1?
- Does the feed show revive lines? Which icons exist for grenade, vehicle, zone, fall, teamkill?
- Who records now and on which machine (GameLoop was uninstalled from the laptop on 10-07)? Any new machine or resolution must pass the layout guard; do not loosen the guard to make it pass.

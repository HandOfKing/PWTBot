---
name: harvest-templates
description: Add digit or icon templates to PWT from a clip with known values — Remaining digits, scoreboard digits, banner score digits, weapon icons — with a held-out 0 WRONG check. Use when a number reads blank, a weapon reads "unknown", or a known gap (banner digits 2-10, AKM/M416/headshot icons) is being closed. Delegates the measuring to the pwt-calibrator agent.
argument-hint: "<remaining|board|banner|weapon> <clip>"
---

# Harvest templates: $ARGUMENTS

Templates are the only way numbers get read here (DECISIONS M3: tesseract misreads this font).
A wrong template is worse than a missing one: a misread Remaining digit is a phantom or lost
elimination.

1. **Truth first.** Build a truth file from frames you looked at, in the existing format:
   - Remaining: `start_s,end_s,value` like `tests/fixtures/remaining_vp13.csv`. Leave a margin at the
     edges of each interval; the digit animates when it changes.
   - Board: like `tests/fixtures/match_board_vp11.csv`.
   Show Chirag the truth file (or the frames behind it) before harvesting if any value is uncertain.
2. **Harvest with a hold-out.** Use the tool, with `--harvest-before <s>` so the rest of the clip
   stays unseen:
   - `python tools/harvest_remaining_digits.py <clip> <truth.csv> --harvest-before <s>`
   - `python tools/harvest_board_digits.py <clip> <truth.csv> --at 1,3` (harvests only from the
     seconds listed in `--at`; check on the others and on a different board)
   Banner score and weapon icons have no tool yet: hand to the `pwt-calibrator` agent, which cuts
   from ≥2 sightings and tests against every other icon.
3. **Check.** `--check-only` on the held-out part **and** on a different clip. Required: 0 WRONG.
   Report correct / blank / WRONG counts. Any WRONG → delete the templates just added and stop.
4. **Weapons:** the new icon must not match any other weapon at ≥ 0.80 (`weapon_thresh`). Report
   the best wrong-weapon score. Do not lower `weapon_thresh` (M4).
5. Add or extend a test in `tests/test_readers.py` with a fixture frame showing the new value.
6. Run `/measure`, then record the result in `docs/METRICS.md` and remove the gap from
   CLAUDE.md "Known gaps" / DECISIONS "Open questions" if it is closed.

Never: hand-edit a template image, harvest from the same frames you check on, or build a
partial `chars_feed/` name library (invariant 4).

---
name: experiment
description: Make one change to PWT that could move accuracy, the disciplined way — measure a baseline, change one thing, measure again, keep or revert, and record the outcome in DECISIONS or METRICS either way. Use for any change to readers, names, alignment, thresholds, windows, detectors, templates or the profile, and whenever trying an idea to fix flagged rows.
argument-hint: "[what to try]"
---

# Experiment: $ARGUMENTS

One idea per experiment. If you are tempted to change two things, run two experiments.

## 1. Check it is not a repeat
Search `docs/DECISIONS.md` (Tried and rejected, Measured rules) and the newest handoff for this
idea or a close variant. If it is there, stop and tell Chirag: "R# says <number>. What is
different now?" Continue only with a stated new reason.

## 2. Write the hypothesis (3 lines, in the reply)
- **Change:** the one thing, and the file(s).
- **Expect:** which number moves, in which direction, on which clip.
- **Guard:** which numbers must not get worse (always: VP9 14 elims at fps 4/12/24, tests pass,
  no unflagged self-kills; plus anything this change could plausibly break — e.g. VP13 rounds).

## 3. Baseline
Measure the target number and the guard numbers **before** changing anything, on the current
commit. Use the `pwt-verifier` agent for the standard set; measure the target number yourself
with a short script if it is not standard. Write the numbers down in the reply.

## 4. Change
The smallest change that tests the idea. No refactors, renames or cleanups in the same change.
Constants that depend on the footage go in the profile JSON with a note; code constants get a
comment with the measurement that set them.

## 5. Measure again
Same commands, same clips, same fps. Report before → after for target and every guard.

## 6. Decide
- **Target up, guards hold:** keep. Add the numbers to `docs/METRICS.md`; if it sets a rule others
  must not undo, add a row to DECISIONS "Measured rules".
- **Target flat or down, or any guard worse:** revert the change (`git checkout -- <files>` or
  `git restore`), and add a row to DECISIONS "Tried and rejected" with the numbers — e.g.
  "R15 | Delay OCR 0.75 s | fixed VP9 36.2 s, broke VP13 r15 Trisha row". A rejected experiment
  recorded is a success; an unrecorded one will be tried again next week.
- **Mixed (helps one clip, hurts another):** do not keep it. Record it as rejected with both
  numbers, and say what would have to be true for it to work.

## 7. Before committing
Run the `pwt-reviewer` agent on the diff. Commit message: what changed and the before → after
numbers.

---
name: measure
description: Run PWT's definition-of-done checks (tests, VP9 eliminations at fps 4/12/24, determinism, KG696969, VP13 Remaining digits) and log the numbers to docs/METRICS.md. Use before a commit, before a handoff, or when Chirag asks "is it working" or "did that help".
---

# Measure

Delegate to the `pwt-verifier` agent: "Run the full definition-of-done check on the current tree
and append the results to docs/METRICS.md."

When it returns:
- Relay its report to Chirag as is, numbers unchanged, with its VERDICT on the first line.
- `INCOMPLETE` because a clip is missing: name the clip and where it was last seen (the handoff
  says `C:\Users\Chirag\Desktop\PWT Videos`). Do not call the work done.
- `FAIL`: say which check failed and stop. Do not start fixing in the same breath unless Chirag
  asks; the fix is an `/experiment`.

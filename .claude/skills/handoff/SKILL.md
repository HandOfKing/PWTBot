---
name: handoff
description: End a PWT session by writing docs/handoff/HANDOFF-<date>.md — what changed with commits and numbers, what was tried and rejected, and the numbered next steps — and updating DECISIONS and METRICS. Use when Chirag says "wrap up", "write the handoff", "we're done for today", or before a session runs out of context.
---

# Write the handoff

1. Gather facts, don't recall them: `git log --oneline <last handoff's HEAD>..HEAD`, `git status`,
   the METRICS.md rows added this session, any DECISIONS rows added this session.
2. If nothing was measured this session, run `/measure` first. A handoff without numbers is not done.
3. Make sure every experiment this session is in DECISIONS (kept → Measured rules; reverted →
   Tried and rejected) or METRICS. Add what is missing now.
4. Write `docs/handoff/HANDOFF-<YYYY-MM-DD>.md` (add `-2` if one exists for today). Keep it under
   ~80 lines, in this shape:

   ```
   # PWT handoff — <date> <time>
   Read docs/ARCHITECTURE.md and docs/DECISIONS.md first. Supersedes HANDOFF-<previous>.

   ## 1. State
   Branch main, HEAD <sha>. Build: <green/red/unknown>. Tests: <n ok / n skip / n FAIL>.

   ## 2. What changed (commit → effect, with numbers)
   ## 3. Tried and rejected this session (also in DECISIONS)
   ## 4. Next (numbered, in order; each with how to check it is done)
   ## 5. Needs Chirag (recordings, decisions, things only he can run)
   ```
   Do not repeat content already in ARCHITECTURE or DECISIONS; link to it.
5. If anything in CLAUDE.md, RUNBOOK.md or an older doc is now wrong, correct it in place and list
   the correction in the handoff.
6. Commit the docs. Tell Chirag in two or three sentences: the headline number, the next step,
   and what he needs to do. Offer to mirror the handoff into the claude.ai project if he works
   from there too.

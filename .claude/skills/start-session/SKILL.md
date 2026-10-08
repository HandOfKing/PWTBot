---
name: start-session
description: Start a PWT work session — read the contract, the decisions ledger and the newest handoff, check the repo state, and state the next step before touching code. Use at the start of every session, or when Chirag says "let's continue", "where were we", or "pick up from last time".
---

# Start a PWT session

Do these in order and do not write code until step 5 is answered.

1. `cd pwt-starter/pwt-app`. Run `git status --short`, `git branch --show-current`, `git log --oneline -5`.
   - Not on `main`? Say so. There is one branch (DECISIONS D3).
   - Uncommitted changes? List them and ask whether they are wanted before building on them.
2. Read in full: `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, and the newest file in `docs/handoff/`
   (highest date in the name). Skim the last rows of `docs/METRICS.md`.
3. List which clips exist in `clips/` (`Video_Project_9.mp4`, `Video_Project_13.mp4` are needed for
   the benchmarks). Missing ones mean benchmarks will be NOT RUN, so say that now.
4. Reply to Chirag with, at most, ten lines:
   - **Where we are:** commit, last measured numbers (from METRICS.md, with dates).
   - **Next step:** the handoff's first unfinished numbered "Next" item, quoted.
   - **What I need from you:** a recording, a clip, a decision — or "nothing".
   - **Blocked?** If the next step cannot be done here (for example it needs Chirag to run the app
     on his laptop), say so plainly. Do not silently substitute a different step (ARCHITECTURE §8).
5. If Chirag's message asks for something else, check it against DECISIONS first:
   - In "Decided"? Follow it. Contradicts it? Point to the entry and ask.
   - In "Tried and rejected"? Quote the entry and its number and ask what is new.
   - Neither? Proceed, using `/experiment` if it could move accuracy.

Keep the reply short. Chirag dictates by voice; he wants the answer, not a recap of the docs.

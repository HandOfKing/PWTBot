# PWT architecture

The stable contract. Current *status* lives in `claude/HANDOFF-*.md`; this file
describes what the system **is** and the rules it must obey. It should change
rarely. If a session proposes something that contradicts this file, the file
wins unless Chirag says otherwise.

---

## 1. Goal

One command. An OBS recording of a PUBG Mobile WoW custom room goes in; a table
of eliminations comes out — who killed whom, when, with what, and how confident
we are. Later: a per-player "Impact" score.

```
python -m pwt replay match.mkv --profile <name> --csv events.csv
```

Eventually the same pipeline behind a desktop app a non-technical friend can run
with nothing installed.

---

## 2. Scope

**In:** recorded video only. Offline. Windows 10/11.

**Out, permanently:** live screen capture, real-time analysis, auto-scroll or any
input sent to the game, folder watching, reading game memory.

`pwt/capture/sources.py:LiveScreenSource` and `pwt live` are legacy. They exist;
they are unsupported; do not extend them. `FileReplaySource` is the only path.

**Target footage:** first-person **spectator**, round-based, 6v6, GameLoop
windowed, 1080p. A second "aerial arena TDM" mode was investigated and dropped.

---

## 3. Pipeline

Each stage has one job and a defined output. Stages do not reach around each other.

```
video file
   │
   ├─ 0  PROFILE GUARD      readers/hud.py
   │     Sample ~30 frames. Confirm the profile's HUD landmarks are where it
   │     claims. REFUSE TO RUN otherwise. Without this, a mismatched profile
   │     runs to completion and emits plausible, wrong data.
   │
   ├─ 1  DECODE             capture/sources.py:FileReplaySource
   │     → (t, BGR frame) at --fps (default 12). Streams; never loads the whole video.
   │     t = sample index / fps. This is the master clock.
   │
   ├─ 2  SCREEN STATE       readers/screens.py:ScreenReader
   │     → live | dimmed | scoreboard | other
   │
   ├─ 3  READERS (per frame, parallel concerns)
   │     ├ readers/feed.py      → feed rows (panel or text detection per profile)
   │     ├ readers/counters.py  → Remaining, helmets, banner score
   │     └ readers/screens.py   → end-of-round scoreboard table
   │
   ├─ 4  LINE TRACKING      readers/feed.py:LineTracker, Line.vote
   │     One feed row is seen across many frames. Group the sightings, OCR
   │     several, take the modal reading. A row slides in over ~2 frames, so the
   │     first sighting is often half-rendered.
   │
   ├─ 5  NAME RESOLUTION    readers/names.py
   │     OCR text → NFKC + transliterate → glyph-fold → nearest roster name,
   │     subject to threshold AND margin.
   │
   ├─ 6  ALIGNMENT          engine/engine.py:_align
   │     Eliminations take their true time from a Remaining drop, teamed by the
   │     helmet that greys. Knocks keep feed time, marked approximate.
   │
   ├─ 7  RECONCILIATION     engine/engine.py
   │     Feed counts vs scoreboard counts. Disagreement is reported, not resolved.
   │
   ├─ 8  PERSISTENCE        db.py:LiveMatch  (SQLite, committed as it goes)
   │
   └─ 9  OUTPUT             CSV · Excel · (planned) review GUI
```

### Three independent signals
The design's core idea: **kill feed**, **Remaining counter** and **scoreboard
totals** are measured separately and cross-checked. Where they agree, a row is
effectively certain. Where they disagree, that disagreement is the output's most
valuable content — it tells you exactly which rows to doubt. Never tune one
signal to silence a disagreement with another.

---

## 4. Invariants

These are not preferences. Breaking any one has already cost real accuracy.

1. **Flag, never guess.** Every row is emitted. One that cannot be resolved
   carries `flag=UNRESOLVED` and its raw OCR. Never drop a row; never assert a
   name the evidence does not support.
2. **Icons classify; they never gate.** `templates/icons/` holds a handful of
   weapons. A row matching no icon is still a valid feed row. Reinstating
   `if not icons: continue` took a real recording from 30 kills to **0**.
   *Narrow exception (2026-10-05):* the two paths that only ADD rows the main
   detector never saw -- the A11 in-run text search at round ends and short
   lines (on screen < min_seen_s) -- require an icon. Without it they mostly
   found in-world nameplates. They can never remove a row the main path found.
3. **The roster finds names; it does not validate them.** OCR never reads these
   names correctly. Fuzzy-match every token to the nearest roster entry. Using
   the roster as a membership test gives 0%.
4. **Never ship a partial template library.** `CharReader.ready` counts entries,
   not coverage, and `ocr_mask` abandons Tesseract the moment it is true. A
   library covering some characters is worse than none.
5. **Coordinates live in profile JSON, never in code.** One profile per footage
   geometry. No single parameter set serves two different recordings — do not
   search for one.
6. **The sampled frame index is the master clock** (t = index / fps). The
   in-game timer is a cross-check. The table must not depend on the sampling
   rate: anything timed in frames instead of video seconds breaks this. Feed time is not event time; it lags up to 3.5 s and can arrive
   out of causal order.
7. **Read pixels only.** Never touch the game's memory, files or network.
8. **Mismatched input must fail loudly.** Silent wrong output is the worst
   possible outcome and the one this system is most prone to.
9. **A renamed player is an alias, never a second roster entry.** Two entries for
   one person fold alike, the margin rule refuses both, and yield collapses.

---

## 5. Contracts between stages

| Stage | Produces | Guarantee |
|---|---|---|
| Decode | `(t, frame)` | `t` is exact; frames never dropped on replay |
| Feed | `Row` | has `row_mask`, `icons`, `icon_scores`; icons may be empty |
| Line tracking | `Line` | ≥1 OCR reading; `vote()` returns modal `(killer, victim, type)` |
| Names | `(name, score)` | `None` unless score ≥ threshold **and** margin over runner-up |
| Counters | `int` or `None` | `None` means unreadable — never a guessed number |
| Align | `true_time_s`, `time_source` | `remaining_drop[+helmet]` = true; `feed` = approximate |

---

## 6. Definition of done

A change is acceptable only if all of these hold:

- `python tests/run_all.py` — all pass.
- **Elimination count** on `Video_Project_9.mp4`: events of type `kill` +
  `eliminated_knocked` equal the Remaining counter's 14 drops at `--fps` 4, 12
  and 24, and the event CSV is identical when the run is repeated.
- **6v6 benchmark** on `Video_Project_9.mp4`: ≥20 feed rows resolve both names,
  and `KG696969` is among the names read correctly.
- *(The 2v2 regression on `Video_Project_7.mp4` was dropped 2026-10-05 at
  Chirag's call: that clip is not the footage the tool is for. The `text`
  detector and its profile stay, untested.)*
- No new unflagged row whose killer equals its victim.
- Any claim about accuracy is **measured and stated with its number**, not argued.

---

## 7. Roles of the documents

| File | Role | Changes |
|---|---|---|
| `docs/ARCHITECTURE.md` | this file — the contract | rarely |
| `CLAUDE.md` | what a coding session must know on line 1 | rarely |
| `docs/RUNBOOK.md` | how to run it | when the CLI changes |
| `docs/roster.md` | exact player spellings | when players change |
| `docs/kill-feed-reference.md` | the 2v2 mode; the regression test | rarely |
| `claude/HANDOFF-*.md` (project) | current status, what's left | every session |
| `claude/spectator-feed-reference.md` (project) | 6v6 HUD calibration + evidence | when recalibrated |

Anything not in this table is historical. Do not build from it.

---

## 8. Working agreement for sessions

- Read `CLAUDE.md`, this file, and the newest `HANDOFF-*` before proposing work.
- Follow the handoff's numbered next steps in order. If a step turns out to be
  blocked, **say so and stop** — do not substitute a different step silently.
- Measure before claiming. "It's better" without a number is not a result.
- Prefer the smallest change that satisfies the goal. This codebase has been
  broken more by helpful rewrites than by missing features.
- When an earlier document is wrong, correct it in place and say what changed.

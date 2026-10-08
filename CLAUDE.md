# PWTBot

All work happens in `pwt-starter/pwt-app/`. Run commands from there (`cd pwt-starter/pwt-app`).

@pwt-starter/pwt-app/CLAUDE.md

## How a session runs here

1. Start with `/start-session`. It reads the contract, the decisions ledger and the newest handoff,
   and states the next step before any code is touched.
2. Every change that could move accuracy goes through `/experiment`: baseline number, one change,
   new number, keep or revert, and an entry in `docs/DECISIONS.md` or `docs/METRICS.md` either way.
3. Before a commit: the `pwt-verifier` agent (tests + benchmarks, with numbers) and the
   `pwt-reviewer` agent (diff against the invariants and the rejected-ideas list).
4. End with `/handoff`, which writes `docs/handoff/HANDOFF-<date>.md`.

## Agents (in `.claude/agents/`)

| Agent | Job | Never |
|---|---|---|
| `pwt-verifier` | Runs tests and the definition-of-done benchmarks; reports numbers and skips | edits code; calls a skipped test a pass |
| `pwt-reviewer` | Reviews a diff against ARCHITECTURE invariants, DECISIONS and scope | edits anything; approves without reading the diff |
| `pwt-calibrator` | HUD coordinates, profile JSON, digit/icon templates from real frames | touches readers/engine logic; guesses coordinates |
| `pwt-run-analyst` | Reads a full-match result (xlsx/csv/log) and explains every gap vs the board | changes code; tunes anything |

The main session writes the code. Agents check, measure, calibrate and diagnose.

## Ask Chirag before

- changing scope (anything in DECISIONS "Decided"), adding a second layout/profile, or a dependency
- editing `docs/ARCHITECTURE.md`, a truth fixture (`tests/fixtures/*.csv`), the schema, or `docs/roster.md`
- deleting anything under `pwt/templates/`, `tests/fixtures/`, or `docs/`

The hooks in `.claude/hooks/guard.py` enforce part of this; the rest is on you.

#!/usr/bin/env python3
"""PWT SessionStart hook: whatever this prints is added to Claude's context.

Points the session at the newest handoff and its "Next" list, the decisions ledger, the branch,
and which benchmark clips are present, so a session cannot start from stale assumptions.
Never fails the session: any error just prints less.
"""
import os, re, subprocess, sys
from pathlib import Path

root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
app = root / "pwt-starter" / "pwt-app"
out = ["PWT session context (from .claude/hooks/session_start.py):"]

try:
    branch = subprocess.run(["git", "-C", str(root), "branch", "--show-current"],
                            capture_output=True, text=True, timeout=10).stdout.strip()
    head = subprocess.run(["git", "-C", str(root), "log", "--oneline", "-1"],
                          capture_output=True, text=True, timeout=10).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(root), "status", "--short"],
                           capture_output=True, text=True, timeout=10).stdout.strip().splitlines()
    out.append(f"- git: branch {branch or '?'}, HEAD {head or '?'}, {len(dirty)} uncommitted file(s).")
    if branch and branch != "main":
        out.append("  WARNING: not on main. There is one branch (DECISIONS D3). Ask Chirag before working here.")
except Exception:
    pass

handoffs = sorted((app / "docs" / "handoff").glob("HANDOFF-*.md"))
if handoffs:
    h = handoffs[-1]
    out.append(f"- Newest handoff: {h.relative_to(root).as_posix()}. Its Next list:")
    try:
        text = h.read_text(encoding="utf-8")
        m = re.search(r"^##\s*\d*\.?\s*Next\b.*?$(.*?)(?=^##\s|\Z)", text, re.M | re.S)
        lines = [l for l in (m.group(1) if m else "").strip().splitlines() if l.strip()][:14]
        out += ["    " + l for l in lines] or ["    (no Next section found; read the file)"]
    except Exception:
        out.append("    (could not read it)")
else:
    out.append("- No handoff in docs/handoff/. Ask Chirag for the latest status before starting.")

out.append("- Before proposing anything: docs/ARCHITECTURE.md (contract) and docs/DECISIONS.md "
           "(decided + tried-and-rejected with numbers). Do not re-propose a rejected idea without new evidence.")

clips = app / "clips"
need = ["Video_Project_9.mp4", "Video_Project_13.mp4"]
missing = [c for c in need if not (clips / c).exists()]
if missing:
    out.append(f"- Benchmark clips missing from clips/: {', '.join(missing)}. Benchmarks that need them "
               "are NOT RUN; never report them as passing.")

out.append("- Suggested: run /start-session. Finish with /handoff.")
print("\n".join(out))
sys.exit(0)

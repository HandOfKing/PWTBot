#!/usr/bin/env python3
"""PWT guardrail hook (Claude Code PreToolUse).

Blocks (exit 2, reason sent back to Claude):
  - out-of-scope code: live screen capture, input sent to the game, folder watching,
    game-memory reads (DECISIONS D1), and icon gating (`if not icons: continue`, R1)
  - committing videos, force-adding ignored files, force-pushing
  - deleting templates, fixtures or docs

Asks Chirag first (permission prompt):
  - edits to the contract and truth files: ARCHITECTURE, CLAUDE.md, schema, roster,
    profiles, templates, truth CSVs, existing tests, these hooks, CI
  - hard resets, clean, branch deletes, `replay --force`, recursive deletes

Everything else passes through to the normal permission flow.

Self-test:  python .claude/hooks/guard.py --selftest
"""
import json, os, re, sys

APP = "pwt-starter/pwt-app/"

# ---------------------------------------------------------------- content rules
BANNED_CODE = [
    (r"^\s*(import|from)\s+dxcam\b|\bdxcam\.create\b", "live screen capture (dxcam)"),
    (r"^\s*(import|from)\s+mss\b", "live screen capture (mss)"),
    (r"\bImageGrab\.grab\b|\bpyautogui\b|\bpynput\b|\bSendInput\b|\bkeybd_event\b|\bmouse_event\b",
     "screen grabbing or input sent to the game"),
    (r"\bLiveScreenSource\b", "live capture source (deleted 2026-10-07)"),
    (r"^\s*(import|from)\s+watchdog\b|\bReadDirectoryChangesW\b", "folder watching"),
    (r"\bReadProcessMemory\b|\bOpenProcess\b|^\s*(import|from)\s+pymem\b", "reading game memory"),
    (r"if\s+not\s+icons\s*:\s*(continue|return)\b", "icon gating (R1: took a real match from 30 kills to 0)"),
]

# paths (relative to repo root, forward slashes, lowercase) that need Chirag's OK to edit
PROTECTED = [
    (r"^claude\.md$", "root CLAUDE.md"),
    (rf"^{APP}claude\.md$", "the coding-session rules"),
    (rf"^{APP}docs/architecture\.md$", "the contract (ARCHITECTURE.md)"),
    (rf"^{APP}docs/roster\.md$", "player spellings (a wrong entry halves name resolution, R4)"),
    (rf"^{APP}pwt/schema\.sql$", "the database schema (needs a migration + user_version bump)"),
    (rf"^{APP}pwt/profiles/.+\.json$", "HUD coordinates (layout profile)"),
    (rf"^{APP}pwt/templates/", "the template library"),
    (rf"^{APP}tests/fixtures/", "test fixtures / truth data"),
    (r"^\.claude/(settings\.json|hooks/)", "the guardrails themselves"),
    (r"^\.github/workflows/", "the Windows build"),
]
EXISTING_TESTS = rf"^{APP}tests/test_.+\.py$"
VIDEO = r"\.(mp4|mkv|mov|avi|flv|ts)$"
NEVER_DELETE = r"(pwt/templates|tests/fixtures|docs)\b"


def repo_root():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def rel(path):
    """Repo-relative, forward slashes, lowercase."""
    if not path:
        return ""
    p = path.replace("\\", "/")
    root = repo_root().replace("\\", "/").rstrip("/")
    if p.lower().startswith(root.lower() + "/"):
        p = p[len(root) + 1:]
    elif os.path.isabs(path):
        try:
            p = os.path.relpath(path, repo_root()).replace("\\", "/")
        except ValueError:          # different drive on Windows
            pass
    while p.startswith("./"):
        p = p[2:]
    return p.lower()


def new_text(tool, inp):
    if tool == "Write":
        return inp.get("content", "")
    if tool == "Edit":
        return inp.get("new_string", "")
    if tool == "MultiEdit":
        return "\n".join(e.get("new_string", "") for e in inp.get("edits", []))
    if tool == "NotebookEdit":
        return inp.get("new_source", "")
    return ""


# ---------------------------------------------------------------- decisions
def check_edit(tool, inp):
    path = inp.get("file_path") or inp.get("notebook_path") or ""
    r = rel(path)
    if re.search(VIDEO, r):
        return "deny", f"Never write video files into the repo ({path})."
    if r.endswith(".py"):
        text = new_text(tool, inp)
        for pat, why in BANNED_CODE:
            if re.search(pat, text, re.M):
                return "deny", (f"Blocked: this adds {why}, which is out of scope or a rejected idea "
                                "(docs/DECISIONS.md). If Chirag has changed the decision, he must "
                                "update DECISIONS.md first.")
    for pat, why in PROTECTED:
        if re.search(pat, r):
            return "ask", f"Editing {why}: {r}. Chirag must approve this change."
    if re.search(EXISTING_TESTS, r):
        full = os.path.join(repo_root(), r) if not os.path.isabs(path) else path
        if tool != "Write" or os.path.exists(full) or os.path.exists(path):
            return "ask", (f"Editing an existing test ({r}). Changing an expectation to make a test pass "
                           "needs Chirag's OK; adding a new test is fine.")
    return None, ""


def check_bash(cmd):
    c = " ".join(cmd.split())
    low = c.lower().replace("\\", "/")
    # git safety
    if re.search(r"\bgit\s+push\b.*(\s--force\b|\s-f\b|\s--force-with-lease\b)", low):
        return "deny", "Force-push is blocked. main is the only line of work (DECISIONS D3)."
    if re.search(r"\bgit\s+add\b.*\s(-f|--force)\b", low):
        return "deny", "git add --force is blocked: it adds ignored files (clips, videos, data)."
    if re.search(r"\bgit\s+add\b", low) and re.search(r"\.(mp4|mkv|mov|avi)\b", low):
        return "deny", "Never commit videos. Clips live in the gitignored clips/ folder."
    # deletes
    deleting = re.search(r"(\brm\s+-[a-z]*r|\brmdir\b|remove-item\b.*-recurse|\bdel\s+/s|\brd\s+/s)", low)
    if deleting and re.search(NEVER_DELETE, low):
        return "deny", "Deleting templates, fixtures or docs is blocked. Ask Chirag."
    if re.search(r"\bgit\s+rm\b", low) and re.search(NEVER_DELETE, low):
        return "deny", "Removing templates, fixtures or docs from git is blocked. Ask Chirag."
    if re.search(r"\bgit\s+(reset\s+--hard|clean\s+-[a-z]*f|branch\s+-d\b|checkout\s+--\s+\.|restore\s+\.)", low):
        return "ask", "This discards work or deletes a branch. Chirag must approve."
    if deleting:
        return "ask", "Recursive delete. Chirag must approve."
    # pipeline misuse
    if re.search(r"\bpwt\s+replay\b.*\s--force\b", low):
        return "ask", ("replay --force bypasses the layout guard (invariant 8); every row would be "
                       "suspect. Chirag must approve.")
    # writing protected files through the shell
    for key, why in SHELL_PROTECTED:
        k = re.escape(key)
        if re.search(rf"(>>?|\btee\s+(-a\s+)?|\bset-content\b|\bout-file\b|\badd-content\b|\bcopy-item\b|\bcp\s|\bmv\s)[^|;&]*{k}", low) \
                or re.search(rf"\bsed\s+-i\S*\s.*{k}", low):
            return "ask", f"Shell command that writes to {why}. Chirag must approve."
    return None, ""


SHELL_PROTECTED = [
    ("architecture.md", "the contract (ARCHITECTURE.md)"),
    ("claude.md", "a CLAUDE.md"),
    ("roster.md", "player spellings"),
    ("schema.sql", "the database schema"),
    ("profiles/", "a layout profile"),
    ("templates/", "the template library"),
    ("fixtures/", "test fixtures / truth data"),
    (".claude/", "the guardrails"),
    ("workflows/", "the Windows build"),
]


def decide(data):
    tool = data.get("tool_name", "")
    inp = data.get("tool_input", {}) or {}
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return check_edit(tool, inp)
    if tool in ("Bash", "PowerShell"):
        return check_bash(inp.get("command", ""))
    return None, ""


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0                      # never block on a malformed payload
    decision, reason = decide(data)
    if decision == "deny":
        print(reason, file=sys.stderr)
        return 2
    if decision == "ask":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "PWT guard: " + reason}}))
    return 0


# ---------------------------------------------------------------- self-test
def selftest():
    A = APP
    cases = [
        ({"tool_name": "Write", "tool_input": {"file_path": A + "pwt/capture/live.py", "content": "import dxcam\n"}}, "deny"),
        ({"tool_name": "Edit", "tool_input": {"file_path": A + "pwt/readers/feed.py", "old_string": "x", "new_string": "        if not icons: continue\n"}}, "deny"),
        ({"tool_name": "Edit", "tool_input": {"file_path": A + "pwt/readers/feed.py", "old_string": "x", "new_string": "if via_ink and not icons and not self._weapon_blob(m):\n"}}, None),
        ({"tool_name": "Write", "tool_input": {"file_path": A + "app/x.py", "content": "import pyautogui\n"}}, "deny"),
        ({"tool_name": "Write", "tool_input": {"file_path": A + "clips/a.mp4", "content": ""}}, "deny"),
        ({"tool_name": "Edit", "tool_input": {"file_path": A + "docs/ARCHITECTURE.md", "old_string": "a", "new_string": "b"}}, "ask"),
        ({"tool_name": "Edit", "tool_input": {"file_path": A.replace("/", "\\") + "pwt\\profiles\\gameloop-spectator-6v6-1080p.json", "old_string": "a", "new_string": "b"}}, "ask"),
        ({"tool_name": "Edit", "tool_input": {"file_path": A + "tests/fixtures/remaining_vp13.csv", "old_string": "a", "new_string": "b"}}, "ask"),
        ({"tool_name": "Edit", "tool_input": {"file_path": A + "tests/test_rounds.py", "old_string": "a", "new_string": "b"}}, "ask"),
        ({"tool_name": "Write", "tool_input": {"file_path": A + "tests/test_brand_new_thing.py", "content": "def test_x(): pass\n"}}, None),
        ({"tool_name": "Edit", "tool_input": {"file_path": A + "pwt/engine/engine.py", "old_string": "a", "new_string": "b = 1\n"}}, None),
        ({"tool_name": "Edit", "tool_input": {"file_path": A + "docs/DECISIONS.md", "old_string": "a", "new_string": "b"}}, None),
        ({"tool_name": "Edit", "tool_input": {"file_path": A + "docs/METRICS.md", "old_string": "a", "new_string": "b"}}, None),
        ({"tool_name": "Bash", "tool_input": {"command": "git push --force origin main"}}, "deny"),
        ({"tool_name": "Bash", "tool_input": {"command": "git add -f clips/Video_Project_9.mp4"}}, "deny"),
        ({"tool_name": "Bash", "tool_input": {"command": "git add clips/x.mkv"}}, "deny"),
        ({"tool_name": "Bash", "tool_input": {"command": "rm -rf pwt/templates/digits_banner"}}, "deny"),
        ({"tool_name": "PowerShell", "tool_input": {"command": "Remove-Item -Recurse tests\\fixtures"}}, "deny"),
        ({"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD~1"}}, "ask"),
        ({"tool_name": "Bash", "tool_input": {"command": "rm -rf build/"}}, "ask"),
        ({"tool_name": "Bash", "tool_input": {"command": "python -m pwt replay clips/x.mkv --force"}}, "ask"),
        ({"tool_name": "Bash", "tool_input": {"command": "echo hi > docs/ARCHITECTURE.md"}}, "ask"),
        ({"tool_name": "Bash", "tool_input": {"command": "sed -i s/0.55/0.40/ pwt/profiles/gameloop-spectator-6v6-1080p.json"}}, "ask"),
        ({"tool_name": "Bash", "tool_input": {"command": "python tests/run_all.py"}}, None),
        ({"tool_name": "Bash", "tool_input": {"command": "cat docs/ARCHITECTURE.md > /tmp/x.txt"}}, None),
        ({"tool_name": "PowerShell", "tool_input": {"command": "Copy-Item x.png pwt\\templates\\icons\\weapon_AKM.png"}}, "ask"),
        ({"tool_name": "Edit", "tool_input": {"file_path": ".claude/hooks/guard.py", "old_string": "a", "new_string": "b"}}, "ask"),
        ({"tool_name": "Bash", "tool_input": {"command": "python -m pwt --db s.db replay clips/Video_Project_9.mp4 --fps 12 --out s > s/log.txt"}}, None),
        ({"tool_name": "Bash", "tool_input": {"command": "git add pwt/readers/feed.py docs/METRICS.md && git commit -m x"}}, None),
        ({"tool_name": "Read", "tool_input": {"file_path": "x"}}, None),
    ]
    bad = 0
    for data, want in cases:
        got, why = decide(data)
        ok = got == want
        bad += not ok
        label = data["tool_input"].get("command") or data["tool_input"].get("file_path")
        print(f"{'ok  ' if ok else 'FAIL'} {data['tool_name']:<10} want={str(want):<5} got={str(got):<5} {label}")
    print("guard self-test:", "PASSED" if not bad else f"{bad} FAILED")
    return 1 if bad else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        os.environ.setdefault("CLAUDE_PROJECT_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
        sys.exit(selftest())
    sys.exit(main())

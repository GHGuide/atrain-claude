---
description: ATrain Token Autopsy — analyze any past Claude transcript, project what ATrain would have saved. Free try-before-install.
argument-hint: <transcript.jsonl path>
---

User invoked `/atrain-autopsy $ARGUMENTS`.

**EXECUTE the bash block below NOW via the Bash tool. Do not reply "Noted" or summarize — invoke Bash. The user needs the printed card, not an acknowledgement.**

Project savings on a past transcript or prompt list. No live API calls.

## Procedure

1. If $ARGUMENTS is a path → run autopsy on that file.
2. If empty → autopsy the most-recent transcript in `~/.claude/projects/`.
3. Print results card.

## Inline Python

```bash
python3 - <<'EOF'
import pathlib, subprocess, sys

arg = "$ARGUMENTS".strip()

# Locate autopsy script
candidates = [
    pathlib.Path("tools/atrain_autopsy.py"),
    pathlib.Path.home() / ".claude" / "tools" / "atrain_autopsy.py",
]
script = next((c for c in candidates if c.exists()), None)
if script is None:
    print("atrain_autopsy.py not found.")
    sys.exit(1)

# Resolve transcript
target = arg
if not target:
    proj_root = pathlib.Path.home() / ".claude" / "projects"
    if not proj_root.exists():
        print("No transcripts in ~/.claude/projects/. Pass a path explicitly.")
        sys.exit(1)
    jsonls = sorted(proj_root.rglob("*.jsonl"),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    if not jsonls:
        print("No .jsonl transcripts found.")
        sys.exit(1)
    target = str(jsonls[0])
    print(f"(auto-picked most-recent: {target})")

r = subprocess.run(["python3", str(script), target],
                   capture_output=False)
sys.exit(r.returncode)
EOF
```

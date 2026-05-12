---
description: ATrain Live Dashboard — htop-style TUI showing tier histogram, cost meter, sparkline. Press s/c/q for share/clear/quit.
---

User invoked `/atrain-dashboard`.

**EXECUTE the bash block below NOW via the Bash tool. Do not reply "Noted" or summarize — invoke Bash. The user needs the printed launch command, not an acknowledgement.**

Launch the live TUI in a new terminal. Inside Claude Code's prompt
window we can't take over the screen, so print instructions for the
user to run it externally.

## Inline Python

```bash
python3 - <<'EOF'
import pathlib

candidates = [
    pathlib.Path("tools/atrain_tui.py"),
    pathlib.Path.home() / ".claude" / "tools" / "atrain_tui.py",
]
script = next((c for c in candidates if c.exists()), None)

print()
print("┌──────────────────────────────────────────────────────┐")
print("│  🚂 ATrain Live Dashboard                            │")
print("├──────────────────────────────────────────────────────┤")
if script is None:
    print("│  Script not found. Re-install ATrain.                │")
else:
    print("│  Run in a separate terminal:                         │")
    print("│                                                      │")
    print(f"│    python3 {str(script)[:39]:<39s}    │")
    print("│                                                      │")
    print("│  Hotkeys inside the dashboard:                       │")
    print("│    [s]  share receipt (writes SVG + tweet URL)       │")
    print("│    [c]  clear stats                                  │")
    print("│    [q]  quit                                         │")
print("└──────────────────────────────────────────────────────┘")
EOF
```

---
description: ATrain Save Receipt — generate a shareable SVG card showing $ saved this session. Tweet/share with one click.
---

User invoked `/atrain-receipt`.

**EXECUTE the bash block below NOW via the Bash tool. Do not reply "Noted" or summarize — invoke Bash. The user needs the SVG path + tweet URL, not an acknowledgement.**

## Procedure

1. Run `python3 tools/atrain_receipt.py --tweet` (fall back to `python3 ~/.claude/tools/atrain_receipt.py --tweet`).
2. Print the SVG path + tweet intent URL.
3. Show a small ASCII preview of the receipt for in-terminal viewing.

## Inline Python

```bash
python3 - <<'EOF'
import json, pathlib, sys, subprocess, urllib.parse
from datetime import datetime

home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text()) if p.exists() else {}
stats = cfg.get("session_stats", {}) or {}
mode = cfg.get("mode", "balanced")

total = stats.get("total_calls", 0)
cost = stats.get("estimated_cost_usd", 0.0)
base = stats.get("baseline_opus_xhigh_cost_usd", 0.0)
saved = stats.get("estimated_savings_usd", 0.0)
pct = (saved / base * 100) if base > 0 else 0.0

# Try project copy first, fall back to user-scope
candidates = [
    pathlib.Path("tools/atrain_receipt.py"),
    pathlib.Path.home() / ".claude" / "tools" / "atrain_receipt.py",
]
script = next((c for c in candidates if c.exists()), None)
if script is None:
    print("atrain_receipt.py not found. Re-install ATrain.")
    sys.exit(1)

out = pathlib.Path.cwd() / "atrain-receipt.svg"
r = subprocess.run(
    ["python3", str(script), "--out", str(out), "--tweet"],
    capture_output=True, text=True
)
print(r.stdout)
if r.returncode != 0:
    print(r.stderr)
    sys.exit(r.returncode)

text = (
    f"ATrain just saved me ${saved:.2f} ({pct:.0f}%) on this Claude Code "
    f"session. Same accuracy, fraction of the cost. "
    f"github.com/LeonardoCalancea/atrain-claude"
)
tweet_url = "https://twitter.com/intent/tweet?text=" + urllib.parse.quote(text)

print()
print("┌──────────────────────────────────────────────────────┐")
print("│  🚂 ATrain Save Receipt                              │")
print("├──────────────────────────────────────────────────────┤")
print(f"│  Saved              ${saved:>8.2f}  ({pct:>5.1f}%)        │")
print(f"│  vs all-Opus baseline                               │")
print(f"│  ████████████████████░░░░░░░░░░  {min(pct,100):>5.1f}%          │")
print(f"│  Calls: {total:<6d}  Cost: ${cost:<7.2f}  Base: ${base:<7.2f}    │")
print("├──────────────────────────────────────────────────────┤")
print(f"│  SVG:   {str(out)[:42]:<42s}  │")
print(f"│  Tweet: open the URL below                          │")
print("└──────────────────────────────────────────────────────┘")
print()
print(f"Tweet intent: {tweet_url}")
print(f"Open SVG:     open {out}")
EOF
```

---
description: Turn on decompose mode for the rest of this conversation. Every non-trivial prompt will be reasoned about, split into parallel subagent chunks, and merged.
---

User invoked `/router-on`.

Set `decompose_enabled` to `true` in the active router config and
print a confirmation card. From now until `/router-off` (or end of
session), every multi-faceted prompt gets decomposed and dispatched
in parallel through the five tiered subagents.

## Steps

1. Read `~/.claude/router-config.json` (or project-scope fallback).
2. Set `decompose_enabled = true`.
3. Atomic write back.
4. Print this card:

```
┌─────────────────────────────────────────────────────────┐
│  smart-router · DECOMPOSE MODE: ON                      │
├─────────────────────────────┬───────────────────────────┤
│  Cost preset                │  {mode}                   │
│  Behavior                   │  every multi-faceted      │
│                             │  prompt gets decomposed   │
│  Stop                       │  /router-off              │
│  One-shot                   │  /router-once <task>      │
└─────────────────────────────┴───────────────────────────┘
```

Substitute `{mode}` with the value of `mode` from config.

5. Briefly tell the user (one line): "Send your task — I'll plan
   chunks, dispatch in parallel, and merge."

## Inline Python

```bash
python3 - <<'EOF'
import json, os, pathlib
home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text())
cfg["decompose_enabled"] = True
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)
print("decompose_enabled = true")
print("mode =", cfg.get("mode", "balanced"))
EOF
```

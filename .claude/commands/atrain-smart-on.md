---
description: ATrain smart-on — caveman OFF, normal prose. Use when you want full sentences for explanations, doc writing, or talking with someone over Claude. Routing + cache + index still active.
---

User invoked `/atrain-smart-on`.

Switch caveman intensity to **off**. Output reverts to full Claude prose.
Routing, caching, indexing, sensitive-keyword forcing — all stay on.
Lose ~30% of token savings vs default but gain readability for
explanations, docs, prose-heavy work.

## Procedure

1. Load `~/.claude/router-config.json`.
2. Set `caveman_intensity = null`.
3. Atomic write back.
4. Print confirmation card.

## Inline Python

```bash
python3 - <<'EOF'
import json, os, pathlib

home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text())
cfg["caveman_intensity"] = None
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)

print("┌──────────────────────────────────────────────────────┐")
print("│  🎩 ATrain SMART-ON                                  │")
print("├──────────────────────────────────────────────────────┤")
print("│  Caveman: OFF                                        │")
print("│  Output: full prose, normal Claude voice             │")
print("│  Routing, cache, index: still active                 │")
print("│                                                      │")
print("│  Use when: writing docs, explaining concepts, prose  │")
print("│  Switch to max compression: /atrain-dumb-on          │")
print("└──────────────────────────────────────────────────────┘")
EOF
```

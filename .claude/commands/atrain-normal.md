---
description: ATrain normal — caveman OFF, full Claude prose. Use for docs, explanations, prose-heavy work. Routing + cache + index stay active. Switch to max compression with /atrain-terse.
---

User invoked `/atrain-normal`.

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
print("│  ATrain NORMAL                                       │")
print("├──────────────────────────────────────────────────────┤")
print("│  Caveman: OFF                                        │")
print("│  Output: full prose, normal Claude voice             │")
print("│  Routing, cache, index: still active                 │")
print("│                                                      │")
print("│  Use when: writing docs, explaining concepts, prose  │")
print("│  Switch to max compression: /atrain-terse            │")
print("└──────────────────────────────────────────────────────┘")
EOF
```

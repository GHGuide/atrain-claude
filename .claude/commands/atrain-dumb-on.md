---
description: ATrain dumb-on — caveman ULTRA mode. Maximum compression. Output reads like Tarzan but with full technical accuracy. Saves additional 15-25% on top of standard ATrain.
---

User invoked `/atrain-dumb-on`.

Switch caveman intensity to **ultra** — even more compressed than the
default `full`. Tradeoff: harder to skim for non-devs. Wins: another
15-25% output token reduction on top of standard ATrain.

## Procedure

1. Load `~/.claude/router-config.json`.
2. Set `caveman_intensity = "ultra"`.
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
cfg["caveman_intensity"] = "ultra"
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)

print("┌──────────────────────────────────────────────────────┐")
print("│  🦴 ATrain DUMB-ON                                   │")
print("├──────────────────────────────────────────────────────┤")
print("│  Caveman: ULTRA                                      │")
print("│  Output: max compressed, abbreviations, arrows       │")
print("│  Code/commits/security: still write normal           │")
print("│                                                      │")
print("│  Saves +15-25% on top of standard ATrain.            │")
print("│  Switch back: /atrain-smart-on                       │")
print("└──────────────────────────────────────────────────────┘")
EOF
```

---
description: Turn off decompose mode. Subsequent prompts handled in single-Claude mode (no fan-out).
---

User invoked `/router-off`.

Set `decompose_enabled` to `false` in the active router config and
print a brief confirmation. The cost preset (eco/balanced/quality)
stays as it was — only the decompose toggle flips.

## Steps

1. Read `~/.claude/router-config.json` (or project-scope fallback).
2. Set `decompose_enabled = false`.
3. Atomic write back.
4. Print:

```
smart-router · DECOMPOSE MODE: OFF
  Cost preset stays:  {mode}
  Future prompts handled in single-Claude mode.
  Re-enable with /router-on or /router-once <task>.
```

Substitute `{mode}` with the value of `mode` from config.

## Inline Python

```bash
python3 - <<'EOF'
import json, os, pathlib
home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text())
cfg["decompose_enabled"] = False
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)
print("decompose_enabled = false")
print("mode =", cfg.get("mode", "balanced"))
EOF
```

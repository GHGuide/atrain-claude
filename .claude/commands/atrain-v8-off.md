---
description: ATrain v8 OFF — disable progressive Read disclosure. Reverts Read to full-body responses.
---

User invoked `/atrain-v8-off`.

**EXECUTE the bash block below NOW via the Bash tool. Do not reply "Noted" or summarize — invoke Bash.**

## Inline Python

```bash
python3 - <<'EOF'
import json, os, pathlib

home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text())
cfg["progressive_read_enabled"] = False
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)
print("ATrain v8 progressive-read: OFF")
EOF
```

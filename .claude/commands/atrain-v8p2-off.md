---
description: ATrain v8 Phase 2 OFF — disable FTS5 session output index.
---

User invoked `/atrain-v8p2-off`.

**EXECUTE the bash block below NOW via the Bash tool. Do not reply "Noted".**

```bash
python3 - <<'EOF'
import json, os, pathlib
home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text())
cfg["output_index_enabled"] = False
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)
print("ATrain v8 Phase 2 output index: OFF")
EOF
```

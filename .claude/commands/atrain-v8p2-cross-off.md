---
description: ATrain v8 Phase 2b OFF — restrict FTS5 recall back to current session only.
---

User invoked `/atrain-v8p2-cross-off`.

**EXECUTE the bash block below NOW via the Bash tool.**

```bash
python3 - <<'EOF'
import json, os, pathlib
home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text())
cfg["cross_session_recall_enabled"] = False
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)
print("ATrain v8 Phase 2b cross-session recall: OFF")
EOF
```

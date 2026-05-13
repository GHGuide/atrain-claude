---
description: ATrain v8 stop — flip every v8 flag OFF. Entries in DB stay (memory + index unaffected); just stops surfacing.
---

User invoked `/atrain-v8-stop`.

**EXECUTE the bash block below NOW via the Bash tool.**

```bash
python3 - <<'EOF'
import json, os, pathlib
home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text())
cfg["progressive_read_enabled"] = False
cfg["output_index_enabled"] = False
cfg["cross_session_recall_enabled"] = False
cfg["memory_enabled"] = False
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)
print("ATrain v8 stack: OFF (data retained in router-cache.sqlite)")
EOF
```

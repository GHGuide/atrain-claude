---
description: ATrain KILL — disarm everything. All features off. Data retained in cache DB.
---

User invoked `/atrain-kill`.

**EXECUTE the bash block below NOW via the Bash tool. Do not reply "Noted".**

```bash
python3 - <<'EOF'
import json, os, pathlib

home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text()) if p.exists() else {}

cfg["progressive_read_enabled"] = False
cfg["output_index_enabled"] = False
cfg["cross_session_recall_enabled"] = False
cfg["advisory_pruning_enabled"] = False
cfg["caveman_intensity"] = None
cfg["decompose_enabled"] = False

tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)

print("+------------------------------+")
print("|  ATrain KILLED               |")
print("|  All features disarmed.      |")
print("|  Data retained in cache DB.  |")
print("|                              |")
print("|  Re-arm: /atrain-ultimate    |")
print("|          /atrain-regular     |")
print("+------------------------------+")
EOF
```

---
description: ATrain v8 Phase 2b ON — cross-session FTS5 recall. Pre-tool recall searches ALL past sessions' tool outputs, not just this one. Caveat: privacy — hits other projects' transcripts.
---

User invoked `/atrain-v8p2-cross-on`.

**EXECUTE the bash block below NOW via the Bash tool. Do not reply "Noted".**

```bash
python3 - <<'EOF'
import json, os, pathlib
home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text()) if p.exists() else {}
cfg["output_index_enabled"] = True
cfg["cross_session_recall_enabled"] = True
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)

print("+----------------------------------------------------------+")
print("|  ATrain v8 Phase 2b — Cross-session recall ON            |")
print("+----------------------------------------------------------+")
print("|  Pre-tool recall now scans ALL past sessions' outputs.   |")
print("|  Advisory shows sess=<id8> tag on hits from other        |")
print("|  sessions.                                               |")
print("|                                                          |")
print("|  Privacy: index covers EVERY past Claude Code project.   |")
print("|  Disable: /atrain-v8p2-cross-off                         |")
print("|  Purge:   rm ~/.claude/router-cache.sqlite               |")
print("+----------------------------------------------------------+")
EOF
```

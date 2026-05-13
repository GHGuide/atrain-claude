---
description: ATrain v8 Phase 3 memory ON — curated cross-session memory advisory injected on matching UserPromptSubmit.
---

User invoked `/atrain-memory-on`.

**EXECUTE the bash block below NOW via the Bash tool.**

```bash
python3 - <<'EOF'
import json, os, pathlib
home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text()) if p.exists() else {}
cfg["memory_enabled"] = True
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)
print("+----------------------------------------------------------+")
print("|  ATrain v8 Phase 3 — Curated memory ON                   |")
print("+----------------------------------------------------------+")
print("|  UserPromptSubmit queries memory_entries (FTS5).         |")
print("|  Top 2 matches surfaced as advisory, project-scoped.     |")
print("|                                                          |")
print("|  Add memory  : /atrain-remember <category> <text>        |")
print("|     categories: decision | bugfix | convention |          |")
print("|                 lesson   | note                          |")
print("|  List        : /atrain-memory-list                       |")
print("|  Forget      : /atrain-forget <id>                       |")
print("|  Disable     : /atrain-memory-off                        |")
print("+----------------------------------------------------------+")
EOF
```

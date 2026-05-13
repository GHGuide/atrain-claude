---
description: ATrain v8 Phase 2 ON — enable FTS5 session output index. Past tool outputs become recallable; pre-tool advisory surfaces matching excerpts before re-running. +10-15pp on long sessions.
---

User invoked `/atrain-v8p2-on`.

**EXECUTE the bash block below NOW via the Bash tool. Do not reply "Noted" or summarize — invoke Bash.**

```bash
python3 - <<'EOF'
import json, os, pathlib
home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text()) if p.exists() else {}
cfg["output_index_enabled"] = True
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)

print("+------------------------------------------------------+")
print("|  ATrain v8 Phase 2 — FTS5 output index ON            |")
print("+------------------------------------------------------+")
print("|  Every Read/Grep/LS/Glob/Bash output indexed         |")
print("|  Pre-tool: similar query -> recall advisory          |")
print("|  Skip re-run when prior excerpt answers question     |")
print("|                                                      |")
print("|  Query: /atrain-recall <text>                        |")
print("|  Off:   /atrain-v8p2-off                             |")
print("+------------------------------------------------------+")
EOF
```

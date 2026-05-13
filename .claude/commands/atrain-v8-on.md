---
description: ATrain v8 ON — enable progressive Read disclosure. First Read of large source files returns head+outline only. Subsequent Reads bypass. Saves +15-20pp on recon-heavy sessions.
---

User invoked `/atrain-v8-on`.

**EXECUTE the bash block below NOW via the Bash tool. Do not reply "Noted" or summarize — invoke Bash. The user needs the confirmation card.**

Flip `progressive_read_enabled = true` in router-config.

## Inline Python

```bash
python3 - <<'EOF'
import json, os, pathlib

home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text()) if p.exists() else {}
cfg["progressive_read_enabled"] = True
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)

print("+------------------------------------------------------+")
print("|  ATrain v8.0 — Progressive Read ON                   |")
print("+------------------------------------------------------+")
print("|  First Read of a large source file this session ->   |")
print("|    head 60 lines + symbol outline (advisory)         |")
print("|  Re-Read same file -> full bypass                    |")
print("|                                                      |")
print("|  Outline-capable: .py .js .jsx .ts .tsx .go .rs      |")
print("|  Trigger: > 120 lines AND > 4KB                      |")
print("|  Skip: offset/limit already set, ext outside whitelist|")
print("|                                                      |")
print("|  Projected +15-20pp on recon-heavy sessions on top   |")
print("|  of base ATrain savings.                             |")
print("|                                                      |")
print("|  Disable: /atrain-v8-off                             |")
print("+------------------------------------------------------+")
EOF
```

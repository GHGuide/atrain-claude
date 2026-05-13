---
description: ATrain output style. Subcommands: terse (caveman ULTRA, max compression) | normal (caveman OFF, full prose). Replaces /atrain-terse, /atrain-normal.
argument-hint: <terse|normal>
---

User invoked `/atrain-style $ARGUMENTS`.

**EXECUTE the bash block below NOW via the Bash tool. Do not reply "Noted".**

```bash
python3 - <<'EOF'
import json, os, pathlib, sys

arg = """$ARGUMENTS""".strip().lower() or "normal"
home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text()) if p.exists() else {}

if arg in ("terse", "ultra", "dumb"):
    cfg["caveman_intensity"] = "ultra"
    label, body = "TERSE (caveman ULTRA)", "max compressed output, abbreviations, arrows. Code/commits/security stay normal."
elif arg in ("normal", "off", "smart", "prose"):
    cfg["caveman_intensity"] = None
    label, body = "NORMAL (caveman OFF)", "full prose, normal Claude voice. Routing + cache + index stay active."
else:
    print(f"usage: /atrain-style <terse|normal>")
    sys.exit(0)

tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)

print(f"+--------------------------------------------------+")
print(f"|  ATrain style: {label:<33s} |")
print(f"+--------------------------------------------------+")
print(f"|  {body[:46]:<46s} |")
if len(body) > 46:
    print(f"|  {body[46:92]:<46s} |")
print(f"+--------------------------------------------------+")
EOF
```

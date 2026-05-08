---
description: ATrain caveman mode — terse output style. Sets caveman_intensity to lite, full, or ultra. Saves 22-87% output tokens (measured median 65% per JuliusBrussee/caveman eval). Independent of /atrain-eco; overrides for any mode.
argument-hint: lite | full | ultra | off
---

User invoked `/atrain-caveman $ARGUMENTS`.

Set `caveman_intensity` in `~/.claude/router-config.json` to control
ATrain's output-style compression. The `UserPromptSubmit` hook injects
style rules every turn until the conversation ends or the user runs
`/atrain-caveman off`.

## Intensity levels

| Level   | What changes                                                |
|---------|-------------------------------------------------------------|
| `off`   | Standard prose. Plugin doesn't inject style rules.          |
| `lite`  | Drop filler/hedging. Keep articles + full sentences.         |
| `full`  | Drop articles, fragments OK, short synonyms. (Default for `/atrain-eco`.) |
| `ultra` | Abbreviate (DB/auth/config/fn), arrows for causality, one word when one word enough. |

## Procedure

1. Read `~/.claude/router-config.json`.
2. If `$ARGUMENTS == "off"`: set `caveman_intensity = null`.
3. Else if `$ARGUMENTS` is one of `lite | full | ultra`: set
   `caveman_intensity = "<arg>"`.
4. Else: print available levels and current setting.
5. Atomic write back via `.tmp` + `os.replace`.
6. Print confirmation:

```
ATrain caveman: <level>
  Token reduction (typical): <range>
  Code/commits/security still write normal.
  Off: /atrain-caveman off
```

Token-reduction estimates:
- `lite`  → 15-30%
- `full`  → 50-70% (measured median 65%)
- `ultra` → 65-85%

## Inline Python

```bash
python3 - <<EOF
import json, os, pathlib, sys
arg = "$ARGUMENTS".strip().lower()
home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text())
levels = {"off": None, "lite": "lite", "full": "full", "ultra": "ultra"}
if arg not in levels:
    print(f"current: caveman_intensity = {cfg.get('caveman_intensity')!r}")
    print(f"usage: /atrain-caveman <off|lite|full|ultra>")
    sys.exit(0)
cfg["caveman_intensity"] = levels[arg]
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)
print(f"ATrain caveman: {arg}")
print(f"  Code/commits/security still write normal.")
print(f"  Off: /atrain-caveman off")
EOF
```

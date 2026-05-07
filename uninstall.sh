#!/usr/bin/env bash
# smart-router — remove user-scope install
set -euo pipefail

CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"

echo "smart-router → uninstalling from ${CLAUDE_HOME}"
echo

remove_files=(
    "commands/router-eco.md"
    "commands/router-balanced.md"
    "commands/router-quality.md"
    "commands/smart-router-set.md"
    "commands/smart-router-status.md"
    "commands/smart-router-report.md"
    "agents/recon-haiku.md"
    "agents/impl-sonnet.md"
    "agents/api-sonnet.md"
    "agents/architect-opus.md"
    "agents/secure-opus.md"
    "hooks/router.py"
)

echo "[1/3] removing files"
for rel in "${remove_files[@]}"; do
    f="${CLAUDE_HOME}/${rel}"
    if [ -f "$f" ]; then
        rm -v "$f"
    fi
done

echo
echo "[2/3] removing skill directory"
if [ -d "${CLAUDE_HOME}/skills/smart-router" ]; then
    rm -rv "${CLAUDE_HOME}/skills/smart-router"
fi

echo
echo "[3/3] removing hooks from settings.json"
python3 - <<PYEOF
import json, os, pathlib
p = pathlib.Path("${CLAUDE_HOME}/settings.json")
hook_cmd = "python3 ${CLAUDE_HOME}/hooks/router.py"
if not p.exists():
    print("  no settings.json — nothing to do")
    raise SystemExit(0)
cfg = json.loads(p.read_text())
hooks = cfg.get("hooks", {})
removed = []
for evt, entries in list(hooks.items()):
    new_entries = []
    for entry in entries:
        kept = [
            h for h in entry.get("hooks", [])
            if h.get("command", "").strip() != hook_cmd.strip()
        ]
        if kept:
            entry["hooks"] = kept
            new_entries.append(entry)
        elif entry.get("hooks"):
            # entry had only the smart-router hook; drop entry
            removed.append(evt)
    if new_entries:
        hooks[evt] = new_entries
    else:
        del hooks[evt]
        removed.append(evt)
if hooks:
    cfg["hooks"] = hooks
elif "hooks" in cfg:
    del cfg["hooks"]
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)
print(f"  detached: {', '.join(sorted(set(removed))) or 'none'}")
PYEOF

echo
echo "  router-config.json kept at ${CLAUDE_HOME}/router-config.json"
echo "  (delete it manually if you want a fresh install next time)"
echo
echo "✓ uninstalled. Restart Claude Code."

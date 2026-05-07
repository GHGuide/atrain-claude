#!/usr/bin/env bash
# smart-router — install user-scope so slash commands appear globally
# in Claude Code's command picker.
set -euo pipefail

CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "smart-router → installing to ${CLAUDE_HOME}"
echo

mkdir -p \
    "${CLAUDE_HOME}/commands" \
    "${CLAUDE_HOME}/agents" \
    "${CLAUDE_HOME}/skills/smart-router" \
    "${CLAUDE_HOME}/hooks"

echo "[1/6] commands  → ${CLAUDE_HOME}/commands/"
cp -v "${SRC_DIR}/.claude/commands/"*.md "${CLAUDE_HOME}/commands/"

echo
echo "[2/6] agents    → ${CLAUDE_HOME}/agents/"
cp -v "${SRC_DIR}/.claude/agents/"*.md "${CLAUDE_HOME}/agents/"

echo
echo "[3/6] skill     → ${CLAUDE_HOME}/skills/smart-router/"
cp -v "${SRC_DIR}/.claude/skills/smart-router/"*.md \
    "${CLAUDE_HOME}/skills/smart-router/"

echo
echo "[4/6] hook      → ${CLAUDE_HOME}/hooks/"
cp -v "${SRC_DIR}/.claude/hooks/router.py" "${CLAUDE_HOME}/hooks/"

echo
echo "[5/6] router-config.json"
if [ -f "${CLAUDE_HOME}/router-config.json" ]; then
    echo "  existing config kept (re-run with FORCE=1 to overwrite)"
    if [ "${FORCE:-0}" = "1" ]; then
        cp -v "${SRC_DIR}/.claude/router-config.json" \
            "${CLAUDE_HOME}/router-config.json"
    fi
else
    cp -v "${SRC_DIR}/.claude/router-config.json" \
        "${CLAUDE_HOME}/router-config.json"
fi

echo
echo "[6/6] merging hooks into ${CLAUDE_HOME}/settings.json"
python3 - <<PYEOF
import json, os, pathlib
p = pathlib.Path("${CLAUDE_HOME}/settings.json")
hook_cmd = "python3 ${CLAUDE_HOME}/hooks/router.py"
events = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"]

if p.exists():
    cfg = json.loads(p.read_text())
else:
    cfg = {}
cfg.setdefault("hooks", {})

added = []
for evt in events:
    existing = cfg["hooks"].setdefault(evt, [])
    already = False
    for entry in existing:
        for h in entry.get("hooks", []):
            if h.get("command", "").strip() == hook_cmd.strip():
                already = True
                break
        if already:
            break
    if already:
        continue
    star_entry = next(
        (e for e in existing if e.get("matcher") == "*"), None
    )
    if star_entry:
        star_entry.setdefault("hooks", []).append(
            {"type": "command", "command": hook_cmd}
        )
    else:
        existing.append({
            "matcher": "*",
            "hooks": [{"type": "command", "command": hook_cmd}],
        })
    added.append(evt)

tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)

if added:
    print(f"  added: {', '.join(added)}")
else:
    print(f"  all four hooks already wired")
PYEOF

echo
echo "─────────────────────────────────────────────────────────"
echo "  ✓ installed"
echo "─────────────────────────────────────────────────────────"
echo
echo "Restart Claude Code. Then in any project, type:"
echo
echo "    /router-eco        — 95% accuracy, ~90% tokens saved"
echo "    /router-balanced   — 99% accuracy, ~50% tokens saved (default)"
echo "    /router-quality    — 99.9% accuracy, ~20% tokens saved"
echo
echo "Commands now appear in the slash-command picker globally."
echo "Subagents recon-haiku / impl-sonnet / api-sonnet / architect-opus /"
echo "secure-opus available via the Task tool."
echo
echo "Uninstall:  ./uninstall.sh"

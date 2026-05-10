---
description: ATrain × Graphify — optional add-on. Builds a queryable knowledge graph of your codebase, then ATrain routes graph-scoped reads to Haiku more aggressively. Stacks +5-10pp on recon-heavy sessions. Requires `pip install graphifyy` (one-time).
---

User invoked `/atrain-graphify`.

Optional graphify integration. Builds a knowledge graph of the current
project, registers the graphify hook with Claude Code, and flips ATrain's
`graph_aware` routing flag so scoped reads downgrade to Haiku more often.

graphify is third-party (safishamsi/graphify). Not bundled with ATrain to
keep the stdlib-only install promise. This command shells out to it if
present, prints install instructions if not.

## Procedure

1. Detect `graphify` on PATH.
2. If missing → print install command + bail.
3. If present → run `graphify .` to build the graph.
4. Run `graphify claude install` to register the graphify hook.
5. Flip ATrain's `graph_aware = true` in router-config so scoped reads route
   to Haiku more aggressively (graph queries answer "where does X live"
   without needing exploratory Reads).
6. Whitelist `graphify` from ATrain bash-rewrite so the graph build output
   is not truncated.
7. Print confirmation card with synergy note.

## Inline Python implementation

```bash
python3 - <<'EOF'
import json, os, pathlib, shutil, subprocess, sys

# 1. Detect graphify
graphify_bin = shutil.which("graphify")
if graphify_bin is None:
    print("┌──────────────────────────────────────────────────────┐")
    print("│  graphify not found on PATH                          │")
    print("├──────────────────────────────────────────────────────┤")
    print("│  Install (one-time):                                 │")
    print("│    uv tool install graphifyy                         │")
    print("│  or:                                                 │")
    print("│    pipx install graphifyy                            │")
    print("│  or:                                                 │")
    print("│    pip install graphifyy                             │")
    print("│                                                      │")
    print("│  Then re-run /atrain-graphify.                       │")
    print("└──────────────────────────────────────────────────────┘")
    sys.exit(0)

# 2. Build graph in cwd
print("[1/4] Building knowledge graph (graphify .) ...")
r = subprocess.run([graphify_bin, "."], capture_output=False)
if r.returncode != 0:
    print("graphify build failed. Aborting integration.")
    sys.exit(r.returncode)

# 3. Register graphify Claude Code hook
print("\n[2/4] Registering graphify Claude Code hook ...")
subprocess.run([graphify_bin, "claude", "install"], check=False)

# 4. Flip ATrain graph_aware flag + whitelist graphify bash command
print("\n[3/4] Flipping ATrain graph_aware routing flag ...")
home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text()) if p.exists() else {}

cfg["graph_aware"] = True
cfg.setdefault("bash_rewrite_whitelist", [])
if "graphify" not in cfg["bash_rewrite_whitelist"]:
    cfg["bash_rewrite_whitelist"].append("graphify")

# Tighten haiku threshold by 0.02 (graph-scoped reads more trustworthy)
thr = cfg.setdefault("thresholds", {})
thr["haiku_confidence_min"] = max(0.85, thr.get("haiku_confidence_min", 0.92) - 0.02)

tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)

# 5. Confirm
print("\n[4/4] Done.")
print()
print("┌──────────────────────────────────────────────────────────┐")
print("│  ATrain × Graphify — armed                               │")
print("├──────────────────────────────────────────────────────────┤")
print("│  graphify:    graph built in graphify-out/               │")
print("│  graphify:    Claude Code hook registered                │")
print("│  ATrain:      graph_aware = true                         │")
print("│  ATrain:      graphify whitelisted from bash-rewrite     │")
print("│  ATrain:      haiku_confidence_min relaxed by -0.02      │")
print("├──────────────────────────────────────────────────────────┤")
print("│  Synergy: graphify scopes recon, ATrain routes scoped    │")
print("│  reads to Haiku. Projected +5-10pp on recon-heavy        │")
print("│  sessions on top of base ATrain savings.                 │")
print("│                                                          │")
print("│  Run /atrain-status after a few prompts to see the       │")
print("│  delta. /atrain-graphify-off to disable.                 │")
print("└──────────────────────────────────────────────────────────┘")
EOF
```

## Disable

`graph_aware` flag persists across the session. To disable without
uninstalling graphify:

```bash
python3 -c "
import json, pathlib, os
p = pathlib.Path.home() / '.claude' / 'router-config.json'
cfg = json.loads(p.read_text())
cfg['graph_aware'] = False
tmp = p.with_suffix('.json.tmp')
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)
print('graph_aware: off')
"
```

To fully uninstall graphify: `graphify uninstall --purge` (drops the
graph directory too).

## Notes

- graphify is MIT, third-party, ~25 tree-sitter pip deps — that is why it
  is opt-in and not bundled.
- Graph rebuild (`graphify .`) is incremental on second run thanks to its
  `--update` flag and AST-only delta.
- Team workflow: commit `graphify-out/` to git, everyone pulls the graph
  for free. ATrain's `graph_aware` flag is per-user (router-config.json).
- Cost projection script: `python3 tools/atrain_graphify_projection.py
  <transcript.jsonl>` — re-classifies a past session under graph_aware
  rules so you can see the delta before installing graphify.

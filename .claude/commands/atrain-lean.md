---
description: ATrain LEAN — minimum token consumption. Routing + caveman + bash-rewrite stay on. Decompose fan-out + all v8 advisories OFF. Best when your weekly limit matters more than $ saved.
---

User invoked `/atrain-lean`.

**EXECUTE the bash block below NOW via the Bash tool. Do not reply "Noted".**

```bash
python3 - <<'EOF'
import json, os, pathlib

home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text()) if p.exists() else {}

cfg["mode"] = "balanced"
cfg["accuracy_target"] = 99.0
cfg["bash_pre_rewrite_enabled"] = True
cfg["decompose_enabled"] = False
cfg["progressive_read_enabled"] = False
cfg["output_index_enabled"] = False
cfg["cross_session_recall_enabled"] = False
cfg["advisory_pruning_enabled"] = False
cfg["caveman_intensity"] = "full"
cfg["lean_mode"] = True   # v9.6 — silence all verbose advisories

empty_tier = {k: 0 for k in [
    "haiku_none","sonnet_low","sonnet_medium","sonnet_high","sonnet_max",
    "opus_low","opus_medium","opus_high","opus_xhigh","opus_max",
]}
cfg.setdefault("session_stats", {
    "total_calls": 0, "calls_by_tier": dict(empty_tier),
    "tokens_by_tier": dict(empty_tier), "estimated_cost_usd": 0.0,
    "baseline_opus_xhigh_cost_usd": 0.0, "estimated_savings_usd": 0.0,
})

tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)

# Also mirror to project config for repo-local dev testing.
proj_cfg = pathlib.Path(".claude/router-config.json")
if proj_cfg.exists() and proj_cfg.resolve() != p.resolve():
    try:
        pcfg = json.loads(proj_cfg.read_text())
        for k, v in cfg.items():
            pcfg[k] = v
        tmp2 = proj_cfg.with_suffix(".json.tmp")
        tmp2.write_text(json.dumps(pcfg, indent=2))
        os.replace(tmp2, proj_cfg)
    except (OSError, ValueError):
        pass

print("+----------------------------------------------------------+")
print("|  ATrain LEAN — ARMED                                     |")
print("+----------------------------------------------------------+")
print("|  Routing per-call           : ON                         |")
print("|  Bash output rewrite        : ON                         |")
print("|  Caveman compression        : FULL                       |")
print("|                                                          |")
print("|  Decompose fan-out          : OFF (no subagent push)     |")
print("|  Progressive Read advisory  : OFF                        |")
print("|  FTS5 recall advisory       : OFF                        |")
print("|  Cross-session advisory     : OFF                        |")
print("|                                                          |")
print("|  Minimum input overhead. Best for weekly token limits.   |")
print("|                                                          |")
print("|  Max savings: /atrain-ultimate                           |")
print("|  Readable  : /atrain-regular                             |")
print("|  Stop      : /atrain-kill                                |")
print("+----------------------------------------------------------+")
EOF
```

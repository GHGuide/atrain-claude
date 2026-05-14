---
description: ATrain LEAN — routing only. No advisories, no decompose, no subagent fan-out. Best for preserving weekly token limit. Smaller savings than ULTIMATE but minimum overhead.
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

# Routing core ON
cfg["mode"] = "balanced"
cfg["accuracy_target"] = 99.0
cfg["bash_pre_rewrite_enabled"] = True  # bash compaction still on (output-side)

# All advisory/decompose features OFF
cfg["decompose_enabled"] = False              # no fan-out push
cfg["progressive_read_enabled"] = False       # no Read intercept advisory
cfg["output_index_enabled"] = False           # no FTS5 recall hints
cfg["cross_session_recall_enabled"] = False   # no cross-session advisory
cfg["advisory_pruning_enabled"] = False       # nothing to prune
cfg["caveman_intensity"] = "full"             # still compress output

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

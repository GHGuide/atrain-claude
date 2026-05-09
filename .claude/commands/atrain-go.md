---
description: ATrain GO — one-prompt activation. Arms the full stack (routing + decompose + caveman + bash-rewrite) on balanced mode. Persists for the whole conversation. Stop with /atrain-kill.
---

User invoked `/atrain-go`.

ONE prompt. Full ATrain stack armed. Persists across the conversation
until `/atrain-kill` runs or the session ends.

## Procedure

1. Load `~/.claude/router-config.json` (fall back to project copy).
2. Apply the balanced profile (locked default — eco/quality removed for
   simplicity; everything is tuned for max accuracy + max savings here).
3. Reset `session_stats` so the dashboard reflects this run.
4. Atomic write `.tmp` + `os.replace`.
5. Print confirmation card.

## Inline Python implementation

```bash
python3 - <<'EOF'
import json, os, pathlib

home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text())

# Balanced profile — locked, only mode exposed to user
cfg["mode"] = "balanced"
cfg["accuracy_target"] = 99.0
cfg["decompose_enabled"] = True
cfg["caveman_intensity"] = "full"
cfg["bash_pre_rewrite_enabled"] = True
cfg["force_subagent_recon"] = False
cfg.setdefault("thresholds", {}).update({
    "haiku_pct_target": 35,
    # v6.8 — quality+cost tune: 0.88 → 0.92 (stricter haiku trust)
    "haiku_confidence_min": 0.92,
    "sonnet_effort": "high",
    "opus_effort": "high",
    # v6.8 — 1 → 2 critical chunks only, advisory metadata
    "consistency_runs": 2,
})

empty_tier = {k: 0 for k in [
    "haiku_none","sonnet_low","sonnet_medium","sonnet_high","sonnet_max",
    "opus_low","opus_medium","opus_high","opus_xhigh","opus_max",
]}
cfg["session_stats"] = {
    "total_calls": 0,
    "calls_by_tier": dict(empty_tier),
    "tokens_by_tier": dict(empty_tier),
    "escalations_total": 0, "escalations_auth_secrets": 0,
    "escalations_multi_file": 0, "escalations_error_recovery": 0,
    "escalations_user_phrase": 0, "escalations_output_verify": 0,
    "estimated_cost_usd": 0.0, "baseline_opus_xhigh_cost_usd": 0.0,
    "estimated_savings_usd": 0.0,
    "task_dispatches": {}, "dispatch_blocks": 0, "dispatch_mismatches": 0,
    "advisory_calls": 0, "real_subagent_calls": 0,
    "real_savings_usd": 0.0, "advisory_savings_usd": 0.0,
}

tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)

print("┌──────────────────────────────────────────────────────┐")
print("│  ATrain GO — armed for this conversation             │")
print("├──────────────────────────────────────────────────────┤")
print("│  Mode             : balanced (99% acc target)        │")
print("│  Decompose mode   : ON                               │")
print("│  Bash pre-rewrite : ON                               │")
print("│  Sensitive escalate: ON  (47 keywords)               │")
print("│  Cache + memory + index: ON                          │")
print("├──────────────────────────────────────────────────────┤")
print("│  Type tasks normally.                                │")
print("│  /atrain-status  → live accuracy + tokens-saved %    │")
print("│  /atrain-kill    → disable for one-off boring tasks  │")
print("└──────────────────────────────────────────────────────┘")
EOF
```

## Stop / inspect

```
/atrain-status     # accuracy %, tokens saved %, cost vs baseline
/atrain-kill       # turn off for the rest of the session
```

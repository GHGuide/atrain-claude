---
description: Balanced preset — 99% accuracy, ~50% token savings. Default. Sonnet handles most work, Haiku for cheap recon, Opus reserved for sensitive or architectural changes.
---

User invoked `/router-balanced`.

Apply the **Balanced** preset to smart-router and confirm. Steps:

1. Read `.claude/router-config.json`.
2. Apply these values (atomic write via `.tmp` + `os.replace`):
   - `mode` = `"balanced"`
   - `accuracy_target` = `99.0`
   - `thresholds.haiku_pct_target` = `35`
   - `thresholds.haiku_confidence_min` = `0.88`
   - `thresholds.sonnet_effort` = `"high"`
   - `thresholds.opus_effort` = `"high"`
   - `thresholds.consistency_runs` = `1`
3. Reset every `session_stats.*` counter to `0`.
4. Print this card exactly:

```
┌─────────────────────────────────────────────────────────┐
│  smart-router · BALANCED mode (default)                 │
├─────────────────────────────┬───────────────────────────┤
│  Accuracy target            │  99.0%                    │
│  Token savings (estimated)  │  ~50% vs all-Opus         │
│  Haiku rate                 │  ~35% of tool calls       │
│  Sonnet effort              │  high                     │
│  Opus effort                │  high                     │
│  Consistency runs           │  1                        │
└─────────────────────────────┴───────────────────────────┘
  Best for: most day-to-day work — features, bug fixes,
  refactors, tests, code review.
  Auto-escalates to Opus xhigh on auth/secrets/crypto/
  migrations and on any error recovery.

  Switch anytime with /router-eco or /router-quality.
```

Run via inline Python so the read + write happens in a single atomic
step:

```bash
python3 - <<'EOF'
import json, os, pathlib
p = pathlib.Path(".claude/router-config.json")
cfg = json.loads(p.read_text())
cfg["mode"] = "balanced"
cfg["accuracy_target"] = 99.0
cfg["thresholds"].update({
    "haiku_pct_target": 35,
    "haiku_confidence_min": 0.88,
    "sonnet_effort": "high",
    "opus_effort": "high",
    "consistency_runs": 1,
})
empty_tier = {k: 0 for k in [
    "haiku_none","sonnet_low","sonnet_medium","sonnet_high","sonnet_max",
    "opus_low","opus_medium","opus_high","opus_xhigh","opus_max",
]}
cfg["session_stats"] = {
    "total_calls": 0,
    "calls_by_tier": dict(empty_tier),
    "tokens_by_tier": dict(empty_tier),
    "escalations_total": 0,
    "escalations_auth_secrets": 0,
    "escalations_multi_file": 0,
    "escalations_error_recovery": 0,
    "escalations_user_phrase": 0,
    "escalations_output_verify": 0,
    "estimated_cost_usd": 0.0,
    "baseline_opus_xhigh_cost_usd": 0.0,
    "estimated_savings_usd": 0.0,
    "task_dispatches": {},
    "dispatch_blocks": 0,
    "dispatch_mismatches": 0,
}
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)
EOF
```

Do not invoke any further tools after the card prints.

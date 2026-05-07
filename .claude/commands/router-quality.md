---
description: Quality preset — 99.9% accuracy, ~20% token savings. Pushes everything to Opus, runs Sonnet only as a verification shadow. Use for production code, security work, anything with high cost-of-error.
---

User invoked `/router-quality`.

Apply the **Quality** preset to smart-router and confirm. Steps:

1. Read `.claude/router-config.json`.
2. Apply these values (atomic write via `.tmp` + `os.replace`):
   - `mode` = `"quality"`
   - `accuracy_target` = `99.9`
   - `thresholds.haiku_pct_target` = `15`
   - `thresholds.haiku_confidence_min` = `0.95`
   - `thresholds.sonnet_effort` = `"high"`
   - `thresholds.opus_effort` = `"xhigh"`
   - `thresholds.consistency_runs` = `2`
3. Reset every `session_stats.*` counter to `0`.
4. Print this card exactly:

```
┌─────────────────────────────────────────────────────────┐
│  smart-router · QUALITY mode                            │
├─────────────────────────────┬───────────────────────────┤
│  Accuracy target            │  99.9%                    │
│  Token savings (estimated)  │  ~20% vs all-Opus         │
│  Decompose mode             │  ON (every multi-step prompt) │
│  Sonnet effort              │  high                     │
│  Opus effort                │  xhigh                    │
│  Consistency runs           │  2                        │
├─────────────────────────────┴───────────────────────────┤
│  Routing table (chunk type → subagent)                  │
│    recon         → impl-sonnet (NOT haiku)              │
│    impl          → impl-sonnet (high effort)            │
│    api           → architect-opus                       │
│    architecture  → architect-opus (xhigh)               │
│    sensitive     → secure-opus (xhigh)                  │
└─────────────────────────────────────────────────────────┘
  Best for: production code, security-sensitive changes,
  cryptography, migrations, anything where a wrong answer
  is costly to discover later.
  All Sonnet routes get promoted to Opus high; all Opus
  high gets promoted to Opus xhigh. Empty / errored
  outputs auto-retry on Opus xhigh.

  Switch anytime with /router-eco or /router-balanced.
```

Run via inline Python so the read + write happens in a single atomic
step:

```bash
python3 - <<'EOF'
import json, os, pathlib
home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text())
cfg["mode"] = "quality"
cfg["accuracy_target"] = 99.9
cfg["thresholds"].update({
    "haiku_pct_target": 15,
    "haiku_confidence_min": 0.95,
    "sonnet_effort": "high",
    "opus_effort": "xhigh",
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

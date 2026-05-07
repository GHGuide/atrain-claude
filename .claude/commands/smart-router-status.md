---
description: Print current smart-router mode, thresholds, registry, and session stats
---

User invoked: `/smart-router-status`

Print a concise status report for smart-router. Read
`.claude/router-config.json` and print:

## 1. Mode block

```text
smart-router status
─────────────────────────────────────────────
  Mode             : {mode}
  Accuracy target  : {accuracy_target}%
  Sonnet effort    : {thresholds.sonnet_effort}
  Opus effort      : {thresholds.opus_effort}
  Haiku target %   : {thresholds.haiku_pct_target}%
  Haiku confidence : {thresholds.haiku_confidence_min:.3f}
  Consistency runs : {thresholds.consistency_runs}
```

## 2. Model registry

```text
  Model registry (refreshed: {last_model_check})
    opus    → {model_registry.opus.id}
    sonnet  → {model_registry.sonnet.id}
    haiku   → {model_registry.haiku.id}
```

## 3. Session stats

```text
  Session stats
    Total calls    : {session_stats.total_calls}
    haiku  none    : {calls_by_tier.haiku_none}
    sonnet medium  : {calls_by_tier.sonnet_medium}
    sonnet high    : {calls_by_tier.sonnet_high}
    opus   high    : {calls_by_tier.opus_high}
    opus   xhigh   : {calls_by_tier.opus_xhigh}
    opus   max     : {calls_by_tier.opus_max}
    Escalations    : {escalations_total}
    Cost (actual)  : ${estimated_cost_usd:.4f}
    Cost (baseline): ${baseline_opus_xhigh_cost_usd:.4f}
    Savings        : ${estimated_savings_usd:.4f}
```

## 4. Smart recommendation

Compute these proportions from `session_stats`:

- `total = session_stats.total_calls` (skip section if `total == 0`)
- `opus_used = (calls_by_tier.opus_low + opus_medium + opus_high +
   opus_xhigh + opus_max) / total`
- `haiku_used = calls_by_tier.haiku_none / total`
- `escalation_pct = escalations_total / total`

Print **exactly one** of:

- if `opus_used > 0.75`:
  `Opus handling most tasks. Try 'balanced' if speed is a concern.`
- elif `haiku_used > 0.65`:
  `Haiku handling most tasks — savings are maximal. Consider 'fast' to push further.`
- elif `escalation_pct > 0.30`:
  `High escalation rate. Your codebase has many sensitive files — accuracy is being maintained.`
- else:
  `Router performing within expected parameters for {mode} mode.`

Run via inline Python so the math and JSON read happen in one step:

```bash
python3 - <<'EOF'
import json, pathlib
cfg = json.loads(pathlib.Path(".claude/router-config.json").read_text())
# format and print the four blocks above
EOF
```

Do not invoke any further tools after the report prints.

---
description: Eco preset — 95% accuracy, ~90% token savings. Pushes everything routable to Haiku, sends only sensitive/architectural work to Opus.
---

User invoked `/router-eco`.

Apply the **Eco** preset to smart-router and confirm. Steps:

1. Read `.claude/router-config.json`.
2. Apply these values (atomic write via `.tmp` + `os.replace`):
   - `mode` = `"eco"`
   - `accuracy_target` = `95.0`
   - `thresholds.haiku_pct_target` = `60`
   - `thresholds.haiku_confidence_min` = `0.75`
   - `thresholds.sonnet_effort` = `"medium"`
   - `thresholds.opus_effort` = `"high"`
   - `thresholds.consistency_runs` = `0`
3. Reset every `session_stats.*` counter to `0` (calls_by_tier, tokens_by_tier, escalations_*, costs, task_dispatches, dispatch_blocks, dispatch_mismatches).
4. Print this card exactly:

```
┌─────────────────────────────────────────────────────────┐
│  smart-router · ECO mode                                │
├─────────────────────────────┬───────────────────────────┤
│  Accuracy target            │  95.0%                    │
│  Token savings (estimated)  │  ~90% vs all-Opus         │
│  Decompose mode             │  ON (every multi-step prompt) │
│  Sonnet effort              │  medium                   │
│  Opus effort                │  high                     │
│  Consistency runs           │  0                        │
├─────────────────────────────┴───────────────────────────┤
│  Routing table (chunk type → subagent)                  │
│    recon         → recon-haiku                          │
│    impl          → impl-sonnet                          │
│    api           → impl-sonnet (downgraded from api-sonnet) │
│    architecture  → architect-opus                       │
│    sensitive     → secure-opus (never compromised)      │
└─────────────────────────────────────────────────────────┘
  Best for: exploration, prototypes, search-heavy work,
  side projects, sketches.
  Avoid for: anything where a wrong answer is expensive
  to discover later.

  Switch anytime with /router-balanced or /router-quality.
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
cfg["mode"] = "eco"
cfg["accuracy_target"] = 95.0
cfg["thresholds"].update({
    "haiku_pct_target": 60,
    "haiku_confidence_min": 0.75,
    "sonnet_effort": "medium",
    "opus_effort": "high",
    "consistency_runs": 0,
})
# reset session stats
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

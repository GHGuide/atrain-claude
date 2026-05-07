---
description: Full session report with progress bars, escalation breakdown, and cost
---

User invoked: `/smart-router-report`

Print the full smart-router session report.

## Output format (exact)

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  smart-router — session report
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Mode: {MODE} (target: {ACCURACY}%)   Updated: {DATE}
  ─────────────────────────────────────────────
  Tool calls by model + effort:
    haiku  none   ██████░░░░░░  {N} ({PCT}%)
    sonnet medium ████░░░░░░░░  {N} ({PCT}%)
    sonnet high   ██░░░░░░░░░░  {N} ({PCT}%)
    opus   high   ███░░░░░░░░░  {N} ({PCT}%)
    opus   xhigh  █░░░░░░░░░░░  {N} ({PCT}%)
    opus   max    ░░░░░░░░░░░░  {N} ({PCT}%)

  Escalations: {N} ({PCT}% of calls)
    └─ auth/secrets:    {N}
    └─ multi-file:      {N}
    └─ error recovery:  {N}
    └─ user phrase:     {N}
    └─ output verify:   {N}

  Est. tokens:          {N}
  Cost this session:    ${ACTUAL}
  Baseline (opus+xhigh):${BASELINE}
  Savings:              ${SAVED} ({PCT}%)

  Registry: opus→{ID} | sonnet→{ID} | haiku→{ID}
  ─────────────────────────────────────────────
  {CONTEXT-AWARE RECOMMENDATION}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## Rules

- Progress bars are exactly **12 chars wide**: `█` for the proportion of
  total calls in that tier, `░` for the remainder. If a tier has zero
  calls, render 12 `░` characters.
- `{PCT}` percentages are rounded to the nearest whole percent.
- `{ACTUAL}` and `{BASELINE}` formatted as `${value:.4f}`. `{SAVED}` as
  `${value:.4f}` and the parenthesised savings percent rounded whole.
- `{DATE}` is `last_model_check` from the config (the registry
  refresh date), formatted as the raw ISO string.
- `{CONTEXT-AWARE RECOMMENDATION}` follows the same rules as
  `/smart-router-status`:
    - opus calls > 75% of total → `Opus handling most tasks. Try 'balanced' if speed is a concern.`
    - haiku calls > 65% of total → `Haiku handling most tasks — savings are maximal. Consider 'fast' to push further.`
    - escalations > 30% of total → `High escalation rate. Your codebase has many sensitive files — accuracy is being maintained.`
    - else → `Router performing within expected parameters for {MODE} mode.`
- If `total_calls == 0`, print the framework but use `0` everywhere and
  print the recommendation
  `No calls yet — start using Claude Code to populate stats.`

## Implementation

Compute and render the report in one shot:

```bash
python3 - <<'EOF'
import json, pathlib
cfg = json.loads(pathlib.Path(".claude/router-config.json").read_text())
s = cfg["session_stats"]
total = s["total_calls"]
def bar(n):
    if total == 0:
        filled = 0
    else:
        filled = round(12 * n / total)
    filled = max(0, min(12, filled))
    return "█" * filled + "░" * (12 - filled)
def pct(n):
    return 0 if total == 0 else round(100 * n / total)
# ... render the framed block above using the helpers
EOF
```

Do not invoke any further tools after the report prints.

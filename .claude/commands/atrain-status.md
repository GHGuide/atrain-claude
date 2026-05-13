---
description: ATrain live session stats — accuracy %, tokens saved %, total cost vs baseline. One screen, plain numbers.
---

User invoked `/atrain-status`.

**EXECUTE the bash block below NOW via the Bash tool. Do not reply "Noted" or summarize — invoke Bash. The user needs the printed card, not an acknowledgement.**

Print a single status card. Show accuracy + token savings prominently.

## Inline Python

```bash
python3 - <<'EOF'
import json, pathlib
home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text())

mode = cfg.get("mode", "balanced")
target = cfg.get("accuracy_target", 99.0)
stats = cfg.get("session_stats", {}) or {}
calls = stats.get("calls_by_tier", {}) or {}
toks = stats.get("tokens_by_tier", {}) or {}

total = stats.get("total_calls", 0)
mismatches = stats.get("dispatch_mismatches", 0)
blocks = stats.get("dispatch_blocks", 0)
esc = stats.get("escalations_total", 0)

cost = stats.get("estimated_cost_usd", 0.0)
base = stats.get("baseline_opus_xhigh_cost_usd", 0.0)
saved = stats.get("estimated_savings_usd", 0.0)

# Empirical accuracy: 1 - (misroutes / total). Floor at 0
if total > 0:
    empirical = max(0.0, 1.0 - (mismatches / total)) * 100
else:
    empirical = 100.0

# Tokens saved % vs baseline-Opus-xhigh
if base > 0:
    saved_pct = (saved / base) * 100
else:
    saved_pct = 0.0

# Token totals across tiers
total_in = sum(v for k, v in toks.items() if k.endswith("_in")) if any("_in" in k for k in toks) else 0
total_out = sum(v for k, v in toks.items() if k.endswith("_out")) if any("_out" in k for k in toks) else sum(toks.values())

bar_w = 30
def bar(pct):
    n = int(round((pct / 100.0) * bar_w))
    return "█" * n + "░" * (bar_w - n)

print()
print("┌─────────────────────────────────────────────────────────────┐")
print(f"│  ATrain status — mode: {mode:<12s} target acc: {target:>5.1f}%       │")
print("├─────────────────────────────────────────────────────────────┤")
print(f"│  Accuracy   {bar(empirical)} {empirical:6.2f}% │")
print(f"│  Saved tok  {bar(min(saved_pct, 100))} {saved_pct:6.2f}% │")
print("├─────────────────────────────────────────────────────────────┤")
print(f"│  Total calls       : {total:<10d}                             │")
print(f"│  Misroutes         : {mismatches:<10d}                             │")
print(f"│  Blocks (caught)   : {blocks:<10d}                             │")
print(f"│  Sensitive escalate: {esc:<10d}                             │")
print("├─────────────────────────────────────────────────────────────┤")
print(f"│  Cost (this sess)  : ${cost:<8.4f}                            │")
print(f"│  Cost (all-Opus)   : ${base:<8.4f}                            │")
print(f"│  Saved             : ${saved:<8.4f}                            │")
print("├─────────────────────────────────────────────────────────────┤")
print(f"│  Tier breakdown                                             │")
for tier in ("haiku_none","sonnet_medium","sonnet_high",
             "opus_high","opus_xhigh","opus_max"):
    n = calls.get(tier, 0)
    if n > 0:
        print(f"│    {tier:<16s}: {n:<6d}                              │")
print("├─────────────────────────────────────────────────────────────┤")

# v6.8 — cost budget alarm + actionable tips. Show flags when
# session is going off-rails so user can intervene mid-flight.
flags = []
if cost > 5.0 and saved_pct < 30.0:
    flags.append(f"⚠ HIGH-COST ({cost:.2f}$) + LOW SAVE ({saved_pct:.0f}%)")
    flags.append("  → escalating too aggressively. Check tier breakdown")
    flags.append("  → opus_xhigh count high? Run /clear, restart")
opus_xh = calls.get("opus_xhigh", 0)
if total > 100 and opus_xh / max(total, 1) > 0.30:
    flags.append("⚠ Over-escalating: >30% of calls hit opus_xhigh")
    flags.append("  → likely path/keyword false-positive. /atrain-go to reset")
if total > 50 and calls.get("haiku_none", 0) / max(total, 1) < 0.10:
    flags.append("⚠ Under-using haiku: <10% recon on cheapest tier")
    flags.append("  → run: python3 ~/.claude/hooks/router.py --index")
if total > 80:
    flags.append(f"ℹ Long session ({total} calls). Consider /clear before")
    flags.append("  next unrelated task. Cuts 30-60% off next prompt.")

# v9 feature status — show which optimizations are armed
v9_flags = []
def _on_off(key):
    return "ON " if cfg.get(key, False) else "off"
v9_flags.append(f"caveman={cfg.get('caveman_intensity','off') or 'off':<5s}")
v9_flags.append(f"progRead={_on_off('progressive_read_enabled')}")
v9_flags.append(f"fts5={_on_off('output_index_enabled')}")
v9_flags.append(f"cross={_on_off('cross_session_recall_enabled')}")
v9_flags.append(f"adv-prune={_on_off('advisory_pruning_enabled')}")
print(f"│  v9 stack : {' '.join(v9_flags):<48s} │")
print("├─────────────────────────────────────────────────────────────┤")

if flags:
    print("│  Alerts                                                     │")
    for f in flags:
        print(f"│  {f:<60s} │")
    print("└─────────────────────────────────────────────────────────────┘")
else:
    print("│  Healthy — no flags                                         │")
    print("└─────────────────────────────────────────────────────────────┘")
EOF
```

Do not invoke any further tools after the card prints.

---
description: ATrain GO — one-prompt activation. Sets mode + decompose + caveman + bash-rewrite + force-subagent-recon in a single shot. Persists for the whole conversation. Use this instead of running the four separate slash commands.
argument-hint: eco | balanced | quality
---

User invoked `/atrain-go $ARGUMENTS`.

ONE prompt. Full ATrain stack armed. Persists across the conversation
until user runs `/atrain-kill` or starts a fresh session.

## Procedure

1. Parse `$ARGUMENTS`: must be one of `eco`, `balanced`, `quality`
   (default: `balanced` if empty or unrecognized).

2. Read `~/.claude/router-config.json` (fall back to project copy).

3. Apply ALL settings in one atomic write:

   ```python
   mode_settings = {
       "eco": {
           "mode": "eco",
           "accuracy_target": 95.0,
           "decompose_enabled": True,
           "caveman_intensity": "full",
           "bash_pre_rewrite_enabled": True,
           "force_subagent_recon": True,
           "thresholds": {
               "haiku_pct_target": 60,
               "haiku_confidence_min": 0.75,
               "sonnet_effort": "medium",
               "opus_effort": "high",
               "consistency_runs": 0,
           },
       },
       "balanced": {
           "mode": "balanced",
           "accuracy_target": 99.0,
           "decompose_enabled": True,
           "caveman_intensity": None,
           "bash_pre_rewrite_enabled": True,
           "force_subagent_recon": False,
           "thresholds": {
               "haiku_pct_target": 35,
               "haiku_confidence_min": 0.88,
               "sonnet_effort": "high",
               "opus_effort": "high",
               "consistency_runs": 1,
           },
       },
       "quality": {
           "mode": "quality",
           "accuracy_target": 99.9,
           "decompose_enabled": True,
           "caveman_intensity": None,
           "bash_pre_rewrite_enabled": True,
           "force_subagent_recon": False,
           "thresholds": {
               "haiku_pct_target": 15,
               "haiku_confidence_min": 0.95,
               "sonnet_effort": "high",
               "opus_effort": "xhigh",
               "consistency_runs": 2,
           },
       },
   }
   ```

4. Reset `session_stats` to zeros so the dashboard reflects this run.

5. Atomic write `.tmp` + `os.replace`.

6. Print confirmation card (single block, no other commentary):

   ```
   ┌──────────────────────────────────────────────────────┐
   │  ATrain GO — full stack ARMED for this conversation │
   ├──────────────────────────────────────────────────────┤
   │  Mode             : {MODE} ({ACCURACY}%)            │
   │  Decompose mode   : ON                               │
   │  Caveman terse    : {CAVEMAN}                        │
   │  Bash pre-rewrite : ON  (rtk pattern, -80% on bash) │
   │  Force subagent   : {SUBRECON}  (eco only)          │
   │  Sensitive escalate: ON  (47 keywords, forced opus) │
   │  Cache + memory + index: ON  (build index manually:  │
   │                  python3 ~/.claude/hooks/router.py   │
   │                  --index)                            │
   ├──────────────────────────────────────────────────────┤
   │  Type tasks normally. Stop with /atrain-kill.        │
   │  Switch mode mid-conv: /atrain-go <other-mode>       │
   └──────────────────────────────────────────────────────┘
   ```

   Substitute placeholders. `{CAVEMAN}` is "full" for eco,
   "off" for balanced/quality. `{SUBRECON}` is "ON (asks before
   each Read/Grep)" for eco, "OFF" for balanced/quality.

## Inline Python implementation

```bash
python3 - <<EOF
import json, os, pathlib, sys
arg = "$ARGUMENTS".strip().lower()
if arg not in ("eco", "balanced", "quality"):
    arg = "balanced"

home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text())

profiles = {
    "eco": {
        "mode": "eco", "accuracy_

... [content truncated, 193 chars omitted] ...

fidence_min": 0.75,
        "sonnet_effort": "medium", "opus_effort": "high", "consistency_runs": 0,
    },
    "balanced": {
        "mode": "balanced", "accuracy_target": 99.0,
        "decompose_enabled": True, "caveman_intensity": None,
        "bash_pre_rewrite_enabled": True, "force_subagent_recon": False,
        "haiku_pct_target": 35, "haiku_confidence_min": 0.88,
        "sonnet_effort": "high", "opus_effort": "high", "consistency_runs": 1,
    },
    "quality": {
        "mode": "quality", "accuracy_target": 99.9,
        "decompose_enabled": True, "caveman_intensity": None,
        "bash_pre_rewrite_enabled": True, "force_subagent_recon": False,
        "haiku_pct_target": 15, "haiku_confidence_min": 0.95,
        "sonnet_effort": "high", "opus_effort": "xhigh", "consistency_runs": 2,
    },
}
prof = profiles[arg]
cfg["mode"] = prof["mode"]
cfg["accuracy_target"] = prof["accuracy_target"]
cfg["decompose_enabled"] = prof["decompose_enabled"]
cfg["caveman_intensity"] = prof["caveman_intensity"]
cfg["bash_pre_rewrite_enabled"] = prof["bash_pre_rewrite_enabled"]
cfg["force_subagent_recon"] = prof["force_subagent_recon"]
cfg.setdefault("thresholds", {}).update({
    "haiku_pct_target": prof["haiku_pct_target"],
    "haiku_confidence_min": prof["haiku_confidence_min"],
    "sonnet_effort": prof["sonnet_effort"],
    "opus_effort": prof["opus_effort"],
    "consistency_runs": prof["consistency_runs"],
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

caveman_str = prof["caveman_intensity"] or "off"
subrecon_str = "ON  (asks before each Read/Grep)" if prof["force_subagent_recon"] else "OFF"
print("┌──────────────────────────────────────────────────────┐")
print(f"│  ATrain GO — full stack ARMED for this conversation │")
print("├──────────────────────────────────────────────────────┤")
print(f"│  Mode             : {arg} ({prof['accuracy_target']}%)               ")
print(f"│  Decompose mode   : ON                               ")
print(f"│  Caveman terse    : {caveman_str}                                ")
print(f"│  Bash pre-rewrite : ON  (rtk pattern, -80% on bash) ")
print(f"│  Force subagent   : {subrecon_str}                   ")
print(f"│  Sensitive escalate: ON  (47 keywords, forced opus) ")
print(f"│  Cache + memory + index: ON                          ")
print("├──────────────────────────────────────────────────────┤")
print(f"│  Type tasks normally. Stop with /atrain-kill.       ")
print(f"│  Switch mode mid-conv: /atrain-go <other-mode>      ")
print("└──────────────────────────────────────────────────────┘")
EOF
```

## Why use this instead of separate commands

Without `/atrain-go`, full activation requires:
```
/atrain-eco
/atrain-on
/atrain-caveman full
```
Three prompts, three round-trips, more chance to forget one.

`/atrain-go eco` does all three plus the bash-pre-rewrite + force-
subagent-recon flags in a single slash command. Persists for the
whole conversation.

## Stop / change

```
/atrain-kill              # disable decompose mode (keep mode preset)
/atrain-go balanced       # switch mid-conversation (also resets stats)
/atrain-caveman off       # disable caveman, keep everything else
```

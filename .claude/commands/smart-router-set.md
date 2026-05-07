---
description: Set smart-router mode (fast/balanced/precise/max) or custom accuracy target
argument-hint: fast | balanced | precise | max | <90.0..99.99>
---

User invoked: `/smart-router-set $ARGUMENTS`

Apply the smart-router mode change. The argument `$ARGUMENTS` is one of:
`fast`, `balanced`, `precise`, `max`, or a numeric accuracy target between
`90.0` and `99.99`.

## Mode → threshold mappings

| Mode       | accuracy | haiku_pct | sonnet_effort | opus_effort | consistency_runs |
|------------|----------|-----------|---------------|-------------|------------------|
| `fast`     | 95.00    | 60        | medium        | high        | 0                |
| `balanced` | 99.00    | 35        | high          | high        | 1                |
| `precise`  | 99.90    | 15        | high          | xhigh       | 2                |
| `max`      | 99.99    | 5         | high          | max         | 2 (session-only) |

Custom numeric targets between 90 and 99.99 linearly interpolate every
column above between the two surrounding anchors.

## Steps

1. **Read** `.claude/router-config.json`.

2. **Resolve the target.** If `$ARGUMENTS` is one of the four named modes,
   use the row from the table. If it's a number, interpolate.

3. **Update the config in memory:**
   - `mode` ← the named mode (or `"custom"` for numeric)
   - `accuracy_target` ← the resolved accuracy value
   - `thresholds.haiku_pct_target` ← resolved haiku_pct
   - `thresholds.sonnet_effort` ← resolved sonnet_effort
   - `thresholds.opus_effort` ← resolved opus_effort. **Important:**
     if the resolved opus_effort is `max`, do **not** persist it. Write
     `xhigh` to `thresholds.opus_effort` and print a warning that `max`
     is session-only.
   - `thresholds.consistency_runs` ← resolved consistency_runs

4. **Reset session_stats** — every counter under `session_stats` to `0`
   (calls_by_tier values to 0, tokens_by_tier values to 0, escalations_*
   to 0, costs to 0.0).

5. **Atomic write.** Write the updated config to
   `.claude/router-config.json.tmp` then `os.replace` onto
   `.claude/router-config.json`. Do this via the Write tool followed by
   a `mv` — or, more reliably, run:

   ```bash
   python3 - <<'EOF'
   import json, os, pathlib
   p = pathlib.Path(".claude/router-config.json")
   cfg = json.loads(p.read_text())
   # ... apply the updates above ...
   tmp = p.with_suffix(".json.tmp")
   tmp.write_text(json.dumps(cfg, indent=2))
   os.replace(tmp, p)
   EOF
   ```

6. **Print the confirmation table** in this exact format, substituting
   the resolved values:

   ```text
   ┌──────────────────────────────────────────────┐
   │  smart-router mode set: {MODE}               │
   ├──────────────────┬───────────────────────────┤
   │  Accuracy target │  {ACCURACY}%              │
   │  Haiku rate est. │  ~{PCT}% of tool calls    │
   │  Sonnet effort   │  {EFFORT}                 │
   │  Opus effort     │  {EFFORT}                 │
   │  Consistency     │  {N} verification runs    │
   │  Est. savings    │  ~{PCT}% vs opus+xhigh    │
   └──────────────────┴───────────────────────────┘
   Model registry: opus→{ID} | sonnet→{ID} | haiku→{ID}
   ```

   Estimated savings is approximated as
   `(haiku_pct * 0.84 + (100-haiku_pct-5) * 0.40 + 5 * 0)` rounded —
   i.e. Haiku saves ~84% vs Opus output, Sonnet saves ~40%, Opus
   saves 0%. Round to the nearest whole percent.

7. If the requested mode is `max`, append below the table:

   ```text
   ⚠  max effort is session-scoped only. The persisted opus_effort
      is xhigh; the runtime promotes to max for this session.
   ```

Do not run any other tools after the table is printed.

# smart-router

Dynamic per-call selection of Claude model and effort level for Claude
Code. Routes cheap operations to Haiku, mid-size edits to Sonnet, and
architecture / sensitive work to Opus, while keeping a configurable
accuracy target. Auto-discovers new Claude models from the Anthropic
API so the registry never goes stale.

## Two layers

1. **Subagent dispatch (real, runtime-respected)** — five pre-built
   subagents in `.claude/agents/` with `model:` frontmatter that
   Claude Code actually honors. The PreToolUse hook enforces
   `secure-opus` for sensitive content and tracks dispatch stats.
2. **Per-tool classification (analytics)** — the hook classifies
   every tool call into a model+effort tier and tracks cost/savings.
   Claude Code's runtime may or may not respect a `model_override`
   returned from a hook; either way, the stats remain accurate.

## Install

1. Drop the `.claude/` tree into your project root, or copy the
   plugin's contents into your existing `.claude/` directory:

   ```
   .claude/
   ├── agents/recon-haiku.md
   ├── agents/impl-sonnet.md
   ├── agents/api-sonnet.md
   ├── agents/architect-opus.md
   ├── agents/secure-opus.md
   ├── skills/smart-router/SKILL.md
   ├── skills/smart-router/README.md
   ├── commands/smart-router-set.md
   ├── commands/smart-router-status.md
   ├── commands/smart-router-report.md
   ├── hooks/router.py
   ├── router-config.json
   └── settings.json
   ```

2. Verify Python 3.11+ is on `$PATH`:

   ```bash
   python3 --version
   ```

3. Self-test the hook:

   ```bash
   python3 .claude/hooks/router.py --test
   ```

   All 16 tests must pass (12 routing + 3 dispatch + 1 registry).

4. Start a new Claude Code session in this directory. The hooks
   activate automatically via `.claude/settings.json`.

5. (Optional) Manually refresh the model registry when Anthropic
   ships a new model. Requires an API key only for this one-shot
   refresh; day-to-day routing uses your Claude Code bundled tokens.

   ```bash
   curl -s https://api.anthropic.com/v1/models \
     -H "x-api-key: $ANTHROPIC_API_KEY" \
     -H "anthropic-version: 2023-06-01" \
     | python3 .claude/hooks/router.py --update-models
   ```

The plugin itself **never makes network calls during routing**. All
classification runs locally in the Python hook; actual model calls
go through Claude Code using your existing subscription quota.

## Subagents

| Subagent          | Model      | When to use                              |
|-------------------|------------|------------------------------------------|
| `recon-haiku`     | Haiku 4.5  | read-only recon, search, grep            |
| `impl-sonnet`     | Sonnet 4.6 | default — single/2-file edits, tests     |
| `api-sonnet`      | Sonnet 4.6 | endpoints, routes, integrations          |
| `architect-opus`  | Opus 4.7   | multi-file refactors, design, perf       |
| `secure-opus`     | Opus 4.7   | MANDATORY for auth/secrets/crypto        |

Spawn via the Task tool — `subagent_type: "secure-opus"` etc. The
PreToolUse hook will block with `permissionDecision: ask` if it sees
sensitive keywords going to a non-opus agent.

## Slash commands

### `/smart-router-set <target>`

Set the mode and accuracy target.

```text
/smart-router-set fast       # 95.0%   accuracy, ~60% Haiku
/smart-router-set balanced   # 99.0%   accuracy, ~35% Haiku  (default)
/smart-router-set precise    # 99.9%   accuracy, ~15% Haiku
/smart-router-set max        # 99.99%  accuracy, ~5% Haiku, opus+max
/smart-router-set 99.5       # custom — interpolated thresholds
```

Modes interpolate `haiku_pct_target`, sonnet/opus effort, and
verification runs linearly between the named anchors.

### `/smart-router-status`

Print the current mode, accuracy target, active thresholds, model
registry IDs (with last-refreshed date), per-tier call breakdown, and
a smart recommendation based on observed call distribution.

### `/smart-router-report`

Full per-session breakdown with ASCII progress bars: calls per
`(model, effort)` tier, escalation reasons, token totals, actual vs
baseline cost, savings percentage, and a context-aware recommendation.

## Effort levels

| Level   | Model support              | Behaviour                       |
|---------|----------------------------|---------------------------------|
| low     | opus, sonnet               | minimal thinking, fastest       |
| medium  | opus, sonnet               | moderate thinking, may skip     |
| high    | opus, sonnet               | always thinks                   |
| xhigh   | opus only                  | always thinks deeply            |
| max     | opus, sonnet (session only)| deepest reasoning, no ceiling   |
| (none)  | haiku                      | Haiku has no `effort` parameter |

`max` is session-scoped: it is **never persisted** to
`router-config.json` and reverts automatically on the next call.

## Auto-update

The model registry refreshes from the Anthropic API at most once per
24 hours. To trigger a refresh manually:

```bash
curl -s https://api.anthropic.com/v1/models \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  | python3 .claude/hooks/router.py --update-models
```

The hook picks the highest-version match for each prefix
(`claude-opus-4`, `claude-sonnet-4`, `claude-haiku-4`) and writes
the new IDs atomically. Routing decisions immediately use the
updated IDs.

## Troubleshooting

1. **Hook doesn't seem to fire** — check that `python3` resolves to
   3.11+ and that `.claude/settings.json` is valid JSON. Run
   `python3 .claude/hooks/router.py --test` to confirm the script
   itself works.

2. **Unexpected Opus calls** — open `.claude/router-config.json`
   and look at `session_stats.escalations_*`. A high
   `escalations_auth_secrets` count means your inputs reference one
   of the sensitive keywords; this is by design.

3. **Haiku misclassifying real work** — set
   `/smart-router-set balanced` (or `precise`) to raise the
   `haiku_confidence_min` threshold. The session-end calibrator will
   tighten it automatically if Haiku errors exceed 30%.

4. **Routing seems stale after a Claude release** — force a registry
   refresh:
   ```bash
   curl -s https://api.anthropic.com/v1/models \
     -H "x-api-key: $ANTHROPIC_API_KEY" \
     -H "anthropic-version: 2023-06-01" \
     | python3 .claude/hooks/router.py --update-models
   ```

5. **Hook is slow** — `router.py` should run under 50 ms per call.
   If you see slowdowns, check for huge `tool_input` payloads being
   stringified (the classifier reads `len(json.dumps(tool_input))`).
   The hook never blocks on the network; the registry refresh is a
   separate manual or scheduled job.

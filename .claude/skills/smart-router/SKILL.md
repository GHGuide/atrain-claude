---
name: smart-router
description: Dynamic per-call selection of Claude model + effort level. Routes Read/LS/grep to Haiku, mid-size edits to Sonnet, architecture/sensitive work to Opus. Self-calibrates haiku trust threshold from session error rate. Auto-discovers new models from the Anthropic API.
---

# smart-router

## Purpose

smart-router dynamically selects the optimal model + effort level for every
tool call, maximising speed and minimising cost while hitting the user's
accuracy target. Read `.claude/router-config.json` at every session start.

The router operates as a stdlib-only Python hook bound to PreToolUse and
PostToolUse. The PreToolUse hook chooses the model and effort; the
PostToolUse hook records actual usage, detects errors, and triggers
output-verification escalations in PRECISE mode. SessionEnd recalibrates
the haiku confidence threshold based on the trust rate.

## Auto-discovery rule

At session start, if `last_model_check` in `.claude/router-config.json` is
older than 24 hours, run:

```bash
curl -s https://api.anthropic.com/v1/models \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  | python3 .claude/hooks/router.py --update-models
```

This keeps the router current whenever Anthropic releases new models.
The script picks the highest-version match for each prefix
(`claude-opus-4`, `claude-sonnet-4`, `claude-haiku-4`) and rewrites
`model_registry[*].id` atomically.

## Routing decision table

### HAIKU + no effort
- `tool_name` in {Read, LS, Glob} **and** `tool_input_len < 300`
- `tool_name == Grep` and `tool_input_len < 150`
- `tool_name == WebSearch` and query `< 80` chars
- `Bash` command starts with: `grep`, `ls`, `find`, `cat`, `echo`, `pwd`,
  `wc`, `head`, `tail`, `diff`, `stat`, `file`
- Formatting: `prettier`, `black`, `eslint --fix`, `gofmt`

### SONNET + medium effort
- Write/Edit on files estimated `< 150` lines (input length `< 1500`)
- Test runners: `pytest`, `jest`, `vitest`, `npm test`, `cargo test`,
  `go test`
- Boilerplate: "generate", "scaffold", "create a basic", "add a simple",
  "stub out", "template"

### SONNET + high effort
- Write/Edit `150–400` lines (input length `1500–4000`)
- Changes across `2–3` files simultaneously (`2` paths)
- Debugging with a clear error + stack trace
- API routes, new endpoints, adding integrations

### OPUS + high effort
- Write/Edit `> 400` lines (input length `>= 4000`)
- `4+` file changes simultaneously (3+ paths)
- Architecture, system design, tradeoff analysis
- Complex debugging (no clear error, subtle bugs)
- Security review, performance optimisation, algorithms
- Keywords: "refactor entire", "redesign", "optimize", "bottleneck",
  "architecture", "design pattern", "review all"

### OPUS + xhigh effort
- Only when mode `accuracy_target >= 99.9%` AND task is OPUS tier

### OPUS + max effort
- NEVER auto-assigned. Only via `/smart-router-set max` OR when user
  writes: "think carefully", "use max effort", "spare no tokens".
  Applies current task only, then reverts. NOT persisted.

### DEFAULT
`sonnet + medium`

## Hard escalation rules (ALWAYS → opus + xhigh, no exceptions)

1. Tool input references `> 3` file paths simultaneously
2. Any of these in `tool_input` (case-insensitive):
   `auth`, `authentication`, `password`, `secret`, `api_key`,
   `private_key`, `token`, `crypto`, `encrypt`, `decrypt`, `hash`,
   `migration`, `sql schema`, `production`, `deploy`, `main branch`,
   `master branch`, `.env`, `ssl`, `tls`
3. Previous tool call returned an error/exception
4. User message contains: "think carefully", "be precise",
   "don't mess this up", "critical", "production"
5. Task modifies: `package.json`, `pyproject.toml`, `Cargo.toml`,
   `go.mod`, `requirements.txt`

## PRECISE mode override (accuracy_target >= 99.9%)

- All sonnet calls → opus + high
- All opus + high → opus + xhigh
- Empty or error-flagged outputs trigger automatic retry on opus + xhigh

## Session stats

After every tool call batch, the PostToolUse hook updates
`session_stats` in `router-config.json`:

- Increment `calls_by_tier["{model}_{effort}"]`
- Add token estimate (`len(output)/4`) to `tokens_by_tier`
- Update `estimated_cost_usd` from the per-tier output price
- Compute `baseline_opus_xhigh_cost_usd` at the opus output rate
- `estimated_savings_usd = baseline - actual`

The SessionEnd handler computes the haiku trust rate
(`trusted / total_haiku`) and adjusts `thresholds.haiku_confidence_min`:
relax `-0.005` if `> 0.90` (and mode != fast), tighten `+0.01` if
`< 0.70`. Output-verify escalations always tighten. The adjustment is
appended to `calibration_history`.

## Effort support

| Model     | Effort levels                       |
|-----------|-------------------------------------|
| Opus 4.7  | low / medium / high / xhigh / max   |
| Sonnet 4.6| low / medium / high / max           |
| Haiku 4.5 | none — never include `effort` field |

## Decompose-by-default — split every non-trivial prompt

This is **how the router works**, not an opt-in mode. For any user
prompt with 2 or more distinct concerns, decompose it into chunks
and dispatch them through the five tiered subagents in parallel.

The active preset (`eco`, `balanced`, `quality`) does **not** change
whether you decompose — it changes **which subagent each chunk gets
assigned to**. The mapping is stored in
`.claude/router-config.json` under `routing_tables[<mode>]`. Read
that file at the start of every session and apply the active table.

### Routing tables (chunk type → subagent)

| Chunk type     | eco             | balanced         | quality          |
|----------------|-----------------|------------------|------------------|
| recon          | `recon-haiku`   | `recon-haiku`    | `impl-sonnet`    |
| impl           | `impl-sonnet`   | `impl-sonnet`    | `impl-sonnet`    |
| api            | `impl-sonnet`   | `api-sonnet`     | `architect-opus` |
| architecture   | `architect-opus`| `architect-opus` | `architect-opus` |
| sensitive      | `secure-opus`   | `secure-opus`    | `secure-opus`    |

`secure-opus` is the same across every preset — security work never
gets cost-optimized. Everything else slides up the model ladder as
the preset gets stricter.

### Procedure

1. **Plan.** Write a brief markdown list — 3 to 7 chunks max. Each
   chunk gets a one-line task, an assigned subagent, and a list of
   chunks it depends on.

2. **Show.** Print the plan to the user before dispatching. Format:

   ```
   Plan:
   1. [recon-haiku]    find existing auth middleware
   2. [architect-opus] design rate-limit strategy
   3. [secure-opus]    implement bcrypt password hashing   ← needs 1
   4. [impl-sonnet]    wire the route handler              ← needs 1, 2, 3
   ```

3. **Fan out.** For all chunks at the same dependency level, emit
   parallel Task tool calls **in the same assistant message**.
   Claude Code runs them concurrently — independent chunks finish
   in roughly the time of the slowest one.

4. **Merge.** When the subagent results return, compile them into
   one coherent answer in main Claude. Cite which chunk produced
   which finding so the user can audit.

### Agent selection cheat sheet

| Subtask shape                          | Agent             |
|----------------------------------------|-------------------|
| find / locate / list / search / where  | recon-haiku       |
| write small file / edit / fix bug      | impl-sonnet       |
| add endpoint / route / integration     | api-sonnet        |
| refactor / design / multi-file changes | architect-opus    |
| auth / secret / crypto / migration     | secure-opus       |

### When to skip decomposition

- Trivial prompts (one file read, one edit, single grep).
- User explicitly says "do this yourself" or "no agents".
- Latency budget is tight — each subagent dispatch adds ~5-15 s of
  overhead even when it returns quickly.

### Token economics — why this beats main-Opus-handles-all

For a typical 5-chunk multi-faceted prompt (recon + design + two
impls + security), output token totals roughly:

|                     | Tokens | Model           | Cost     |
|---------------------|--------|-----------------|----------|
| Recon               |   250  | Haiku           | $0.001   |
| Two impl chunks     |  1200  | Sonnet          | $0.018   |
| Architecture chunk  |  1700  | Opus high       | $0.043   |
| Security chunk      |  2200  | Opus xhigh      | $0.055   |
| **Total decomposed**|        |                 | **$0.12**|
| Same in main Opus   |  7000  | Opus xhigh      | $0.18    |
| **Saved per prompt**|        |                 | **~$0.06** (33%) |

Wall-clock also drops because independent chunks run in parallel.

### Explicit invocation

The slash command `/router-plan <task>` forces decompose mode for a
specific request even if Claude wouldn't have chosen it
automatically.

## Subagent dispatch (the actually-working layer)

Per-tool model override is best-effort — Claude Code's runtime may
ignore the `model_override` field returned from PreToolUse hooks.
The real, runtime-respected mechanism for model selection is the
`model:` frontmatter on subagent definitions in `.claude/agents/`.

This plugin ships **five pre-configured router subagents**. When you
spawn a subagent via the `Task` tool, dispatch by content tier:

| Subagent          | Model       | Use for                                         |
|-------------------|-------------|-------------------------------------------------|
| `recon-haiku`     | Haiku 4.5   | read-only recon, search, grep, list, locate     |
| `impl-sonnet`     | Sonnet 4.6  | default — single/2-file edits, tests, fixes     |
| `api-sonnet`      | Sonnet 4.6  | endpoints, routes, third-party integrations     |
| `architect-opus`  | Opus 4.7    | multi-file refactors, redesigns, perf, subtle bugs |
| `secure-opus`     | Opus 4.7    | MANDATORY for auth/secrets/crypto/migrations    |

### Dispatch decision

When you would otherwise spawn `Task` with `subagent_type:
"general-purpose"`, instead pick one of the five above:

1. If the prompt mentions **auth, password, secret, api_key, token,
   crypto, encrypt, decrypt, hash, migration, sql schema, production,
   deploy, .env, ssl, tls** → **always** `secure-opus`. No exceptions.
2. Else if the prompt mentions **architecture, design pattern,
   refactor entire, redesign, optimize, bottleneck, performance,
   review all** → `architect-opus`.
3. Else if the prompt is about a new **endpoint / route / API
   integration** → `api-sonnet`.
4. Else if the prompt asks to **find / locate / list / search /
   explore** without modifying anything → `recon-haiku`.
5. Else → `impl-sonnet` (default).

The PreToolUse hook **enforces rule 1** — a sensitive Task dispatch
to any non-opus subagent triggers `permissionDecision: "ask"` with a
recommendation to switch to `secure-opus`. Other rules are advisory.

## Slash commands — three one-click presets

The user picks **one** preset per conversation. Each is a single
slash command. Tradeoff is explicit: token savings vs accuracy.

| Slash command       | Accuracy | Token savings | Use for                            |
|---------------------|----------|---------------|------------------------------------|
| `/router-eco`       | 95%      | ~90% saved    | exploration, prototypes, sketches  |
| `/router-balanced`  | 99%      | ~50% saved    | day-to-day work (default)          |
| `/router-quality`   | 99.9%    | ~20% saved    | production, security, finals       |

If the user has not picked a preset and the current `mode` in
`router-config.json` is the default `balanced`, leave it alone. If
the user expresses cost sensitivity ("just exploring", "cheap as
possible", "don't care if it's a bit off") suggest `/router-eco`.
If they signal high stakes ("production deploy", "this is shipping",
"can't be wrong") suggest `/router-quality`.

### Other commands

- `/smart-router-set <fast|balanced|precise|max|<num>>` — fine-grained
  mode setting (kept for power users; the three presets above cover
  most cases).
- `/smart-router-status` — current mode + active thresholds + session
- `/smart-router-report` — full session breakdown with progress bars

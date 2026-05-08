# ATrain Claude

> *"I'm A-Train. The fastest router alive."*
> — said no one yet, but routing decisions in <50ms anyway

ATrain is a Claude Code plugin that orchestrates Haiku, Sonnet, and Opus
subagents in parallel via the Task tool — so routine work runs cheap and
fast while security work stays on Opus xhigh. No Compound V required,
just your existing Claude Code subscription.

## Pick a mode, type tasks, save bundled tokens

```
/atrain-on          arm fan-out for the whole conversation
/atrain-eco         95% accuracy, ~70-90% tokens saved (recon-heavy)
/atrain-balanced    99% accuracy, ~50% saved (default)
/atrain-quality     99.9% accuracy, ~20% saved (production code)
/atrain-kill        disarm. ATrain takes a break in his trailer.
```

Three steps. ATrain does the rest.

## How it works (plain English)

Don't let your expensive smart Claude (Opus) do dumb work. Send dumb
work to a cheap fast Claude (Haiku) running in parallel. Same
subscription. Quality stays.

```
Without ATrain:
  Opus → Read 12 files → Grep → Read again → think → write fix
  Sequential. Slow. Lots of bundled tokens.

With ATrain:
  Opus → spawns recon-haiku (Haiku, fast)
       └─ "find TODOs, return file:line"
  Opus → spawns impl-sonnet (Sonnet, mid)
       └─ "classify priority"
  Opus → merges + writes the fix (this is what Opus is FOR)
  
  Parallel. ~30% of the tokens. Quality unchanged because only
  the boring work moved off Opus.
```

ATrain runs hot, but he doesn't burn through your subscription.

## What stays on Opus xhigh, no matter what

The router doesn't compromise on these. Hard-escalation keywords scanned
on every tool call:

`auth · password · secret · api_key · jwt · bcrypt · argon2 · scrypt ·
hmac · webhook signature · cors · csrf · sql injection · sanitize · xss ·
db migration · alter table · drop column · drop table · .env · ssl · tls ·
oauth · to production · main branch ·` (47 total, word-boundary regex)

Even ATrain knows when to slow down. Compound V isn't worth it for a
prod deploy.

## Install (5 minutes, no Compound V)

```bash
git clone https://github.com/Metrcih/atrain-claude.git
cd atrain-claude
./install.sh        # installs to ~/.claude/, merges hooks, no overwrites
```

That's it. Restart Claude Code, type `/` in any project, the picker shows
ten `/atrain-*` commands.

Uninstall: `./uninstall.sh` cleans files + detaches hook entries without
touching the rest of your settings. Fast in, fast out — that's how
ATrain rolls.

## Subagents

ATrain ships with five tiered subagents, each running on a specific model
via Claude Code's `model:` frontmatter (real swap, runtime-honored):

| Subagent          | Model      | When ATrain dispatches it           |
|-------------------|------------|--------------------------------------|
| `recon-haiku`     | Haiku 4.5  | finding/listing/grepping             |
| `impl-sonnet`     | Sonnet 4.6 | small-to-mid edits, tests            |
| `api-sonnet`      | Sonnet 4.6 | endpoints, routes, integrations      |
| `architect-opus`  | Opus 4.7   | refactors, design, perf              |
| `secure-opus`     | Opus 4.7   | auth, secrets, crypto, migrations    |

Internal names. Users don't pick agents — ATrain dispatches them based
on the active mode's routing table.

## Honest accounting (v4.0+)

Hook output advisory only — the Claude Code runtime ignores any
`model_override` field a hook returns. Real per-call model swap on
bundled-token subscriptions only happens via subagent dispatch (Task
tool with `subagent_type`). ATrain knows the difference:

```
real_subagent_calls / real_savings_usd
  Credited only when Task dispatch fired. These savings are real.

advisory_calls / advisory_savings_usd
  Main-session calls where ATrain advised cheaper but runtime ignored.
  Aspirational.
```

`/atrain-status` shows both. Pick the column that matches your honesty
budget.

## Benchmarks

Two test harnesses ship with the repo. Run any of them:

```bash
# Synthetic projection across 3 workloads (cheap, no API calls)
python3 tools/evals/three_workloads_bench.py

# Classifier accuracy against labeled corpus (no API calls)
python3 tools/evals/run_eval.py
# expected: 108/108 (100%)

# REAL bench — fires actual `claude -p` subprocesses
# costs ~$0.30-1 of bundled-token quota for full run
python3 tools/evals/atrain_bench.py --quick
```

The real bench captures live `input_tokens`, `output_tokens`, cache reads,
`total_cost_usd`, and `duration_ms` from Claude Code's CLI output. Output
similarity vs single-Opus baseline measured by token-set Jaccard.

## CLI tools

```
python3 .claude/hooks/router.py --test          # 36/36 self-tests
python3 .claude/hooks/router.py --health-check  # 6-check audit, GREEN/DEGRADED
python3 .claude/hooks/router.py --print-rules   # dump all classifier keywords
python3 .claude/hooks/router.py --lint-skill    # check SKILL.md vs classifier
python3 .claude/hooks/router.py --cache-stats   # tool-result cache hit rate
python3 .claude/hooks/router.py --update-models # refresh from Anthropic API
```

## State of the plugin

```
Tests:       36/36 pass
Eval:        108/108 (100%) on labeled corpus
Health:      GREEN (6/6 checks)
Audit:       0 open findings, 0 known bugs
Patterns:    7 of 12 deep-research patterns shipped
CI:          matrix Python 3.11/3.12/3.13 + lint + eval gate
Latency:     ~45ms per hook call, never blocks
Stdlib only: yes (sqlite3 + fcntl included free)
```

## What ATrain doesn't do

- Beat Compound V (we use bundled tokens, much cheaper)
- Per-tool-call main-session model swap (runtime ignores hook overrides;
  real swap is via Task subagent dispatch)
- Replace your `/model` choice (still your call; ATrain orchestrates
  underneath)
- Pretend to save tokens it didn't (v4.0+ separates real from advisory)

## License

MIT — see [LICENSE](LICENSE).

---

ATrain runs fast. ATrain doesn't apologize. ATrain doesn't fight Black
Noir, but he routes your tool calls in under 50ms. Pick a mode, kick
back, watch the bundled-token meter slow down.

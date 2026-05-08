# ATrain v5.0 + v5.1 roadmap — what shipped, what's deferred

**Date**: 2026-05-08
**Driving research**:
[deep-research report](../../../Documents/SmartRouter_Hybrid_Research_20260507/report.md)
plus 3 parallel-subagent audit dispatched 2026-05-08

## Shipped in v5.0

### Pattern 11 — Aggressive Task forcing in eco mode

**What**: When `mode == "eco"` AND `force_subagent_recon == true`,
the PreToolUse hook returns `permissionDecision: "ask"` on
`Read / LS / Glob / Grep` with a reason that names the suggested
subagent + ready-to-run `Task(subagent_type=..., prompt=...)` shape.

**Why**: real bench (v4.1.0) showed eco mode delivered only -1% to
-3% cost vs single-Opus baseline because hook advisories alone do
not swap the model the runtime uses. The only path to the marketed
~70-80% recon savings is forcing Claude to dispatch via Task, which
the runtime DOES honor (model frontmatter on subagent files). The
"ask" permission decision is mildly intrusive but every approval
the user grants on the parent session is a measurable opportunity
cost they explicitly accepted.

**Config**: `force_subagent_recon: bool` (default `false`). Eco
preset card opts in; balanced and quality leave it off.

**Test**: T39.

### Pattern 10 — Negative-Cache Short-Circuit

**What**: New `route_failures` SQLite table keyed on
`(blake2b_8(prompt[:512]), alias)`. When a tool call's PostToolUse
fires with `had_error` or output-verify rejection, the
(fingerprint, alias) is recorded with a 24h TTL. `classify_to_agent`
checks the cache at entry; if the chosen agent has a recent failure
on a similar prompt, it upshifts one tier per the
`recon-haiku → impl-sonnet → api-sonnet → architect-opus → secure-opus`
chain.

**Why**: avoids burning the speculative draft on prompts the system
already learned the cheap model cannot handle. Prior research
(architect-opus subagent, 2026-05-08): expected 5-12% additional
savings on repetitive workflows by reducing wasted draft-verify
cycles.

**Storage**: extends existing `~/.claude/router-cache.sqlite`. New
table created idempotently in `_cache_conn`. Stdlib only (sqlite3).

**Test**: T37, T38.

## Deferred to v5.1+ — research-grade patterns with real ROI

### Pattern 8 — Speculative Haiku-First Draft + Sonnet Verify

**Source**: architect-opus subagent (2026-05-08), inspired by
classic speculative-decoding pattern (BentoML handbook, 2026)
adapted for routing.

**What**: For tool calls scored as `sonnet|low`, dispatch a Haiku
draft via Task in parallel with a structural rubric check
(`json_schema | py_compile | regex`). If draft passes the rubric
(compiles / parses / matches), commit; else re-run on Sonnet.

**Why deferred**: requires building and validating verifier
infrastructure per output type. The verifier dispatch logic alone is
nontrivial — has to know the expected target syntax for the call.
Estimate: 2-3 days of careful work plus an eval set covering the
pass-rate distribution.

**Expected savings**: 8-15% additional on Edit/Write-heavy sessions,
net positive only when verifier pass rate >70%.

### Pattern 9 — Context-Window Compaction via Rolling Summary

**Source**: architect-opus subagent (2026-05-08).

**What**: Track cumulative input-token estimate per session in the
existing SQLite cache. When estimate crosses 60k, inject a digest
directive into the next PreToolUse hook output that triggers Haiku
to summarize older tool outputs into a 500-token digest, replacing
them in subsequent prompts. Distinct from sub-thread distillation
(which condenses inside a Task) — this condenses the *parent thread*.

**Why deferred**: highest expected ROI (12-25% on long sessions
>20 turns) but also highest session-state risk. Incorrect
summarization silently degrades quality. Needs an A/B opt-in
flag plus a quality-regression eval before default-on.

**Expected savings**: 12-25% on long sessions. Targets the dominant
cost line on bundled-token plans (cumulative input tokens).

### Pattern 12 — MoA-Lite for /atrain-quality mode

**Source**: research dispatched 2026-05-08; underlying paper
[Wang et al. 2024 "Mixture of Agents"](https://arxiv.org/abs/2406.04692).
MoA-Lite (2 layers, smaller aggregator) reportedly beat GPT-4 Omni
on AlpacaEval (59.3% vs 57.5%) at lower cost than full MoA.

**What**: For `/atrain-quality` prompts crossing complexity
threshold, dispatch 2-3 parallel `architect-opus` subagents with
slightly varied framings (e.g., "design the simplest possible
solution", "design the most robust solution"), then have main
session synthesize. Distinct from current decompose mode because
chunks intentionally OVERLAP rather than partition.

**Why deferred**: the synthesizer prompt design is non-trivial.
Requires careful prompt engineering to make the aggregator extract
the best of each variant rather than averaging.

**Expected savings**: not a savings pattern — a quality pattern.
For users who chose `/atrain-quality`, this delivers measurably
better output than single-Opus xhigh at modest cost increase.

### Pattern 13 — Tool Search-style classifier optimization

**Source**: [Anthropic Tool Search blog post](https://www.anthropic.com/engineering/advanced-tool-use)
(reports Opus 4 tool-selection accuracy 49% → 74%, 85% reduction
in tool-definition tokens).

**What**: Apply Tool Search's `defer_loading: true` principle to
ATrain's own classifier. Currently every PreToolUse hook fires the
full 47-keyword sensitive scan + 9-arch-keyword + 9-api-keyword
batch. Restructure as: cheap fast-path (tool_name + length) →
expensive scan only when fast-path uncertain. Reduces hook latency
from ~45ms to ~15ms on ~70% of calls.

**Why deferred**: current hook latency (~45ms) is comfortably under
the 50ms budget. Optimization is real but not urgent. Worth shipping
together with v5.1 architectural changes for one cohesive release.

**Expected savings**: latency only, ~30ms per call × hundreds of
calls per session = noticeable cumulative wall-time reduction.

## Survey of newer/lesser-known repos worth watching

From research dispatched 2026-05-08:

- [LightCompress](https://github.com/ModelTC/LightCompress) (EMNLP
  2024 / AAAI 2026) — multimodal compression toolkit, ~20 algorithms.
  Not Claude-specific.
- [Awesome-LLM-Compression](https://github.com/HuangOwen/Awesome-LLM-Compression)
  — curated list, useful for tracking.
- [TogetherCompute MoA](https://github.com/togethercomputer/MoA) —
  reference implementation of the MoA paper. OSS-only models, but
  the architecture pattern ports.
- [Anthropic Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)
  — adjacent technique for RAG; not directly applicable to a
  pure-routing plugin.
- [Stacklok MCP Optimizer](https://stacklok.com/blog/stackloks-mcp-optimizer-vs-anthropics-tool-search-tool-a-head-to-head-comparison/)
  — third-party tool-search competitor. Same `defer_loading` idea
  with different ranking.

## Patterns ruled out (and why)

- **claude-code-router** — sets `ANTHROPIC_BASE_URL` away from
  Claude Code's runtime, breaks bundled-token economics. Forces
  user onto API-credit billing. Plugin author position: too
  expensive a tradeoff for users on Pro/Max subscriptions.
- **LLMLingua / LLMLingua-2** — requires BERT model in memory,
  breaks stdlib-only invariant. Could ship as optional `[compress]`
  install extra in v5.2+.
- **DSPy / MIPRO compilation** — needs DSPy package and a labeled
  eval corpus 5-10× larger than current 108-case set. Worth
  pursuing once v5.1 patterns ship and a 500+ case corpus exists.
- **Speculative decoding** (token-level draft/target) — blocked
  on Anthropic exposing a draft-target API. Different from
  Pattern 8 above (which is route-level speculation, not
  token-level).

## Test coverage state

```
Tests:   39/39 pass (T01-T39)
Eval:    108/108 (100%) on labeled corpus
Health:  GREEN
CI:      matrix Python 3.11/3.12/3.13 + lint + eval gate
```

## Realistic next 4 weeks

| Week | Pattern | Effort | Risk |
|------|---------|--------|------|
| 1    | Pattern 13 (classifier fast-path) | 1 day | Low |
| 1-2  | Pattern 8 (Speculative Haiku) | 2-3 days | Medium |
| 3    | Pattern 12 (MoA-Lite for quality) | 3-4 days | Medium |
| 4    | Pattern 9 (Context compaction) | 4-5 days, opt-in | High |

Or pause at v5.0 and ship a real-bench A/B on the v4.x → v5.0 delta.

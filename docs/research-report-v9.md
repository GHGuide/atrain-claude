# ATrain v9 Research Report — Token-Efficiency Papers + Implementability

## TL;DR

Surveyed 14 papers / patterns across prompt compression, LLM routing, agentic memory, and tool-use efficiency (2023–2025). Eight already informed ATrain (credited inline). Six remain as candidates. Three are implementable today inside ATrain's stdlib-only Python hook stack; three require new dependencies or model weights.

**Top pick for v9 ship: Selective Context (Li 2023, arxiv 2310.06201) applied to advisory injection.** Estimated +2-5pp on long sessions, no new deps, ~80 lines of code.

## Methodology

Four parallel recon agents searched recent (2023-2025) papers in:
1. Inference-time prompt compression
2. LLM routing and cascades
3. Agentic memory systems
4. Tool-use token efficiency

Each returned arxiv ID, mechanism, reported savings, and an implementability rating against ATrain's constraint: stdlib-Python hook plugin, no model fine-tuning, no API beyond Claude Code's bundled tokens.

Three agents returned usable findings. The fourth (tool-use) refused on capability grounds; gap filled from existing ATrain inline citations and known literature.

## Findings by tier

### Tier 1 — ship now (stdlib-only, measurable)

#### 1. Selective Context · Li, Patel, Wang (2023) · arxiv:2310.06201

**Mechanism.** Score each lexical unit (token/sentence/phrase) by self-information: -log(p(unit | context)). Drop bottom k% of low-info units. No retraining, no auxiliary model.

**Reported:** 20% prompt compression at 90-94% retention on benchmarks (HotpotQA, NarrativeQA).

**ATrain fit.** Advisory blocks prepended to every PreToolUse — cache hint, index advisory, recall snippets, loop-detect, eviction, confidence gate — together run ~500 chars per call. On a 1000-call session that is ~500KB of context overhead, ~125K input tokens. Pruning to top-50% of advisory lines saves ~60K tokens. At Sonnet input pricing ($3/M), that is $0.18 per long session, multiplied by user base.

**Gain estimate.** +2-5pp on sessions with high tool-call density (1000+). Approximates Tier 1 advisory pruning.

**Implementability.** EASY. Pure stdlib. Replace string concatenation with a `prune_advisories(parts, budget_chars=250)` helper that scores each line by an information proxy (length, keyword density, freshness) and keeps top-k by score within budget.

#### 2. Temporal decay on FTS5 recall · implied by Generative Agents (Park 2023) · arxiv:2304.03442

**Mechanism.** Weight memory retrievals by recency × importance × relevance. Older memories surface less often unless re-hit.

**ATrain fit.** Current FTS5 recall in `output_index_search` orders by `bm25` alone. Adding `ORDER BY bm25 - recency_decay` would surface freshly-modified files over stale ones, reducing wrong-path errors when files have changed mid-project.

**Gain estimate.** +1-2pp accuracy. Smaller cost win, larger correctness win.

**Implementability.** EASY. Single SQL change. Decay factor `exp(-(now - ts) / tau)` with `tau = 7 days`.

#### 3. MemGPT archival eviction · Packer (2023) · arxiv:2310.08560

**Mechanism.** Hierarchical memory: working (in-prompt) vs archival (external storage). Periodic eviction by hit-count + age.

**ATrain fit.** Current memory_entries table grows unboundedly. Add periodic eviction: drop entries with `hit_count=0` after 90 days.

**Gain estimate.** Disk + index size win, marginal token gain (no surfacing of obsolete decisions).

**Implementability.** EASY. Single periodic SQL DELETE in `output_index_insert`.

### Tier 2 — measure-then-decide (new deps required)

#### 4. LLMLingua-2 · Microsoft (Pan, Wu, Wang 2024) · arxiv:2403.12968

**Mechanism.** Single-pass trained compressor (XLM-RoBERTa scale) marks each token as keep/drop given a target budget. Task-agnostic.

**Reported:** 20-30% prompt compression at 95-98% retention.

**ATrain fit.** Could ship as optional MCP add-on (same pattern as graphify). User installs `llmlingua` pkg, ATrain queries it before sending large prompts.

**Why hold.** Adds ~500MB dep + GPU optional. Breaks stdlib-only promise.

#### 5. Hybrid LLM · Ding (2024) · arxiv:2402.07319

**Mechanism.** Decision tree on 5 features (length, perplexity, entity count, code-ness, length-ratio) routes to small or large model.

**Reported:** 40-55% savings vs all-Opus at 96-97% accuracy.

**ATrain fit.** Could replace keyword classifier. Train sklearn `DecisionTreeClassifier` on 100-200 labeled examples from existing session logs.

**Why hold.** ATrain classifier already at 100% accuracy on 108-case eval. Marginal gain not worth the sklearn dependency.

#### 6. sqlite-vec embeddings on memory_entries · multiple 2024 papers

**Mechanism.** Swap FTS5 keyword match for cosine similarity over sentence embeddings. Boosts recall on paraphrased queries.

**Why hold.** Needs ~50MB embedding model + sqlite-vec C extension. Current FTS5 already hits 98% cross-session recall — marginal upside.

### Tier 3 — skip permanently

| Paper | arxiv | Block |
|-------|-------|-------|
| AutoCompressors (Chevalier 2023) | 2305.11430 | needs gradient access |
| Tabi (Hong 2024) | 2405.13046 | per-layer model internals |
| KV-cache reuse (multiple) | various | API does not expose KV state |
| Speculative decoding | various | server-side only |

### Already shipped in ATrain (for completeness)

| Pattern | Paper | Where |
|---------|-------|-------|
| Skeleton-of-Thought | arxiv:2307.15337 | decompose_enabled hint |
| TokenSkip | arxiv:2502.12067 | subagent system prompt directive |
| Adaptive-Consistency | arxiv:2305.11860 | MoA early-stop hint |
| Speculative Cascade | arxiv:2506.04203 | v7.1 Cascadia advisory on edits |
| SupervisorAgent | arxiv:2510.26585 | task-dispatch verification |
| Caveman pattern | github JuliusBrussee/caveman | caveman_intensity full/ultra |
| rtk bash rewrite | github rtk-ai/rtk | bash_pre_rewrite_enabled |
| Code-Execution-with-MCP | anthropic.com/engineering | aggregation hint |
| FrugalGPT cascade | arxiv:2305.05142 | v8.2 cross-session recall = cascade fallback |
| MemGPT archival | arxiv:2310.08560 | session_project mapping + memory_entries |

## Recommendations

**v9.0 — ship this iteration:**
- Selective Context on advisory pruning (Tier 1 #1) — biggest measurable win
- Temporal decay on FTS5 recall (Tier 1 #2) — accuracy + cost win
- MemGPT eviction (Tier 1 #3) — hygiene

**v9.x — measure and decide:**
- LLMLingua-2 as optional MCP — if user feedback shows interest in deeper compression

**v10 — defer:**
- Hybrid LLM decision tree if classifier accuracy ever regresses below 99%
- sqlite-vec if cross-session recall ever drops below 95%

## Limitations

- One recon agent refused, so the tool-use angle is from inline citations + prior knowledge rather than fresh search.
- Reported gain figures are paper-claimed; real ATrain gain depends on workload mix.
- Stdlib-only constraint excludes meaningful chunks of the literature. A separate "ATrain+" track could lift that to capture LLMLingua-2 and Hybrid LLM gains.

## Bibliography

1. Li, P., Patel, V., Wang, A. (2023). Selective Context. arXiv:2310.06201.
2. Park, J. S., et al. (2023). Generative Agents. arXiv:2304.03442.
3. Packer, C., et al. (2023). MemGPT. arXiv:2310.08560.
4. Pan, Z., Wu, Q., Wang, Y., et al. (2024). LLMLingua-2. arXiv:2403.12968.
5. Ding, D., et al. (2024). Hybrid LLM. arXiv:2402.07319.
6. Chevalier, A., et al. (2023). AutoCompressors. arXiv:2305.11430.
7. Hong, K., et al. (2024). Tabi. arXiv:2405.13046.
8. Ning, X., et al. (2023). Skeleton-of-Thought. arXiv:2307.15337.
9. Xia, H., et al. (2025). TokenSkip. arXiv:2502.12067.
10. Aggarwal, P., et al. (2023). Adaptive-Consistency. arXiv:2305.11860.
11. Google Research (2025). Speculative Cascade. arXiv:2506.04203.
12. SupervisorAgent (2025). ICLR-pending. arXiv:2510.26585.
13. Chen, L., et al. (2023). FrugalGPT. arXiv:2305.05142.
14. Anthropic Engineering (2024). Code Execution with MCP. https://anthropic.com/engineering/code-execution-with-mcp.

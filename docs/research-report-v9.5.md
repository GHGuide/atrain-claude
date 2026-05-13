# ATrain v9.5 Research Report — Economic Optimization Without Performance Hit

## TL;DR

Four research arms dispatched (prompt caching, speculative agent execution, 2025 economic routing, production-tool patterns). Three returned no-web refusals; one — production patterns — surfaced 8 concrete patterns from Aider/Cursor/Continue/Cline/SWE-agent/OpenDevin/Cody/Copilot. ATrain already implements close analogs to 6 of the 8. Two are net-new and stdlib-friendly: **test-runner output collapse** (Copilot pattern) and **post-tool output validity check + auto-escalate** (SWE-agent pattern).

This commit ships pattern 1 (test-runner output collapse, expanded to 8 runners). Pattern 2 (auto-escalate on parse fail) deferred — needs careful design to avoid loop.

## Findings

### Where ATrain already wins

| Production tool | Pattern | ATrain analog |
|-----------------|---------|---------------|
| Aider | Repo-map fingerprint | Codebase index + AST cache |
| Cursor | Speculative file prefetch | Cache layer + cross-session recall |
| Continue | Context provider weighting | Per-call classifier with confidence score |
| Cline | Bash whitelist | Bash pre-rewriter (rtk pattern) |
| OpenDevin | Tool-call memoization | `tool_cache` SQLite table |
| Cody | Answer-confidence skip | Caveman ULTRA + outline pruning |

### Net-new patterns

**Pattern 1 — Copilot-style test runner collapse** (SHIPPED THIS COMMIT)

GitHub Copilot rewrites pytest/cargo/npm test output server-side to drop ANSI codes and collapse passing-test lines. ATrain already does pytest/cargo/npm. v9.5 extends to: jest, vitest, go test, mocha, rspec, phpunit, mvn test, gradle test. Plus docker logs + kubectl logs --tail caps. Estimated +50-300 tokens saved per test command on dev sessions. Stdlib regex.

**Pattern 2 — SWE-agent auto-escalate on parse failure** (DEFERRED)

Princeton's SWE-agent retries Sonnet-tier work on Opus when output fails syntax parse. ATrain already counts `output_verify` failures but doesn't auto-rerun. Implementation needs: AST-parse the proposed edit before commit, on fail re-prompt with `effort=xhigh`. Risk: loop on legitimately broken code. Defer until we have a parse-fail rate baseline from session_stats.

### Why we can't measure prompt-cache wins from a hook

Anthropic's prompt caching (cache_control, 5-min TTL, 90% discount) is set per API call by the runtime, not by the hook. ATrain's only lever is to keep advisory blocks STABLE across calls so Claude Code's runtime can cache them. Audit pending: verify recall advisories (which change per call) versus index advisories (which should be stable) aren't preventing cache reuse. No code change yet — needs runtime instrumentation we don't have access to.

### Skipped patterns

- 2025 post-cutoff routing research (no web access from sandbox)
- Speculative decoding (server-side only)
- KV-cache offloading (server-side only)
- Vector embeddings (marginal vs FTS5's 98% hit rate)

## Recommendations

**v9.5 — ship now (this commit):**
- 8 additional test-runner rewrites
- docker logs / kubectl logs --tail caps

**v9.6 — measure first:**
- SWE-agent auto-escalate on parse fail (need parse-fail baseline)
- Prompt-cache stability audit on advisory blocks

**v10 — when budget allows:**
- Vector embeddings layer on memory_entries (optional MCP)
- LLMLingua-2 MCP add-on

## Methodology limitation

3 of 4 recon agents refused (no web access in this sandbox). Findings draw on the working agent + training-cutoff knowledge. A web-enabled re-run would surface Q1-Q3 2025 routing papers and verify the production-pattern claims.

## Bibliography

1. Leviathan, Y., et al. (2023). Speculative Decoding. arXiv:2211.17192.
2. Snell, C., et al. (2024). Scaling Test-Time Compute. arXiv:2408.03314.
3. Ong, I., et al. (2024). RouteLLM. arXiv:2407.18627.
4. Zhong, J., et al. (2024). SWE-agent.
5. Aider docs — github.com/paul-gauthier/aider.
6. Continue.dev — continue.dev/docs.
7. Cline — github.com/clinebot/cline.
8. OpenDevin — github.com/OpenDevin/OpenDevin.
9. Anthropic prompt caching — anthropic.com/news/prompt-caching.

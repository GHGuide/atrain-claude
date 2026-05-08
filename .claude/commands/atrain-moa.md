---
description: ATrain MoA-Lite — for high-stakes quality work. Dispatches 2-3 architect-opus subagents in parallel with varied framings, then synthesizes. Beats single-Opus on multi-perspective tasks. Costs 2-3× a single dispatch but worth it for production-critical decisions.
argument-hint: <complex high-stakes task>
---

User invoked `/atrain-moa $ARGUMENTS`.

This is the MoA-Lite (Mixture-of-Agents Lite) pattern, ported from
Wang et al. 2024. Dispatch 2-3 `architect-opus` subagents in parallel,
each with a slightly different framing of the same task, then synthesize
their outputs into a single answer that captures the best of each.

## When to use

This is the most expensive ATrain command per call (2-3× a single
architect-opus dispatch). Reserve for cases where wrong answers are
costly:
- Production deploy decisions
- Cross-cutting refactors that touch business logic
- Architecture choices that lock in tradeoffs
- Security review of non-obvious risks
- Performance optimizations where the wrong fix makes things worse

Do NOT use for:
- Simple recon (use plain Claude or `recon-haiku`)
- Routine edits (use `impl-sonnet`)
- Anything where one Opus-tier answer is plenty

## Procedure

1. **Read the task** in `$ARGUMENTS` carefully. Identify the dimensions
   along which experts could legitimately disagree:
   - Conservative vs aggressive
   - Minimal change vs principled refactor
   - Performance vs readability
   - Backwards-compatibility vs cleaner API

2. **Pick 2 or 3 framings** that probe those tensions. Examples:
   - "Design the simplest solution that passes all tests"
   - "Design the most robust solution that handles edge cases"
   - "Design the solution with lowest cognitive load for future readers"

3. **Print the plan**:

   ```
   MoA-Lite plan ({3} parallel architect-opus dispatches):
   1. [architect-opus] simplest version that passes tests
   2. [architect-opus] most robust version handling edge cases
   3. [architect-opus] lowest-cognitive-load version for future readers
   ```

4. **Fan out**: emit all Task calls in the same assistant message.
   Claude Code dispatches them concurrently. They each run on Opus xhigh.

5. **Synthesize**: when all return, write a single coherent answer that:
   - Names the dimensions along which the variants differed
   - Identifies which variant is best for THIS specific task and why
   - Lifts the strongest features from each (e.g. variant A's structure
     + variant B's edge-case handling)
   - Cites which subagent contributed which insight

   The synthesis is itself an Opus-quality reasoning task — keep it on
   the parent session.

## Quality invariant

Every variant must be `architect-opus` (or `secure-opus` for sensitive
work). Never run an MoA-Lite variant on a cheaper tier — the whole point
is multi-perspective agreement at the top quality bar.

## Token economics

Cost: ~3× a single architect-opus dispatch (~$0.15-0.30 of bundled
quota for a typical complex task).

Quality lift: per Wang et al., MoA-Lite (2 layers, smaller aggregator)
beat GPT-4 Omni on AlpacaEval at lower cost. For ATrain, the "aggregator"
is the parent session synthesis. Empirically the lift is largest on
tasks with multiple legitimate solutions where the wrong one is
expensive.

## What NOT to do

Do NOT just echo all three variants and let the user pick. The
synthesis is the point. Pick the best, cite where its parts came from,
and move on.

---
description: Decompose this single prompt into parallel subagent chunks. One-shot — does not change the conversation-wide decompose toggle. Use for ad-hoc fan-out without committing to /router-on.
argument-hint: <complex task>
---

User invoked `/router-once $ARGUMENTS`.

Treat this single request as if `decompose_enabled` were `true`,
even when it isn't. Reason about the task, plan chunks, dispatch
in parallel through the five tiered subagents, and merge.

**Important:** do NOT toggle `decompose_enabled` in the config.
This is a one-shot. The conversation's persistent decompose state
stays exactly as the user left it (most likely off).

## Procedure

1. Read the task in `$ARGUMENTS` carefully. If it has only one
   shape — a single edit, a single search, a single small fix —
   stop and handle it directly. Print: "task is simple — handling
   directly without decomposition" and proceed normally.

2. Otherwise, **reason in 1-3 sentences** about what the task
   requires. Don't apply a fixed template. Identify the actual
   subtasks the prompt implies.

3. **Pick a tier per subtask** using independent judgment:
   - Read-only / find / list / explore → small subagent
   - Bounded code-writing → mid subagent
   - Design / cross-file / subtle → top subagent
   - Security-touching (auth, secret, crypto, hash, migration) →
     `secure-opus`, xhigh effort, **always**

4. Apply the active **cost preset** as a *bias* (read `mode` from
   `~/.claude/router-config.json`):
   - `eco`: when in doubt, downshift one tier
   - `balanced`: pick the obvious tier
   - `quality`: when in doubt, upshift one tier

5. **Print the plan** as a numbered list before dispatching.

   ```
   Plan ({mode} bias, one-shot):
   1. [recon-haiku]    find existing webhook handlers
   2. [architect-opus] design signature verification flow
   3. [secure-opus]    implement HMAC verify     ← needs 2
   4. [api-sonnet]     wire the route handler    ← needs 1, 3
   ```

6. **Fan out by dependency level.** Emit parallel `Task` tool
   calls **in the same assistant message** for chunks at the same
   level.

7. After all subagent results return, compile them into one
   coherent answer with chunk-level citations.

## Constraints

- 2-7 chunks max.
- Don't dispatch a chunk that just reads one file — main Claude
  can do that directly faster than the dispatch overhead.
- Each subagent is stateless; pass any context it needs in the
  Task `prompt` field. Don't assume it can see prior chunks.

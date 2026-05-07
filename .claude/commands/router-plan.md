---
description: Decompose-and-dispatch — explicitly split a complex prompt into parallel subagent chunks, run them concurrently, then merge. Use when you want forced fan-out for a multi-faceted task.
argument-hint: <complex task>
---

User invoked `/router-plan $ARGUMENTS`.

Decompose this task into parallel chunks dispatched through the
five smart-router subagents, then merge the results.

## Procedure

1. **Read the task carefully.** Identify 3 to 7 distinct concerns.
   A "concern" is a piece of work that can be reasoned about
   independently and produces a self-contained result.

2. **Plan.** Write a numbered markdown list. Each entry has:
   - The chunk's task in one sentence
   - The assigned subagent (`recon-haiku`, `impl-sonnet`,
     `api-sonnet`, `architect-opus`, or `secure-opus`)
   - A `← needs N` marker for dependencies, if any

3. **Print the plan.** Show it to the user before dispatching.
   Example:

   ```
   Plan:
   1. [recon-haiku]    find existing auth middleware
   2. [architect-opus] design rate-limit strategy
   3. [secure-opus]    implement bcrypt password hashing   ← needs 1
   4. [impl-sonnet]    wire the route handler              ← needs 1, 2, 3
   ```

4. **Fan out by dependency level.** For all chunks at the same
   level (no unfulfilled deps), emit parallel `Task` tool calls
   **in the same assistant message**. Claude Code runs them
   concurrently. Wait for results before dispatching the next
   level.

5. **Merge.** Compile the subagent outputs into a single coherent
   final answer. Cite which chunk produced which finding so the
   user can audit. If any chunk failed, surface the error and
   stop — don't paper over it.

## Agent selection

| Subtask shape                          | Agent             |
|----------------------------------------|-------------------|
| find / locate / list / search / where  | recon-haiku       |
| write small file / edit / fix bug      | impl-sonnet       |
| add endpoint / route / integration     | api-sonnet        |
| refactor / design / multi-file changes | architect-opus    |
| security/secret/crypto/migration       | secure-opus       |

## Constraints

- Maximum 7 chunks. Past that, the merge step gets noisy.
- Don't dispatch a chunk that just reads one file — main Claude
  can do that itself faster than the dispatch overhead.
- If the task has only one or two distinct concerns, abandon the
  plan and handle it directly. Print: "task is simple enough —
  handling directly without decomposition" and proceed.
- Each subagent is stateless; pass any context it needs in the
  Task `prompt` field. Don't assume it can read prior chunks.

## What success looks like

- Plan printed to the user before any dispatch.
- Independent chunks run in parallel (multiple Task calls in the
  same message).
- Final answer cites chunks (e.g. "from chunk 2 (architect-opus):
  ..." ) so the user can audit cost vs value.
- `/smart-router-report` afterwards shows the dispatch counts.

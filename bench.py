#!/usr/bin/env python3
"""smart-router benchmark — runs 10 representative prompts and reports."""
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
HOOK = ROOT / ".claude" / "hooks" / "router.py"
CONFIG = ROOT / ".claude" / "router-config.json"

# Reset config + clean session logs
os.system(f'rm -f /tmp/smart-router-bench-*.json 2>/dev/null')

PROMPTS = [
    {
        "label": "T01 small Read",
        "expected": "haiku",
        "input": {
            "hook_event": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"path": "src/index.ts"},
            "session_id": "bench-01",
        },
    },
    {
        "label": "T02 grep search",
        "expected": "haiku",
        "input": {
            "hook_event": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "grep -rn 'TODO' src/"},
            "session_id": "bench-02",
        },
    },
    {
        "label": "T03 short Glob",
        "expected": "haiku",
        "input": {
            "hook_event": "PreToolUse",
            "tool_name": "Glob",
            "tool_input": {"pattern": "**/*.ts"},
            "session_id": "bench-03",
        },
    },
    {
        "label": "T04 small Write (~100 chars)",
        "expected": "sonnet+medium",
        "input": {
            "hook_event": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {
                "path": "src/util/format.ts",
                "content": "export const cap = (s: string) => s.toUpperCase();",
            },
            "session_id": "bench-04",
        },
    },
    {
        "label": "T05 npm test",
        "expected": "sonnet+medium",
        "input": {
            "hook_event": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "npm test -- --watch=false"},
            "session_id": "bench-05",
        },
    },
    {
        "label": "T06 medium Write (~2000 chars)",
        "expected": "sonnet+high",
        "input": {
            "hook_event": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {
                "path": "src/cart.ts",
                "content": "// shopping cart impl\n" + ("const item = { id: 1, qty: 2 };\n" * 80),
            },
            "session_id": "bench-06",
        },
    },
    {
        "label": "T07 endpoint kw",
        "expected": "sonnet+high",
        "input": {
            "hook_event": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {
                "path": "src/api/users.ts",
                "old_string": "// add new endpoint",
                "new_string": "router.get('/users/:id', getUser);",
            },
            "session_id": "bench-07",
        },
    },
    {
        "label": "T08 large Write (~5000 chars)",
        "expected": "opus+high",
        "input": {
            "hook_event": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {
                "path": "src/orchestrator.ts",
                "content": "// large file\n" + ("function step(ctx: Ctx) { return ctx; }\n" * 150),
            },
            "session_id": "bench-08",
        },
    },
    {
        "label": "T09 auth file (escalation)",
        "expected": "opus+xhigh (sensitive)",
        "input": {
            "hook_event": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {
                "path": "src/auth/login.ts",
                "content": "export function login() {}",
            },
            "session_id": "bench-09",
        },
    },
    {
        "label": "T10 Task dispatch w/ crypto → block",
        "expected": "ask permission, suggest secure-opus",
        "input": {
            "hook_event": "PreToolUse",
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "description": "encrypt user passwords",
                "prompt": "Implement bcrypt password hashing for the user service.",
            },
            "session_id": "bench-10",
        },
    },
]

results = []
for i, p in enumerate(PROMPTS, 1):
    payload = json.dumps(p["input"])
    t0 = time.perf_counter()
    proc = subprocess.run(
        ["python3", str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
    )
    dt_ms = (time.perf_counter() - t0) * 1000
    try:
        out = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        out = {"_raw": proc.stdout}
    results.append({
        "i": i,
        "label": p["label"],
        "expected": p["expected"],
        "tool": p["input"]["tool_name"],
        "out": out,
        "dt_ms": dt_ms,
        "stderr": proc.stderr.strip(),
    })

# Print structured per-prompt output
print("=" * 78)
print(f"  smart-router benchmark — {len(results)} prompts")
print("=" * 78)
for r in results:
    out = r["out"]
    h = out.get("hookSpecificOutput", {}) or {}
    decision = h.get("permissionDecision", "")
    if decision == "ask":
        model = f"BLOCK ({decision})"
        reason = h.get("permissionDecisionReason", "")
        effort = "—"
        tier = "—"
        confidence = "—"
    else:
        model = out.get("model_override", "—")
        effort = out.get("effort", "—")
        reason = out.get("reason", "")
        tier = out.get("tier_label", "—")
        confidence = out.get("confidence", "—")
    print(f"\n[{r['i']:02d}] {r['label']}")
    print(f"     tool      : {r['tool']}")
    print(f"     expected  : {r['expected']}")
    print(f"     → model   : {model}")
    print(f"     → effort  : {effort}")
    print(f"     → tier    : {tier}")
    print(f"     → reason  : {reason}")
    print(f"     → conf    : {confidence}")
    print(f"     latency   : {r['dt_ms']:.1f} ms")

# Tier histogram
print()
print("=" * 78)
print("  tier histogram")
print("=" * 78)
hist = {}
for r in results:
    out = r["out"]
    h = out.get("hookSpecificOutput", {}) or {}
    decision = h.get("permissionDecision", "")
    if decision == "ask" or decision == "deny":
        key = "BLOCK"
    else:
        key = out.get("tier_label", "?")
    hist[key] = hist.get(key, 0) + 1
for k in sorted(hist):
    bar = "█" * hist[k]
    print(f"  {k:18s} {bar} {hist[k]}")

# Latency stats
lats = [r["dt_ms"] for r in results]
print()
print("=" * 78)
print("  latency")
print("=" * 78)
print(f"  min  : {min(lats):.1f} ms")
print(f"  max  : {max(lats):.1f} ms")
print(f"  mean : {sum(lats)/len(lats):.1f} ms")

# Cost projection (assume avg 800 output tokens per call)
print()
print("=" * 78)
print("  cost projection — 1000 calls at this distribution, 800 output tokens each")
print("=" * 78)
PRICE = {  # $/1M output tokens
    "haiku": 4.00,
    "sonnet": 15.00,
    "opus": 25.00,
}
def alias(model):
    if "haiku" in model: return "haiku"
    if "opus" in model: return "opus"
    if "sonnet" in model: return "sonnet"
    return "opus"  # blocks → opus

per_call_tokens = 800
scaled = 1000
total_actual = 0.0
total_baseline = 0.0
for r in results:
    out = r["out"]
    h = out.get("hookSpecificOutput", {}) or {}
    decision = h.get("permissionDecision", "")
    if decision in ("ask", "deny"):
        m = "claude-opus-4-7"  # block → user routes to opus
    else:
        m = out.get("model_override", "")
    a = alias(m)
    cost = (scaled / len(results)) * per_call_tokens * (PRICE[a] / 1_000_000)
    baseline = (scaled / len(results)) * per_call_tokens * (PRICE["opus"] / 1_000_000)
    total_actual += cost
    total_baseline += baseline
print(f"  actual       : ${total_actual:.4f}")
print(f"  baseline opus: ${total_baseline:.4f}")
print(f"  saved        : ${total_baseline - total_actual:.4f} "
      f"({(1 - total_actual/total_baseline)*100:.1f}%)")

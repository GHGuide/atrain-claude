#!/usr/bin/env python3
"""three_workloads_bench.py — token-cost comparison across three modes.

Workload A: recon-heavy session (search/explore a codebase)
Workload B: typical coding session (mix of read + edit + test)
Workload C: heavy refactor (large writes, multi-file)

For each (workload, mode in {eco, balanced, quality}) plus all-Opus baseline,
compute estimated input + output tokens and dollar cost. Print side-by-side.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".claude" / "hooks"))

from router import classify_task, hard_escalation, _default_config  # noqa

# Realistic average tokens per (alias, effort) tier.
# Output dominates cost; input mostly cached system prompt overhead.
INPUT_TOKENS_AVG = 4500          # cached/prefix overhead per call
TIER_OUT_TOKENS = {
    "haiku+none":     250,
    "sonnet+low":     400,
    "sonnet+medium":  600,
    "sonnet+high":   1100,
    "sonnet+max":    1800,
    "opus+low":       800,
    "opus+medium":   1200,
    "opus+high":     1700,
    "opus+xhigh":    2200,
    "opus+max":      3000,
}
PRICE_IN = {"haiku": 0.80, "sonnet": 3.00, "opus": 5.00}
PRICE_OUT = {"haiku": 4.00, "sonnet": 15.00, "opus": 25.00}


def alias(model: str) -> str:
    if "haiku" in model: return "haiku"
    if "opus" in model: return "opus"
    return "sonnet"


def workloads():
    """Three realistic workloads, each ~20 calls."""
    pad_2k = "x" * 2000
    pad_5k = "x" * 5000
    A = []  # recon-heavy: 70% reads/greps, 20% small edits, 10% sensitive
    for i in range(8):
        A.append(("Read", {"path": f"src/file{i}.ts"}))
    A.append(("Glob", {"pattern": "**/*.ts"}))
    A.append(("Grep", {"pattern": "TODO"}))
    A.append(("Bash", {"command": "grep -rn FIXME src/"}))
    A.append(("Bash", {"command": "ls -la src/"}))
    A.append(("Bash", {"command": "find . -name '*.test.ts'"}))
    A.append(("Read", {"path": "README.md"}))
    A.append(("Write", {"path": "src/util.ts",
                        "content": "export const cap = (s) => s.toUpperCase();"}))
    A.append(("Edit", {"path": "src/log.ts", "old_string": "console.log",
                       "new_string": "logger.info"}))
    A.append(("Edit", {"path": "src/auth/jwt.ts", "old_string": "verify",
                       "new_string": "function verify(token, secret) { return true; }"}))
    A.append(("Bash", {"command": "npm test"}))
    A.append(("Read", {"path": "src/api/users.ts"}))

    B = []  # typical coding: 30% recon, 50% edits, 15% tests, 5% sensitive
    for i in range(6):
        B.append(("Read", {"path": f"src/component{i}.tsx"}))
    B.append(("Bash", {"command": "grep -rn 'useState' src/"}))
    B.append(("Edit", {"path": "src/cart.ts", "old_string": "const total",
                       "new_string": "const total = items.reduce(...)"}))
    B.append(("Write", {"path": "src/util/format.ts", "content": pad_2k[:1800]}))
    B.append(("Edit", {"path": "src/api/orders.ts",
                       "old_string": "// TODO: route",
                       "new_string": "router.get('/orders/:id', getOrder);"}))
    B.append(("Write", {"path": "src/cart.ts", "content": pad_2k}))
    B.append(("Bash", {"command": "npm test -- --watch=false"}))
    B.append(("Bash", {"command": "pytest tests/cart_test.py"}))
    B.append(("Edit", {"path": "src/log.ts", "old_string": "log",
                       "new_string": "log_v2"}))
    B.append(("Write", {"path": "src/auth/session.ts",
                        "content": "export function createSession() {}"}))
    B.append(("Bash", {"command": "npm run lint"}))
    B.append(("Read", {"path": "package.json"}))
    B.append(("Edit", {"path": "src/cart.ts",
                       "old_string": "function checkout",
                       "new_string": "// implement checkout endpoint api integration"}))

    C = []  # heavy refactor: 20% recon, 40% large writes, 30% multi-file, 10% sensitive
    for i in range(4):
        C.append(("Read", {"path": f"src/legacy/module{i}.ts"}))
    for i in range(5):
        C.append(("Write", {"path": f"src/new/module{i}.ts",
                            "content": pad_5k}))
    C.append(("Edit", {"path": "src/main.ts",
                       "old_string": "import legacy",
                       "new_string": "// refactor the entire codebase to use new event bus"}))
    C.append(("Write", {"path": "src/orchestrator.ts", "content": pad_5k * 2}))
    C.append(("Edit", {"path": "src/auth/login.ts",
                       "old_string": "password",
                       "new_string": "bcrypt password hash"}))
    C.append(("Bash", {"command": "psql -c 'ALTER TABLE users DROP COLUMN legacy;'"}))
    C.append(("Edit", {"path": "package.json",
                       "old_string": "1.0.0", "new_string": "2.0.0"}))
    C.append(("Bash", {"command": "npm run migrate"}))
    C.append(("Read", {"path": "src/orchestrator.ts"}))
    C.append(("Bash", {"command": "npm test"}))
    C.append(("Edit", {"path": "src/api/router.ts",
                       "old_string": "// add endpoints",
                       "new_string": "// add new REST endpoints for v2"}))

    return {"A: recon-heavy": A, "B: typical coding": B, "C: heavy refactor": C}


def run_workload(workload, mode):
    cfg = _default_config()
    cfg["mode"] = mode
    cfg["accuracy_target"] = {"eco": 95.0, "balanced": 99.0, "quality": 99.9}[mode]
    in_tok = 0
    out_tok = 0
    cost_in = 0.0
    cost_out = 0.0
    tier_hist = {}
    for tool_name, tool_input in workload:
        decision = classify_task(tool_name, tool_input, cfg)
        escalated, _ = hard_escalation(tool_input, cfg, "bench")
        if escalated:
            decision_alias = "opus"
            effort = "xhigh"
        else:
            decision_alias = decision["model_alias"]
            effort = decision["effort"]
        tier = f"{decision_alias}+{effort}"
        tier_hist[tier] = tier_hist.get(tier, 0) + 1
        out_per_call = TIER_OUT_TOKENS.get(tier, 1000)
        in_tok += INPUT_TOKENS_AVG
        out_tok += out_per_call
        cost_in += INPUT_TOKENS_AVG * PRICE_IN[decision_alias] / 1_000_000
        cost_out += out_per_call * PRICE_OUT[decision_alias] / 1_000_000
    return {
        "in_tok": in_tok, "out_tok": out_tok,
        "cost_in": cost_in, "cost_out": cost_out,
        "cost_total": cost_in + cost_out,
        "tier_hist": tier_hist,
    }


def run_baseline(workload):
    """Single-Opus xhigh — assume every call uses opus+xhigh tier."""
    n = len(workload)
    in_tok = n * INPUT_TOKENS_AVG
    out_tok = n * TIER_OUT_TOKENS["opus+xhigh"]
    return {
        "in_tok": in_tok, "out_tok": out_tok,
        "cost_in": in_tok * PRICE_IN["opus"] / 1_000_000,
        "cost_out": out_tok * PRICE_OUT["opus"] / 1_000_000,
        "cost_total": (in_tok * PRICE_IN["opus"] + out_tok * PRICE_OUT["opus"]) / 1_000_000,
        "tier_hist": {"opus+xhigh": n},
    }


def main():
    wls = workloads()
    print(f"{'workload':22s} | {'mode':10s} | {'in tok':>8s} | "
          f"{'out tok':>8s} | {'cost':>8s} | {'vs Opus':>10s}")
    print("-" * 90)
    for name, work in wls.items():
        baseline = run_baseline(work)
        rows = [("opus only", baseline)]
        for mode in ("eco", "balanced", "quality"):
            r = run_workload(work, mode)
            rows.append((mode, r))
        for mode, r in rows:
            saved_pct = (
                100 * (baseline["cost_total"] - r["cost_total"])
                / baseline["cost_total"]
            ) if baseline["cost_total"] else 0.0
            saved_str = f"-{saved_pct:.0f}%" if mode != "opus only" else "—"
            print(f"{name:22s} | {mode:10s} | {r['in_tok']:>8,} | "
                  f"{r['out_tok']:>8,} | ${r['cost_total']:>6.4f} | {saved_str:>10s}")
        print("-" * 90)

    print()
    print("Tier distribution per workload + mode:")
    for name, work in wls.items():
        print(f"\n  {name}")
        for mode in ("eco", "balanced", "quality"):
            r = run_workload(work, mode)
            tiers = " ".join(
                f"{k}:{v}" for k, v in sorted(r["tier_hist"].items())
            )
            print(f"    {mode:10s} {tiers}")


if __name__ == "__main__":
    main()

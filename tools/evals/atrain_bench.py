#!/usr/bin/env python3
"""atrain_bench.py — real-call benchmark for ATrain Claude.

Fires actual `claude -p` subprocesses across modes and tasks. Reports:
  - input / output / cache tokens (real, from CLI usage block)
  - total_cost_usd (real, from CLI)
  - duration_ms (real, from CLI)
  - output similarity vs single-Opus baseline (Jaccard token overlap)

Three benchmark suites:
  recon       — file searches (Glob, Grep, LS) — Haiku-routable
  mixed       — typical day work (read + edit + test) — Sonnet-routable
  sensitive   — auth / crypto / migration — forced Opus xhigh

Each suite runs across:
  baseline    — single Opus, plugin OFF (--model opus, decompose=false)
  eco         — /atrain-eco + /atrain-on
  balanced    — /atrain-balanced + /atrain-on
  quality     — /atrain-quality + /atrain-on

Usage:
    python3 tools/evals/atrain_bench.py
    python3 tools/evals/atrain_bench.py --suite recon
    python3 tools/evals/atrain_bench.py --suite mixed --mode eco
    python3 tools/evals/atrain_bench.py --quick   # 1 task per suite

Requires:  claude CLI on PATH, logged-in Claude Code subscription
           OR  ANTHROPIC_API_KEY set (uses API credits in that case)
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONFIG_PATH = pathlib.Path.home() / ".claude" / "router-config.json"
PROJECT_CONFIG = ROOT / ".claude" / "router-config.json"

SUITES = {
    "recon": [
        ("find-todos",
         "Find all TODO comments in the .claude/hooks directory and list "
         "their file:line locations. One-line summary per match. Cap at 10."),
        ("locate-fn",
         "Where is `compute_output_confidence` defined in this codebase? "
         "Just give file:line, no extra commentary."),
        ("count-tests",
         "Count how many T01..T36 tests exist in router.py and list any "
         "function name that is referenced but not tested. Cap at 5."),
    ],
    "mixed": [
        ("rename-helper",
         "Read .claude/hooks/router.py and propose a one-line rename for "
         "the `_tool_str` helper that better reflects its purpose. Print "
         "old name → new name plus a one-sentence rationale."),
        ("add-test",
         "Sketch (don't write) a T37 test that verifies "
         "compute_output_confidence returns < 0.5 for an empty Bash output "
         "with exit_code != 0. Five lines max."),
    ],
    "sensitive": [
        ("auth-review",
         "Read tools/evals/router_eval.json and tell me whether any "
         "test case references a real password or API key (vs a placeholder). "
         "Yes/no answer plus the case ID if yes."),
        ("migration-plan",
         "If we wanted to add a `last_login_at` column to a hypothetical "
         "users table, list the three steps for a backwards-compatible "
         "schema migration. Numbered list, one line each."),
    ],
}

PRICE_IN = {"haiku": 0.80, "sonnet": 3.00, "opus": 5.00}
PRICE_OUT = {"haiku": 4.00, "sonnet": 15.00, "opus": 25.00}


def alias_of(model_id: str) -> str:
    if "haiku" in model_id: return "haiku"
    if "opus" in model_id: return "opus"
    return "sonnet"


def set_config(mode: str, decompose: bool) -> None:
    """Mutate ~/.claude/router-config.json to set mode + decompose flag."""
    p = CONFIG_PATH if CONFIG_PATH.exists() else PROJECT_CONFIG
    cfg = json.loads(p.read_text())
    cfg["mode"] = mode
    cfg["accuracy_target"] = {"eco": 95.0, "balanced": 99.0, "quality": 99.9}[mode]
    cfg["decompose_enabled"] = decompose
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    os.replace(tmp, p)


def run_claude(prompt: str, model: str = None, timeout: int = 120) -> dict:
    """Execute `claude -p "<prompt>" --output-format json`. Return parsed JSON."""
    cmd = ["claude", "-p", prompt, "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return {"error": "claude CLI not on PATH", "wall_ms": 0}
    except subprocess.TimeoutExpired:
        return {"error": f"timeout after {timeout}s", "wall_ms": timeout * 1000}
    wall_ms = int((time.perf_counter() - t0) * 1000)
    if proc.returncode != 0:
        return {"error": f"exit {proc.returncode}: {proc.stderr.strip()[:200]}",
                "wall_ms": wall_ms}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"error": "non-JSON stdout", "raw": proc.stdout[:200],
                "wall_ms": wall_ms}
    usage = data.get("usage", {}) or {}
    return {
        "result": (data.get("result") or "").strip(),
        "in_tokens": usage.get("input_tokens", 0),
        "out_tokens": usage.get("output_tokens", 0),
        "cache_read": usage.get("cache_read_input_tokens", 0),
        "cache_create": usage.get("cache_creation_input_tokens", 0),
        "cost_usd": data.get("total_cost_usd", 0.0),
        "duration_ms": data.get("duration_ms", wall_ms),
        "wall_ms": wall_ms,
        "model_usage": data.get("modelUsage", {}),
    }


def jaccard(a: str, b: str) -> float:
    """Token-set Jaccard similarity. Cheap quality proxy."""
    if not a or not b:
        return 0.0
    ta = set(re.findall(r"\w+", a.lower()))
    tb = set(re.findall(r"\w+", b.lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def benchmark_task(task_id: str, prompt: str, modes: list) -> dict:
    """Run a single task across baseline + each mode. Return comparison."""
    results = {}
    print(f"  [{task_id}] running baseline (single Opus)...", flush=True)
    set_config("balanced", False)
    baseline = run_claude(prompt, model="opus")
    results["baseline"] = baseline
    if "error" in baseline:
        print(f"    baseline error: {baseline['error']}")

    for mode in modes:
        print(f"  [{task_id}] running ATrain {mode}...", flush=True)
        set_config(mode, True)  # decompose ON
        r = run_claude(prompt)
        if "error" not in r and "error" not in baseline:
            r["jaccard_vs_baseline"] = jaccard(
                baseline.get("result", ""), r.get("result", "")
            )
        results[mode] = r

    # restore default
    set_config("balanced", False)
    return results


def print_row(label: str, r: dict, baseline: dict = None) -> None:
    if "error" in r:
        print(f"  {label:14s} ERROR  {r['error'][:60]}")
        return
    in_tok = r.get("in_tokens", 0)
    out_tok = r.get("out_tokens", 0)
    cache_read = r.get("cache_read", 0)
    cost = r.get("cost_usd", 0.0)
    dur_s = r.get("duration_ms", 0) / 1000.0
    sim_str = ""
    if "jaccard_vs_baseline" in r:
        sim_str = f"  sim={r['jaccard_vs_baseline']:.2f}"
    delta_str = ""
    if baseline and "cost_usd" in baseline and baseline["cost_usd"] > 0:
        saved = baseline["cost_usd"] - cost
        pct = 100 * saved / baseline["cost_usd"]
        delta_str = f"  ({pct:+.0f}% vs baseline)"
    print(f"  {label:14s} in={in_tok:>5d}  out={out_tok:>5d}  "
          f"cache={cache_read:>6d}  ${cost:.4f}  {dur_s:>5.1f}s{sim_str}{delta_str}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=list(SUITES.keys()) + ["all"],
                        default="all")
    parser.add_argument("--mode", choices=["eco", "balanced", "quality", "all"],
                        default="all")
    parser.add_argument("--quick", action="store_true",
                        help="run only the first task in each suite")
    parser.add_argument("--json", action="store_true",
                        help="emit machine-readable JSON instead of text")
    args = parser.parse_args()

    # check claude CLI
    try:
        subprocess.run(["claude", "--version"], capture_output=True,
                       text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("ERROR: claude CLI not on PATH. Install Claude Code first.",
              file=sys.stderr)
        sys.exit(2)

    suites = list(SUITES.keys()) if args.suite == "all" else [args.suite]
    modes = ["eco", "balanced", "quality"] if args.mode == "all" else [args.mode]

    all_results = {}
    print("=" * 76)
    print(f"  ATrain real-call benchmark")
    print(f"  suites={suites}  modes={modes}  quick={args.quick}")
    print("=" * 76)
    print()

    for suite in suites:
        tasks = SUITES[suite]
        if args.quick:
            tasks = tasks[:1]
        print(f"=== suite: {suite} ===")
        suite_results = {}
        for task_id, prompt in tasks:
            print(f"\n  task: {task_id}")
            print(f"  prompt: {prompt[:120]}{'...' if len(prompt) > 120 else ''}")
            r = benchmark_task(task_id, prompt, modes)
            suite_results[task_id] = r
            print()
            print_row("baseline", r["baseline"])
            for mode in modes:
                print_row(mode, r[mode], baseline=r["baseline"])
            print()
        all_results[suite] = suite_results

    # aggregate
    print()
    print("=" * 76)
    print("  AGGREGATE")
    print("=" * 76)
    for suite, suite_results in all_results.items():
        print(f"\n  suite: {suite}")
        for label in ["baseline"] + modes:
            costs = [r[label].get("cost_usd", 0.0)
                     for r in suite_results.values()
                     if "error" not in r.get(label, {})]
            durs = [r[label].get("duration_ms", 0) / 1000.0
                    for r in suite_results.values()
                    if "error" not in r.get(label, {})]
            sims = [r[label].get("jaccard_vs_baseline", 0.0)
                    for r in suite_results.values()
                    if "error" not in r.get(label, {})
                    and "jaccard_vs_baseline" in r[label]]
            if costs:
                avg_cost = sum(costs) / len(costs)
                avg_dur = sum(durs) / len(durs)
                sim_str = f"  avg sim={sum(sims)/len(sims):.2f}" if sims else ""
                print(f"    {label:12s} avg cost ${avg_cost:.4f}  "
                      f"avg time {avg_dur:5.1f}s{sim_str}")

    if args.json:
        with open("/tmp/atrain_bench_results.json", "w") as f:
            json.dump(all_results, f, indent=2)
        print("\n  Raw results: /tmp/atrain_bench_results.json")


if __name__ == "__main__":
    main()

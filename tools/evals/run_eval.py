#!/usr/bin/env python3
"""run_eval.py — score smart-router classifiers against router_eval.json.

Reports per-category accuracy, overall accuracy, and a confusion matrix.
Provides the labeled corpus needed for any future MIPRO-style optimization
of the agent system prompts.

Usage:
    python3 tools/evals/run_eval.py
    python3 tools/evals/run_eval.py --json    # machine-readable output
    python3 tools/evals/run_eval.py --task-dispatch-only
    python3 tools/evals/run_eval.py --tool-routing-only
"""
import argparse
import json
import pathlib
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[2]
HOOK_DIR = ROOT / ".claude" / "hooks"
sys.path.insert(0, str(HOOK_DIR))

from router import (  # noqa: E402
    classify_to_agent,
    classify_task,
    _default_config,
    hard_escalation,
)


def load_corpus():
    p = pathlib.Path(__file__).parent / "router_eval.json"
    return json.loads(p.read_text())


def score_task_dispatch(corpus, modes=("eco", "balanced", "quality")):
    """For each (case, mode) score classify_to_agent."""
    results = []
    for case in corpus["task_dispatch"]:
        prompt = case["prompt"] + " " + case.get("description", "")
        for mode in modes:
            cfg = _default_config()
            cfg["mode"] = mode
            cfg["accuracy_target"] = {"eco": 95.0, "balanced": 99.0,
                                      "quality": 99.9}[mode]
            actual = classify_to_agent(prompt, cfg)
            expected = case[f"expected_{mode}"]
            results.append({
                "id": case["id"],
                "category": case["category"],
                "mode": mode,
                "expected": expected,
                "actual": actual,
                "passed": actual == expected,
            })
    return results


def _expand_pad_placeholders(value):
    """JSON can't hold 'x' * 2000 — corpus uses __PAD_N__ markers."""
    if not isinstance(value, str):
        return value
    import re
    m = re.fullmatch(r"__PAD_(\d+)__", value)
    if m:
        return "x" * int(m.group(1))
    m = re.match(r"^(.*)__PAD_(\d+)__(.*)$", value, re.DOTALL)
    if m:
        return m.group(1) + ("x" * int(m.group(2))) + m.group(3)
    return value


def score_tool_routing(corpus):
    """For each tool case score classify_task + hard_escalation."""
    results = []
    cfg = _default_config()
    for case in corpus["tool_routing"]:
        ti = dict(case["tool_input"])
        for k, v in ti.items():
            ti[k] = _expand_pad_placeholders(v)
        decision = classify_task(case["tool_name"], ti, cfg)
        escalated, reason = hard_escalation(ti, cfg, "eval")
        if escalated:
            actual_alias = "opus"
            actual_effort = "xhigh"
            actual_reason = reason
        else:
            actual_alias = decision["model_alias"]
            actual_effort = decision["effort"]
            actual_reason = decision["reason"]
        results.append({
            "id": case["id"],
            "category": case["category"],
            "tool_name": case["tool_name"],
            "expected_alias": case["expected_alias"],
            "expected_effort": case["expected_effort"],
            "actual_alias": actual_alias,
            "actual_effort": actual_effort,
            "actual_reason": actual_reason,
            "alias_match": actual_alias == case["expected_alias"],
            "effort_match": actual_effort == case["expected_effort"],
            "passed": (actual_alias == case["expected_alias"]
                       and actual_effort == case["expected_effort"]),
        })
    return results


def confusion_matrix(results, key_expected, key_actual):
    cm = defaultdict(lambda: Counter())
    for r in results:
        cm[r[key_expected]][r[key_actual]] += 1
    return dict((k, dict(v)) for k, v in cm.items())


def category_accuracy(results, category_field="category"):
    by_cat = defaultdict(lambda: [0, 0])  # [passed, total]
    for r in results:
        cat = r[category_field]
        by_cat[cat][1] += 1
        if r["passed"]:
            by_cat[cat][0] += 1
    return {k: {"pass": p, "total": t, "rate": p / t if t else 0.0}
            for k, (p, t) in by_cat.items()}


def render_text_report(td_results, tr_results):
    out = []
    out.append("=" * 72)
    out.append("  smart-router classifier evaluation")
    out.append("=" * 72)
    out.append("")

    if td_results:
        td_pass = sum(1 for r in td_results if r["passed"])
        td_total = len(td_results)
        out.append(f"Task dispatch — classify_to_agent")
        out.append(f"  overall: {td_pass}/{td_total} "
                   f"({100 * td_pass / td_total:.1f}%)")
        out.append("")
        out.append("  Per-category:")
        for cat, stats in sorted(category_accuracy(td_results).items()):
            out.append(f"    {cat:14s} {stats['pass']:>3d}/{stats['total']:<3d} "
                       f"({100 * stats['rate']:.0f}%)")
        out.append("")
        out.append("  Per-mode:")
        for mode in ("eco", "balanced", "quality"):
            mres = [r for r in td_results if r["mode"] == mode]
            mp = sum(1 for r in mres if r["passed"])
            out.append(f"    {mode:10s} {mp}/{len(mres)} "
                       f"({100 * mp / len(mres):.0f}%)")
        out.append("")
        out.append("  Failures:")
        fails = [r for r in td_results if not r["passed"]]
        if not fails:
            out.append("    (none)")
        for r in fails:
            out.append(f"    {r['id']} [{r['mode']}] expected "
                       f"{r['expected']!r}, got {r['actual']!r}")
        out.append("")

    if tr_results:
        tr_pass = sum(1 for r in tr_results if r["passed"])
        tr_total = len(tr_results)
        alias_pass = sum(1 for r in tr_results if r["alias_match"])
        effort_pass = sum(1 for r in tr_results if r["effort_match"])
        out.append("Tool routing — classify_task + hard_escalation")
        out.append(f"  overall (alias+effort): {tr_pass}/{tr_total} "
                   f"({100 * tr_pass / tr_total:.1f}%)")
        out.append(f"  alias match only:       {alias_pass}/{tr_total} "
                   f"({100 * alias_pass / tr_total:.1f}%)")
        out.append(f"  effort match only:      {effort_pass}/{tr_total} "
                   f"({100 * effort_pass / tr_total:.1f}%)")
        out.append("")
        out.append("  Per-category:")
        for cat, stats in sorted(category_accuracy(tr_results).items()):
            out.append(f"    {cat:24s} {stats['pass']:>3d}/{stats['total']:<3d} "
                       f"({100 * stats['rate']:.0f}%)")
        out.append("")
        out.append("  Failures:")
        fails = [r for r in tr_results if not r["passed"]]
        if not fails:
            out.append("    (none)")
        for r in fails:
            out.append(
                f"    {r['id']} [{r['tool_name']}] expected "
                f"{r['expected_alias']}+{r['expected_effort']}, got "
                f"{r['actual_alias']}+{r['actual_effort']}  "
                f"reason={r['actual_reason']!r}"
            )
        out.append("")

    out.append("=" * 72)
    grand_total = len(td_results) + len(tr_results)
    grand_pass = sum(1 for r in td_results + tr_results if r["passed"])
    if grand_total:
        out.append(f"  GRAND TOTAL: {grand_pass}/{grand_total} "
                   f"({100 * grand_pass / grand_total:.1f}%)")
    out.append("=" * 72)
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true",
                        help="emit machine-readable JSON")
    parser.add_argument("--task-dispatch-only", action="store_true")
    parser.add_argument("--tool-routing-only", action="store_true")
    args = parser.parse_args()

    corpus = load_corpus()
    td = score_task_dispatch(corpus) if not args.tool_routing_only else []
    tr = score_tool_routing(corpus) if not args.task_dispatch_only else []

    if args.json:
        sys.stdout.write(json.dumps({
            "task_dispatch": td,
            "tool_routing": tr,
            "task_dispatch_acc": (
                sum(1 for r in td if r["passed"]) / len(td) if td else None),
            "tool_routing_acc": (
                sum(1 for r in tr if r["passed"]) / len(tr) if tr else None),
        }, indent=2))
        return

    sys.stdout.write(render_text_report(td, tr) + "\n")


if __name__ == "__main__":
    main()

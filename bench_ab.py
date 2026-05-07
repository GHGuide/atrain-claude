#!/usr/bin/env python3
"""smart-router A/B bench — with router vs all-opus baseline.

Usage:
  python3 bench_ab.py             # simulated (estimated tokens)
  python3 bench_ab.py --real      # real API calls (needs ANTHROPIC_API_KEY)
"""
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
HOOK = ROOT / ".claude" / "hooks" / "router.py"

# Pricing $ per 1M output tokens
PRICE_OUT = {
    "haiku": 4.00,
    "sonnet": 15.00,
    "opus": 25.00,
}
PRICE_IN = {
    "haiku": 0.80,
    "sonnet": 3.00,
    "opus": 5.00,
}

# Realistic output token estimates per tier
TOKEN_EST = {
    "haiku+none":     250,   # cheap recon, short report
    "sonnet+medium":  600,   # small edit, test run
    "sonnet+high":   1100,   # mid-size edit, multi-file
    "opus+high":     1700,   # big refactor, design
    "opus+xhigh":    2200,   # security/sensitive — deep think
    "opus+max":      3000,
}

# Input token estimate per call (system prompt + tool context)
INPUT_TOKENS_AVG = 4500


def alias(model_id: str) -> str:
    if "haiku" in model_id: return "haiku"
    if "opus" in model_id: return "opus"
    return "sonnet"


PROMPTS = [
    {"label": "small Read",
     "input": {"hook_event":"PreToolUse","tool_name":"Read",
               "tool_input":{"path":"src/index.ts"},"session_id":"ab-01"}},
    {"label": "grep search",
     "input": {"hook_event":"PreToolUse","tool_name":"Bash",
               "tool_input":{"command":"grep -rn TODO src/"},"session_id":"ab-02"}},
    {"label": "short Glob",
     "input": {"hook_event":"PreToolUse","tool_name":"Glob",
               "tool_input":{"pattern":"**/*.ts"},"session_id":"ab-03"}},
    {"label": "small Write 100ch",
     "input": {"hook_event":"PreToolUse","tool_name":"Write",
               "tool_input":{"path":"src/util/format.ts",
                             "content":"export const cap = (s) => s.toUpperCase();"},
               "session_id":"ab-04"}},
    {"label": "npm test",
     "input": {"hook_event":"PreToolUse","tool_name":"Bash",
               "tool_input":{"command":"npm test"},"session_id":"ab-05"}},
    {"label": "medium Write 2000ch",
     "input": {"hook_event":"PreToolUse","tool_name":"Write",
               "tool_input":{"path":"src/cart.ts",
                             "content":"// cart\n" + ("const i = {q:1};\n" * 120)},
               "session_id":"ab-06"}},
    {"label": "endpoint kw",
     "input": {"hook_event":"PreToolUse","tool_name":"Edit",
               "tool_input":{"path":"src/api/users.ts",
                             "old_string":"// add endpoint",
                             "new_string":"router.get('/users/:id', getUser);"},
               "session_id":"ab-07"}},
    {"label": "large Write 5000ch",
     "input": {"hook_event":"PreToolUse","tool_name":"Write",
               "tool_input":{"path":"src/orchestrator.ts",
                             "content":"// big\n" + ("function step(){return 0;}\n" * 200)},
               "session_id":"ab-08"}},
    {"label": "auth file",
     "input": {"hook_event":"PreToolUse","tool_name":"Write",
               "tool_input":{"path":"src/auth/login.ts",
                             "content":"export function login(){}"},
               "session_id":"ab-09"}},
    {"label": "Task crypto block",
     "input": {"hook_event":"PreToolUse","tool_name":"Task",
               "tool_input":{"subagent_type":"general-purpose",
                             "description":"encrypt passwords",
                             "prompt":"Implement bcrypt for the user service."},
               "session_id":"ab-10"}},
]


def run_hook(payload: dict) -> dict:
    proc = subprocess.run(
        ["python3", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=10,
    )
    try:
        return json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        return {"_raw": proc.stdout}


def call_claude_cli(model_id: str, user_msg: str) -> dict:
    """Use Claude Code's bundled-token CLI (`claude -p`). NO API key needed.
    Uses the user's logged-in Claude Code subscription quota."""
    try:
        proc = subprocess.run(
            ["claude", "-p", user_msg,
             "--model", model_id,
             "--output-format", "json"],
            capture_output=True, text=True, timeout=90,
        )
    except FileNotFoundError:
        return {"error": "claude CLI not found on PATH"}
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    if proc.returncode != 0:
        return {"error": f"exit {proc.returncode}: {proc.stderr.strip()[:200]}"}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"error": "non-JSON stdout", "raw": proc.stdout[:200]}
    usage = data.get("usage", {}) or data.get("total_usage", {})
    return {
        "in_tokens": usage.get("input_tokens", 0),
        "out_tokens": usage.get("output_tokens", 0),
        "cache_read": usage.get("cache_read_input_tokens", 0),
        "cache_write": usage.get("cache_creation_input_tokens", 0),
        "text": (data.get("result") or data.get("text") or "")[:200],
    }


def main():
    real_mode = "--real" in sys.argv
    if real_mode:
        # Verify claude CLI exists — bundled tokens, no API key
        try:
            subprocess.run(["claude", "--version"], capture_output=True,
                           text=True, timeout=5)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            print("--real needs the `claude` CLI on PATH (Claude Code "
                  "subscription). No API key required.", file=sys.stderr)
            sys.exit(2)

    rows = []
    for i, p in enumerate(PROMPTS, 1):
        out = run_hook(p["input"])
        h = out.get("hookSpecificOutput", {}) or {}
        decision = h.get("permissionDecision", "")
        if decision == "ask":
            with_model = "claude-opus-4-7"
            with_tier = "opus+xhigh"
            with_reason = "BLOCK→opus"
        else:
            with_model = out.get("model_override", "claude-sonnet-4-6")
            with_tier = out.get("tier_label", "sonnet+medium")
            with_reason = out.get("reason", "")

        without_model = "claude-opus-4-7"
        without_tier = "opus+xhigh"

        out_tok = TOKEN_EST.get(with_tier, 1000)
        baseline_tok = TOKEN_EST.get(without_tier, 2200)
        in_tok = INPUT_TOKENS_AVG

        with_alias = alias(with_model)
        without_alias = alias(without_model)

        with_cost = (in_tok * PRICE_IN[with_alias] / 1_000_000
                     + out_tok * PRICE_OUT[with_alias] / 1_000_000)
        without_cost = (in_tok * PRICE_IN[without_alias] / 1_000_000
                        + baseline_tok * PRICE_OUT[without_alias] / 1_000_000)

        real = {}
        if real_mode:
            sample_msg = f"Task: {p['label']}. Respond briefly in 1-2 sentences."
            real_with = call_claude_cli(with_model, sample_msg)
            real_without = call_claude_cli(without_model, sample_msg)
            real = {"with": real_with, "without": real_without}

        rows.append({
            "i": i, "label": p["label"],
            "with_model": with_model, "with_tier": with_tier,
            "with_reason": with_reason,
            "without_model": without_model, "without_tier": without_tier,
            "out_tok": out_tok, "baseline_tok": baseline_tok,
            "in_tok": in_tok,
            "with_cost": with_cost, "without_cost": without_cost,
            "real": real,
        })

    # Header
    print("=" * 96)
    print(f"  smart-router A/B — WITH router vs WITHOUT (all-opus baseline)")
    if real_mode:
        print("  REAL API mode (live Anthropic calls)")
    else:
        print("  SIMULATED mode (estimated tokens). Add --real for live calls.")
    print("=" * 96)

    # Per-prompt
    for r in rows:
        print(f"\n[{r['i']:02d}] {r['label']}")
        print(f"     WITH    router → {r['with_tier']:14s} {r['with_model']}")
        print(f"                       {r['out_tok']} out tok  ${r['with_cost']:.5f}  reason={r['with_reason']}")
        print(f"     WITHOUT router → {r['without_tier']:14s} {r['without_model']}")
        print(f"                       {r['baseline_tok']} out tok  ${r['without_cost']:.5f}")
        delta = r['without_cost'] - r['with_cost']
        pct = 100 * delta / r['without_cost'] if r['without_cost'] else 0
        print(f"     savings        → ${delta:.5f}  ({pct:.0f}%)")
        if r["real"]:
            rw = r["real"].get("with", {})
            ro = r["real"].get("without", {})
            print(f"     [real WITH ]    in={rw.get('in_tokens')} out={rw.get('out_tokens')}")
            print(f"     [real W/OUT]    in={ro.get('in_tokens')} out={ro.get('out_tokens')}")

    # Totals
    total_with_cost = sum(r["with_cost"] for r in rows)
    total_without_cost = sum(r["without_cost"] for r in rows)
    total_with_out = sum(r["out_tok"] for r in rows)
    total_without_out = sum(r["baseline_tok"] for r in rows)
    total_in = sum(r["in_tok"] for r in rows)
    saved = total_without_cost - total_with_cost
    pct = 100 * saved / total_without_cost if total_without_cost else 0

    print()
    print("=" * 96)
    print("  TOTALS — 10 prompts")
    print("=" * 96)
    print(f"                       WITH router    WITHOUT (all-opus)   delta")
    print(f"  Input tokens         {total_in:>10,}    {total_in:>10,}        0")
    print(f"  Output tokens        {total_with_out:>10,}    {total_without_out:>10,}    "
          f"{total_with_out - total_without_out:+,}")
    print(f"  Cost                 ${total_with_cost:>9.4f}    ${total_without_cost:>9.4f}    "
          f"-${saved:.4f}")
    print(f"  Savings vs all-opus                                       {pct:.1f}%")

    # Tier histogram
    print()
    print("  WITH router tier distribution:")
    hist = {}
    for r in rows:
        t = r["with_tier"]
        hist[t] = hist.get(t, 0) + 1
    for t in sorted(hist):
        bar = "█" * hist[t]
        print(f"    {t:14s} {bar} {hist[t]}")

    # Project to 1000 calls
    print()
    print("  Projected to 1000 calls at this distribution:")
    scale = 1000 / len(rows)
    pw = total_with_cost * scale
    po = total_without_cost * scale
    print(f"    WITH router  : ${pw:.2f}")
    print(f"    WITHOUT      : ${po:.2f}")
    print(f"    Saved        : ${po - pw:.2f}  ({100*(po-pw)/po:.1f}%)")


if __name__ == "__main__":
    main()

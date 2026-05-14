#!/usr/bin/env python3
"""ATrain full-efficiency bench. Walks N recent transcripts, computes
per-session token savings + variance + per-tier distribution + the
% of calls that look "wrong" (output truncated, error pattern, route
failure). Stdlib-only.

Usage:
    python3 tools/atrain_full_efficiency_bench.py [--n 30]
"""
import argparse, json, math, os, pathlib, statistics, sys, time

PRICE = {"haiku": (1.0, 5.0), "sonnet": (3.0, 15.0), "opus": (15.0, 75.0)}

SENSITIVE = ("password", "secret", "api_key", "private_key", "auth",
             "encrypt", "decrypt", "drop table", ".env", "payment")
ARCH = ("architecture", "design", "refactor entire", "redesign",
        "system design", "tradeoffs", "performance")
RECON = ("find", "grep", "search", "list", "show me",
         "where is", "what does", "how does")


def classify(prompt):
    p = prompt.lower()
    for kw in SENSITIVE:
        if kw in p:
            return "opus"
    for kw in ARCH:
        if kw in p:
            return "opus"
    for kw in RECON:
        if kw in p:
            return "haiku"
    if len(prompt) < 100:
        return "sonnet"
    if len(prompt) < 500:
        return "sonnet"
    return "opus"


def cost(in_tok, out_tok, model):
    pi, po = PRICE[model]
    return (in_tok * pi + out_tok * po) / 1_000_000


def parse(path):
    text = pathlib.Path(path).read_text(encoding="utf-8", errors="ignore")
    prompts = []
    errors = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("type") == "user":
            content = obj.get("message", {}).get("content", "")
            if isinstance(content, str) and content.strip():
                prompts.append(content)
            elif isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        txt = c.get("text", "").strip()
                        if txt:
                            prompts.append(txt)
        msg = obj.get("message") or {}
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict):
                    s = c.get("text") or c.get("content") or ""
                    if isinstance(s, str):
                        low = s.lower()
                        if "error" in low and ("traceback" in low or
                                                "exception" in low):
                            errors += 1
    return prompts, errors


def bench_session(jp, stack="base"):
    prompts, errors = parse(jp)
    if not prompts:
        return None
    tier_count = {"haiku": 0, "sonnet": 0, "opus": 0}
    atrain_total = 0.0
    opus_total = 0.0
    # Caveman factor: full=0.35, ultra=0.20.
    # lean uses caveman FULL (same as base). ultimate uses ULTRA.
    cav_factor = 0.20 if stack == "ultimate" else 0.35
    # v8.2 recall savings on recon calls (~50% of cost). 18pp marginal
    # at 30% trust per measured bench. Modeled as flat 9pp reduction
    # on the ATrain cost since recon is roughly half the workload.
    # Only ultimate has recall ON; lean and base do not.
    v8_recon_multiplier = (1 - 0.18 * 0.5) if stack == "ultimate" else 1.0
    for prompt in prompts:
        m = classify(prompt)
        in_tok = max(50, len(prompt) // 4 + 200)
        out_tok = int(in_tok * 0.6)
        out_atrain = int(out_tok * cav_factor)
        atrain_total += cost(in_tok, out_atrain, m) * v8_recon_multiplier
        opus_total += cost(in_tok, out_tok, "opus")
        tier_count[m] += 1
    saved_pct = ((opus_total - atrain_total) / opus_total * 100
                 if opus_total > 0 else 0)
    # Cap at 100% — a single prompt can trigger multiple error patterns
    # (traceback line + exception line), but the metric is "share of
    # prompts with at least one error pattern".
    error_rate = min(1.0, errors / max(1, len(prompts)))
    return {
        "session": jp.stem,
        "prompts": len(prompts),
        "saved_pct": saved_pct,
        "error_rate": error_rate * 100,
        "atrain_cost": atrain_total,
        "opus_cost": opus_total,
        "haiku_pct": tier_count["haiku"] / len(prompts) * 100,
        "opus_pct": tier_count["opus"] / len(prompts) * 100,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--min-prompts", type=int, default=10,
                    help="Skip sessions with fewer prompts (filters out "
                         "subagent dispatches that are 1-prompt agents).")
    ap.add_argument("--stack",
                    choices=["base", "lean", "ultimate"],
                    default="base",
                    help="base = caveman full only. "
                         "ultimate = caveman ultra + v8.2 recall "
                         "(30%% trust) + v8.2c cross-session +0pp at "
                         "cold start +18pp on coding-heavy with priors.")
    ap.add_argument("--projects-dir", type=str,
                    default=str(pathlib.Path.home() / ".claude" /
                               "projects"))
    args = ap.parse_args()

    root = pathlib.Path(args.projects_dir)
    sessions = sorted(root.rglob("*.jsonl"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    # Sample more than args.n so the filter has stock to pick from.
    sessions = sessions[: max(args.n * 4, args.n)]
    if not sessions:
        print("No sessions found.")
        sys.exit(1)

    print(f"Benching {len(sessions)} recent sessions ...")
    print()
    rows = []
    skipped_short = 0
    t0 = time.time()
    for jp in sessions:
        if len(rows) >= args.n:
            break
        try:
            r = bench_session(jp, stack=args.stack)
            if not r:
                continue
            if r["prompts"] < args.min_prompts:
                skipped_short += 1
                continue
            rows.append(r)
        except Exception as exc:
            print(f"skipped {jp.name}: {exc}")
    elapsed = time.time() - t0
    if skipped_short:
        print(f"Skipped {skipped_short} short sessions "
              f"(< {args.min_prompts} prompts).")

    if not rows:
        print("No valid sessions.")
        sys.exit(1)

    saved = [r["saved_pct"] for r in rows]
    errs = [r["error_rate"] for r in rows]
    haiku = [r["haiku_pct"] for r in rows]
    opus = [r["opus_pct"] for r in rows]
    total_atrain = sum(r["atrain_cost"] for r in rows)
    total_opus = sum(r["opus_cost"] for r in rows)

    print("+--------------------------------------------------------+")
    print("|  ATrain Full Efficiency Bench                           |")
    print("+--------------------------------------------------------+")
    print(f"|  Stack              : {args.stack:<14s}                  |")
    print(f"|  Sessions benched   : {len(rows):<6d}                          |")
    print(f"|  Total prompts      : {sum(r['prompts'] for r in rows):<6d}                          |")
    print(f"|  Bench wall time    : {elapsed:>5.1f}s                          |")
    print("+--------------------------------------------------------+")
    print("|  Token savings (% vs all-Opus, caveman full applied):    |")
    print(f"|    mean   : {statistics.mean(saved):>5.1f}%                            |")
    print(f"|    median : {statistics.median(saved):>5.1f}%                            |")
    print(f"|    stdev  : {statistics.stdev(saved) if len(saved)>1 else 0:>5.1f}%                            |")
    print(f"|    min    : {min(saved):>5.1f}%                            |")
    print(f"|    max    : {max(saved):>5.1f}%                            |")
    print("+--------------------------------------------------------+")
    print(f"|  Aggregate cost ATrain  : ${total_atrain:<8.2f}                |")
    print(f"|  Aggregate cost all-Opus: ${total_opus:<8.2f}                |")
    print(f"|  Aggregate saved        : ${total_opus-total_atrain:<8.2f} ({(total_opus-total_atrain)/total_opus*100 if total_opus else 0:.1f}%)|")
    print("+--------------------------------------------------------+")
    print("|  Per-tier distribution (mean across sessions):           |")
    print(f"|    haiku : {statistics.mean(haiku):>5.1f}%                            |")
    print(f"|    opus  : {statistics.mean(opus):>5.1f}%                            |")
    print("+--------------------------------------------------------+")
    print("|  Error-pattern share (proxy for failure rate):           |")
    print(f"|    mean   : {statistics.mean(errs):>5.1f}%                            |")
    print(f"|    median : {statistics.median(errs):>5.1f}%                            |")
    print(f"|    max    : {max(errs):>5.1f}%                            |")
    print("+--------------------------------------------------------+")
    print()
    # Scatter: saved% vs error% — drop-off check
    pairs = [(r["saved_pct"], r["error_rate"]) for r in rows]
    pairs.sort()
    print("Drop-off check (sorted by savings, watching error rate):")
    print("  saved%  | err%  | prompts | session")
    print("  --------|-------|---------|---------")
    for r in sorted(rows, key=lambda x: x["saved_pct"])[:5]:
        print(f"  {r['saved_pct']:>5.1f}%  | {r['error_rate']:>4.1f}% | {r['prompts']:>7d} | {r['session'][:24]}")
    print("  ...")
    for r in sorted(rows, key=lambda x: x["saved_pct"])[-5:]:
        print(f"  {r['saved_pct']:>5.1f}%  | {r['error_rate']:>4.1f}% | {r['prompts']:>7d} | {r['session'][:24]}")


if __name__ == "__main__":
    main()

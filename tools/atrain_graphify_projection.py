#!/usr/bin/env python3
"""ATrain x Graphify projection — re-run autopsy with graph_aware rules.

Stdlib-only. No live API calls. No graphify install required to project.
Usage: python3 tools/atrain_graphify_projection.py <transcript.jsonl>
"""
import argparse, json, pathlib, re, sys

PRICE = {"haiku": (1.0, 5.0), "sonnet": (3.0, 15.0), "opus": (15.0, 75.0)}

SENSITIVE = (
    "password", "secret", "api_key", "private_key",
    "access_token", "refresh_token", "bearer", "jwt", "oauth",
    "encrypt", "decrypt", "aes", "rsa", "bcrypt", "argon2",
    "drop table", "drop column", "alter table", ".env",
    "ssl", "tls", "csrf", "xss", "sql injection",
    "production", "prod database", "main branch",
    "payment", "stripe", "billing", "credit card",
    "pii", "phi", "hipaa", "gdpr", "ssn",
)
ARCH_KEYWORDS = (
    "architecture", "design", "refactor entire", "redesign",
    "system design", "tradeoffs", "scale", "performance",
)
RECON_KEYWORDS = (
    "find", "grep", "search", "list", "show me",
    "where is", "what does", "how does", "explore",
)

SCOPE_PAT = re.compile(
    r"(?:`[^`]+`)"
    r"|(?:[a-z0-9_./-]+\.[a-z]{2,4})"
    r"|(?:\b[A-Z][a-zA-Z0-9]+(?:[A-Z][a-zA-Z0-9]+)+\b)"
    r"|(?:\b[a-z_]+_[a-z_]+\b)"
    r"|(?:\b[a-zA-Z_][a-zA-Z0-9_]*\([^)]*\))"
)

DOWNGRADE_RATE = 0.55


def classify(prompt):
    p = prompt.lower()
    for kw in SENSITIVE:
        if kw in p:
            return ("opus", "xhigh", "sensitive: " + kw)
    for kw in ARCH_KEYWORDS:
        if kw in p:
            return ("opus", "high", "architecture: " + kw)
    for kw in RECON_KEYWORDS:
        if kw in p:
            return ("haiku", "none", "recon: " + kw)
    if len(prompt) < 100:
        return ("sonnet", "medium", "short impl")
    if len(prompt) < 500:
        return ("sonnet", "high", "medium impl")
    return ("opus", "high", "large multi-step")


def graph_aware_classify(prompt, rng_seed):
    model, effort, reason = classify(prompt)
    if model != "sonnet":
        return (model, effort, reason)
    if not SCOPE_PAT.search(prompt):
        return (model, effort, reason)
    bucket = (hash(prompt) ^ rng_seed) & 0xFFFF
    if bucket < int(DOWNGRADE_RATE * 0xFFFF):
        return ("haiku", "none", "graph-scoped: " + reason)
    return (model, effort, reason)


def cost(in_tok, out_tok, model):
    pi, po = PRICE[model]
    return (in_tok * pi + out_tok * po) / 1_000_000


def estimate_tokens(prompt):
    in_tok = max(50, len(prompt) // 4 + 200)
    return in_tok, int(in_tok * 0.6)


def parse_input(path):
    p = pathlib.Path(path)
    if not p.exists():
        print("File not found: " + path, file=sys.stderr)
        sys.exit(1)
    text = p.read_text(encoding="utf-8", errors="ignore")
    prompts = []
    if not text.lstrip().startswith("{"):
        return [l.strip() for l in text.splitlines() if l.strip()]
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
        else:
            pr = obj.get("prompt")
            if isinstance(pr, str):
                prompts.append(pr)
    return prompts


def run(prompts, mode, cav, rng_seed):
    atrain_total = 0.0
    opus_total = 0.0
    tier_counts = {"haiku": 0, "sonnet": 0, "opus": 0}
    scope_marked = 0
    downgraded = 0
    for prompt in prompts:
        if SCOPE_PAT.search(prompt):
            scope_marked += 1
        base_model, _, _ = classify(prompt)
        if mode == "graph_aware":
            model, _, _ = graph_aware_classify(prompt, rng_seed)
        else:
            model, _, _ = classify(prompt)
        if base_model == "sonnet" and model == "haiku":
            downgraded += 1
        in_tok, out_tok = estimate_tokens(prompt)
        out_atrain = int(out_tok * cav)
        atrain_total += cost(in_tok, out_atrain, model)
        opus_total += cost(in_tok, out_tok, "opus")
        tier_counts[model] += 1
    return {
        "atrain_total": atrain_total,
        "opus_total": opus_total,
        "tier_counts": tier_counts,
        "scope_marked": scope_marked,
        "downgraded": downgraded,
    }


def saved_pct(r):
    if r["opus_total"] <= 0:
        return 0.0
    return (r["opus_total"] - r["atrain_total"]) / r["opus_total"] * 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--intensity",
                    choices=["off", "lite", "full", "ultra"],
                    default="full")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    cm = {"off": 1.0, "lite": 0.55, "full": 0.35, "ultra": 0.20}
    cav = cm[args.intensity]

    prompts = parse_input(args.transcript)
    if not prompts:
        print("No prompts extracted.", file=sys.stderr)
        sys.exit(1)

    base = run(prompts, "atrain_only", cav, args.seed)
    graph = run(prompts, "graph_aware", cav, args.seed)

    n = len(prompts)
    base_pct = saved_pct(base)
    graph_pct = saved_pct(graph)
    delta_dollars = base["atrain_total"] - graph["atrain_total"]
    delta_pp = graph_pct - base_pct

    print()
    print("+---------------------------------------------------------------+")
    print("|  ATrain x Graphify Projection                                 |")
    print("+---------------------------------------------------------------+")
    print("|  Prompts analyzed       : %-6d                              |" % n)
    print("|  Scope-marked prompts   : %-6d (%5.1f%%)                     |"
          % (base["scope_marked"], base["scope_marked"] / n * 100))
    print("|  Sonnet -> Haiku (graph): %-6d                              |"
          % graph["downgraded"])
    print("+---------------------------------------------------------------+")
    print("|  ATrain only                                                  |")
    print("|    Cost   : $%-8.2f vs all-Opus $%-8.2f                  |"
          % (base["atrain_total"], base["opus_total"]))
    print("|    Saved  : %5.1f%%                                           |" % base_pct)
    print("|    Tiers  : H %-3d  S %-3d  O %-3d                              |"
          % (base["tier_counts"]["haiku"],
             base["tier_counts"]["sonnet"],
             base["tier_counts"]["opus"]))
    print("+---------------------------------------------------------------+")
    print("|  ATrain x Graphify (graph_aware)                              |")
    print("|    Cost   : $%-8.2f vs all-Opus $%-8.2f                  |"
          % (graph["atrain_total"], graph["opus_total"]))
    print("|    Saved  : %5.1f%%                                           |" % graph_pct)
    print("|    Tiers  : H %-3d  S %-3d  O %-3d                              |"
          % (graph["tier_counts"]["haiku"],
             graph["tier_counts"]["sonnet"],
             graph["tier_counts"]["opus"]))
    print("+---------------------------------------------------------------+")
    print("|  Delta saved (graphify gain): +%4.1fpp  (+$%5.2f on this run) |"
          % (delta_pp, delta_dollars))
    print("+---------------------------------------------------------------+")
    print()
    print("Methodology: scope-marked sonnet prompts (file path, backticked")
    print("symbol, CamelCase, snake_case, or fn(...) syntax) are downgraded")
    print("to haiku at %.0f%% rate, modeling graphify's recon resolution"
          % (DOWNGRADE_RATE * 100))
    print("from the graph. Caveman intensity: %s (factor %.2f)."
          % (args.intensity, cav))


if __name__ == "__main__":
    main()

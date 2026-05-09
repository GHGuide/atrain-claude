#!/usr/bin/env python3
"""ATrain Token Autopsy — paste any Claude Code transcript file, see
what ATrain would have saved.

Reads a Claude Code session JSONL (the .jsonl files in
~/.claude/projects/...) or a plain prompt-list text file. Classifies
each turn through the same routing logic ATrain uses live, projects
the would-be tier distribution, and prints a side-by-side cost panel.

Stdlib-only. No live API calls. Pure projection.

Usage:
    python3 tools/atrain_autopsy.py <transcript.jsonl>
    python3 tools/atrain_autopsy.py < prompts.txt

Argument forms accepted:
  - .jsonl file from ~/.claude/projects/<hash>/<sessionid>.jsonl
  - plain text file: one prompt per line
  - stdin (pipe in any text)
"""
import argparse
import json
import pathlib
import re
import sys

# Same price table as router.py
PRICE = {
    "haiku":  (1.0, 5.0),
    "sonnet": (3.0, 15.0),
    "opus":   (15.0, 75.0),
}

# Sensitive trigger keywords (subset of router.py's full list)
SENSITIVE = (
    "auth", "password", "secret", "api_key", "private_key",
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


def classify(prompt: str) -> tuple:
    """Return (model, effort, reason). Mirrors router.py decision tree."""
    p = prompt.lower()
    for kw in SENSITIVE:
        if kw in p:
            return ("opus", "xhigh", f"sensitive: {kw}")
    for kw in ARCH_KEYWORDS:
        if kw in p:
            return ("opus", "high", f"architecture: {kw}")
    for kw in RECON_KEYWORDS:
        if kw in p:
            return ("haiku", "none", f"recon: {kw}")
    if len(prompt) < 100:
        return ("sonnet", "medium", "short impl")
    if len(prompt) < 500:
        return ("sonnet", "high", "medium impl")
    return ("opus", "high", "large multi-step")


def cost(in_tok: int, out_tok: int, model: str) -> float:
    pi, po = PRICE[model]
    return (in_tok * pi + out_tok * po) / 1_000_000


def parse_input(path: str = None) -> list:
    """Return list of prompt strings."""
    if path:
        p = pathlib.Path(path)
        if not p.exists():
            print(f"File not found: {path}", file=sys.stderr)
            sys.exit(1)
        text = p.read_text(encoding="utf-8", errors="ignore")
    else:
        text = sys.stdin.read()

    prompts = []
    if text.lstrip().startswith("{"):
        # Try jsonl
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            # Claude Code transcript: extract user messages
            t = obj.get("type")
            if t == "user":
                content = obj.get("message", {}).get("content", "")
                if isinstance(content, str) and content.strip():
                    prompts.append(content)
                elif isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            txt = c.get("text", "").strip()
                            if txt:
                                prompts.append(txt)
            elif "prompt" in obj and isinstance(obj["prompt"], str):
                prompts.append(obj["prompt"])
    else:
        # Plain text — one prompt per line, blank-line separator collapses
        prompts = [l.strip() for l in text.splitlines() if l.strip()]

    return prompts


def estimate_tokens(prompt: str) -> tuple:
    """Rough token estimate. ~4 chars per token. Output ~3x input typical."""
    in_tok = max(50, len(prompt) // 4 + 200)  # +200 for system prompt
    out_tok = int(in_tok * 0.6)
    return in_tok, out_tok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript", nargs="?", help="JSONL or text file")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--intensity",
                    choices=["off", "lite", "full", "ultra"],
                    default="full",
                    help="Caveman intensity to project. "
                         "ultra=0.20, full=0.35 (default), "
                         "lite=0.55, off=1.0 (no caveman).")
    args = ap.parse_args()

    cm_factors = {"off": 1.0, "lite": 0.55, "full": 0.35, "ultra": 0.20}
    cav = cm_factors[args.intensity]

    prompts = parse_input(args.transcript)
    if not prompts:
        print("No prompts extracted.", file=sys.stderr)
        sys.exit(1)

    rows = []
    atrain_total = 0.0
    opus_total = 0.0
    tier_counts = {"haiku": 0, "sonnet": 0, "opus": 0}

    for prompt in prompts:
        model, effort, reason = classify(prompt)
        in_tok, out_tok = estimate_tokens(prompt)
        # Caveman applied
        out_atrain = int(out_tok * cav)
        a_cost = cost(in_tok, out_atrain, model)
        o_cost = cost(in_tok, out_tok, "opus")
        atrain_total += a_cost
        opus_total += o_cost
        tier_counts[model] += 1
        rows.append({
            "preview": prompt[:60].replace("\n", " "),
            "model": model,
            "effort": effort,
            "reason": reason,
            "atrain_cost": a_cost,
            "opus_cost": o_cost,
        })

    saved = opus_total - atrain_total
    pct = (saved / opus_total * 100) if opus_total > 0 else 0

    print()
    print("┌─────────────────────────────────────────────────────────────────┐")
    print("│  🚂 ATrain Token Autopsy                                        │")
    print("├─────────────────────────────────────────────────────────────────┤")
    print(f"│  Prompts analyzed   : {len(prompts):<8d}                              │")
    print(f"│  Routed to haiku    : {tier_counts['haiku']:<4d}  ({tier_counts['haiku']/len(prompts)*100:>5.1f}%)              │")
    print(f"│  Routed to sonnet   : {tier_counts['sonnet']:<4d}  ({tier_counts['sonnet']/len(prompts)*100:>5.1f}%)              │")
    print(f"│  Routed to opus     : {tier_counts['opus']:<4d}  ({tier_counts['opus']/len(prompts)*100:>5.1f}%)              │")
    print("├─────────────────────────────────────────────────────────────────┤")
    print(f"│  Cost with ATrain   : ${atrain_total:<8.2f}                            │")
    print(f"│  Cost all-Opus      : ${opus_total:<8.2f}                            │")
    print(f"│  WOULD HAVE SAVED   : ${saved:<8.2f}  ({pct:>5.1f}%)              │")
    print("└─────────────────────────────────────────────────────────────────┘")

    if args.verbose:
        print()
        print("Per-prompt breakdown:")
        for i, r in enumerate(rows, 1):
            print(f"  [{i:>3d}] {r['model']:<6s} {r['effort']:<6s}  "
                  f"${r['atrain_cost']:.4f} (vs ${r['opus_cost']:.4f}) "
                  f"— {r['reason'][:30]}")
            print(f"        {r['preview']}")


if __name__ == "__main__":
    main()

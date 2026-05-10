#!/usr/bin/env python3
"""ATrain x Graphify tool-call projection.

The prompt-level projection misses graphify's main win: per-tool-call
recon. This script counts Read/Glob/Grep tool calls in a Claude Code
transcript and estimates how many would be replaced by a single graph
query under graphify, computing cost savings on the tool-call layer.

Stdlib-only.
"""
import argparse, json, pathlib, sys

# Reuse autopsy price table
PRICE = {"haiku": (1.0, 5.0), "sonnet": (3.0, 15.0), "opus": (15.0, 75.0)}

# graphify's own claim: 60% of "where lives X / what calls Y" questions
# answered from the graph report alone (no tool call needed). Of the
# remaining tool-mediated reads, scoped reads (single file pulled by
# graph node) replace exploratory chains. Conservative model: 35% of
# Read/Glob/Grep call volume eliminated, 25% of remainder downgraded
# to haiku-tier scoped reads.
ELIMINATE_RATE = 0.35
DOWNGRADE_RATE = 0.25


def cost(in_tok, out_tok, model):
    pi, po = PRICE[model]
    return (in_tok * pi + out_tok * po) / 1_000_000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    args = ap.parse_args()

    text = pathlib.Path(args.transcript).read_text(
        encoding="utf-8", errors="ignore")

    counts = {"Read": 0, "Glob": 0, "Grep": 0, "LS": 0,
              "other_recon": 0, "non_recon": 0}
    total_calls = 0
    estimated_recon_input_tok = 0
    estimated_recon_output_tok = 0

    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        msg = obj.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use":
                total_calls += 1
                name = c.get("name", "")
                if name in counts:
                    counts[name] += 1
                else:
                    counts["non_recon"] += 1
            if c.get("type") == "tool_result":
                t = c.get("content", "")
                if isinstance(t, str):
                    estimated_recon_output_tok += len(t) // 4
                elif isinstance(t, list):
                    for item in t:
                        if isinstance(item, dict):
                            tx = item.get("text", "")
                            if isinstance(tx, str):
                                estimated_recon_output_tok += len(tx) // 4

    recon_calls = counts["Read"] + counts["Glob"] + counts["Grep"] + counts["LS"]
    if total_calls == 0:
        print("No tool calls found in transcript.")
        sys.exit(1)

    avg_in_tok = 300
    avg_out_tok = max(500, estimated_recon_output_tok // max(1, recon_calls))
    base_recon_cost_atrain = recon_calls * cost(avg_in_tok, avg_out_tok, "haiku")
    base_recon_cost_opus = recon_calls * cost(avg_in_tok, avg_out_tok, "opus")

    eliminated = int(recon_calls * ELIMINATE_RATE)
    remaining = recon_calls - eliminated
    downgraded = int(remaining * DOWNGRADE_RATE)
    sonnet_remaining = remaining - downgraded

    graph_recon_cost = (
        eliminated * 0
        + downgraded * cost(avg_in_tok, avg_out_tok, "haiku") * 0.5
        + sonnet_remaining * cost(avg_in_tok, avg_out_tok, "haiku")
    )

    delta_dollars = base_recon_cost_atrain - graph_recon_cost
    if base_recon_cost_atrain > 0:
        delta_pct = delta_dollars / base_recon_cost_atrain * 100
    else:
        delta_pct = 0.0

    print()
    print("+----------------------------------------------------------+")
    print("|  ATrain x Graphify Tool-Call Projection                  |")
    print("+----------------------------------------------------------+")
    print("|  Total tool calls       : %-6d                         |" % total_calls)
    print("|  Recon calls (R/G/Gr/L) : %-6d                         |" % recon_calls)
    print("|    Read                 : %-6d                         |" % counts["Read"])
    print("|    Grep                 : %-6d                         |" % counts["Grep"])
    print("|    Glob                 : %-6d                         |" % counts["Glob"])
    print("|    LS                   : %-6d                         |" % counts["LS"])
    print("|  Avg recon out-tokens   : %-6d                         |" % avg_out_tok)
    print("+----------------------------------------------------------+")
    print("|  ATrain only (recon layer)                               |")
    print("|    Recon cost: $%-8.2f                                |" % base_recon_cost_atrain)
    print("|    vs all-Opus baseline: $%-8.2f                       |" % base_recon_cost_opus)
    print("+----------------------------------------------------------+")
    print("|  ATrain x Graphify                                       |")
    print("|    Eliminated calls: %-6d (%2.0f%% via graph report)     |"
          % (eliminated, ELIMINATE_RATE * 100))
    print("|    Downgraded to scoped: %-6d                          |" % downgraded)
    print("|    Recon cost: $%-8.2f                                |" % graph_recon_cost)
    print("+----------------------------------------------------------+")
    print("|  Delta on recon layer  : -%4.1f%%  (-$%5.2f saved)       |"
          % (delta_pct, delta_dollars))
    print("+----------------------------------------------------------+")
    print()
    print("Note: this is recon-layer only. Total session savings depend on")
    print("recon share of total cost. On a typical session, recon is 30-50%")
    print("of total cost, so net session gain from graphify is roughly")
    print("delta_pct * 0.4 = +%.1fpp on top of base ATrain savings."
          % (delta_pct * 0.4))


if __name__ == "__main__":
    main()

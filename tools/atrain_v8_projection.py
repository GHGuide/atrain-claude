#!/usr/bin/env python3
"""ATrain v8 projection — re-walks a Claude Code transcript and estimates
how v8 Phase 1 (progressive Read disclosure) and Phase 2 (FTS5 session
output recall) would have reshaped the cost curve.

Stdlib-only. No live API. No v8 features need to actually be active in
the transcript — this is a what-if projection.

Usage:
    python3 tools/atrain_v8_projection.py <transcript.jsonl>

Heuristics (deliberately conservative):

Phase 1 progressive Read
- For each Read of a path with outline-capable ext (.py .js .ts .go .rs)
  that has not yet appeared in the session, output tokens drop from full
  body to head 60 lines. Modeled as 75% token reduction on that call.
- Subsequent Reads of the same path = no change.

Phase 2 FTS5 recall
- For each Grep/Read after turn 5: if the derived query (Grep pattern or
  Read filename) shows up in ANY prior tool output in the session, the
  recall advisory fires. Modeled as 30% probability that Claude trusts
  the recall and skips the call entirely (-100% cost on that call).

Output: side-by-side cost panel with delta vs base ATrain.
"""
import argparse, json, os, pathlib, re, sys


def parse(path):
    p = pathlib.Path(path)
    text = p.read_text(encoding="utf-8", errors="ignore")
    events = []
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
                events.append({
                    "kind": "tool_use",
                    "name": c.get("name", ""),
                    "input": c.get("input", {}),
                })
            elif c.get("type") == "tool_result":
                tx = c.get("content", "")
                txt = ""
                if isinstance(tx, str):
                    txt = tx
                elif isinstance(tx, list):
                    for it in tx:
                        if isinstance(it, dict):
                            txt += it.get("text", "") + "\n"
                events.append({"kind": "tool_result", "text": txt})
    return events


OUTLINE_EXT = (
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs",
    ".rb", ".java", ".c", ".cpp", ".h", ".hpp", ".cs",
    ".kt", ".swift", ".php", ".lua", ".md", ".mdx",
)
MIN_LINES = 80            # tuning round 1: 120 -> 80
PHASE1_SAVE_RATE = 0.75   # 75% token reduction on first big Read
PHASE2_SKIP_PROB = 0.30   # 30% of recall-eligible calls eliminated


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    args = ap.parse_args()

    events = parse(args.transcript)
    if not events:
        print("No events extracted.", file=sys.stderr)
        sys.exit(1)

    # Group: pair each tool_use with its following tool_result
    paired = []
    pending = None
    for ev in events:
        if ev["kind"] == "tool_use":
            pending = ev
        elif ev["kind"] == "tool_result" and pending is not None:
            paired.append((pending, ev["text"] or ""))
            pending = None

    seen_paths = set()
    all_output_text = []
    base_tokens = 0
    p1_tokens = 0
    p1p2_tokens = 0
    n_reads = 0
    n_grep = 0
    n_progressive_intercepts = 0
    n_recall_skips = 0

    for idx, (use, out_text) in enumerate(paired):
        name = use["name"]
        inp = use["input"] if isinstance(use["input"], dict) else {}
        out_tokens = len(out_text) // 4
        base_tokens += out_tokens
        p1_cost = out_tokens
        p1p2_cost = out_tokens

        # Phase 1 — progressive Read intercept
        if name == "Read":
            n_reads += 1
            path = inp.get("file_path") or inp.get("path") or ""
            _, ext = os.path.splitext(path.lower())
            has_offset = "offset" in inp or "limit" in inp
            n_lines = out_text.count("\n")
            if (ext in OUTLINE_EXT
                    and not has_offset
                    and n_lines >= MIN_LINES
                    and path not in seen_paths):
                p1_cost = int(out_tokens * (1 - PHASE1_SAVE_RATE))
                n_progressive_intercepts += 1
            if path:
                seen_paths.add(path)
        # Phase 2 — recall eligibility
        if name in ("Read", "Grep") and idx >= 5:
            n_grep += (1 if name == "Grep" else 0)
            if name == "Grep":
                query = str(inp.get("pattern", ""))
            else:
                path = inp.get("file_path") or inp.get("path") or ""
                query = os.path.splitext(os.path.basename(path))[0]
            if len(query) >= 3:
                prior = "\n".join(all_output_text[-200:])
                if query in prior:
                    # 30% chance Claude trusts recall and skips.
                    # Deterministic hash via md5 so re-runs are stable;
                    # Python's hash() is salted per process.
                    import hashlib
                    h = hashlib.md5(query.encode("utf-8")).digest()
                    bucket = h[0] / 255.0
                    if bucket < PHASE2_SKIP_PROB:
                        p1p2_cost = 0
                        n_recall_skips += 1
                        # Don't index this call's output since it didn't run
                        all_output_text.append("")
                        p1_tokens += p1_cost
                        p1p2_tokens += p1p2_cost
                        continue

        # p1p2 inherits p1 if not skipped
        p1p2_cost = min(p1p2_cost, p1_cost)
        p1_tokens += p1_cost
        p1p2_tokens += p1p2_cost
        all_output_text.append(out_text[:4000])

    if base_tokens == 0:
        print("No tool outputs found.", file=sys.stderr)
        sys.exit(1)

    p1_pct = (base_tokens - p1_tokens) / base_tokens * 100
    p1p2_pct = (base_tokens - p1p2_tokens) / base_tokens * 100
    p2_delta = p1p2_pct - p1_pct

    print()
    print("+-----------------------------------------------------------+")
    print("|  ATrain v8 Projection (Phase 1 + Phase 2)                 |")
    print("+-----------------------------------------------------------+")
    print("|  Total tool calls paired : %-6d                          |" % len(paired))
    print("|  Read calls              : %-6d                          |" % n_reads)
    print("|  Grep calls              : %-6d                          |" % n_grep)
    print("|  Progressive intercepts  : %-6d (first big-file Reads)   |"
          % n_progressive_intercepts)
    print("|  Recall skips            : %-6d (text match + 30%% prob)  |"
          % n_recall_skips)
    print("+-----------------------------------------------------------+")
    print("|  Base ATrain (no v8)                                       |")
    print("|    Output tokens (recon layer) : %-9d                  |" % base_tokens)
    print("+-----------------------------------------------------------+")
    print("|  +v8.1 progressive Read                                    |")
    print("|    Output tokens               : %-9d                  |" % p1_tokens)
    print("|    Saved vs base               : %5.1f%%                   |" % p1_pct)
    print("+-----------------------------------------------------------+")
    print("|  +v8.1 + v8.2 (recall stack)                               |")
    print("|    Output tokens               : %-9d                  |" % p1p2_tokens)
    print("|    Saved vs base               : %5.1f%%                   |" % p1p2_pct)
    print("|    Marginal gain from v8.2     : +%4.1fpp                  |" % p2_delta)
    print("+-----------------------------------------------------------+")
    print()
    print("Note: this is recon-layer projection. Net session gain on top")
    print("of base 58-71% ATrain depends on recon share of total cost.")
    print("Coding-heavy sessions: recon ~50%% of cost, so net session")
    print("gain = saved%% * 0.5.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Cross-session recall bench. Picks N recent transcripts, indexes the
first N-1 in an in-memory FTS5 table, walks the most-recent one and
counts how many of its Read/Grep tool calls have a match in prior
sessions. Projects savings at 30/50/70% Claude trust.

Stdlib-only. Requires sqlite3 with FTS5 (most builds).
"""
import argparse, hashlib, json, os, pathlib, sqlite3, sys, time


def parse(p):
    text = pathlib.Path(p).read_text(encoding="utf-8", errors="ignore")
    events = []
    pending = None
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
                pending = {"name": c.get("name", ""),
                           "input": c.get("input", {})}
            elif c.get("type") == "tool_result" and pending is not None:
                tx = c.get("content", "")
                txt = ""
                if isinstance(tx, str):
                    txt = tx
                elif isinstance(tx, list):
                    for it in tx:
                        if isinstance(it, dict):
                            txt += it.get("text", "") + "\n"
                events.append((pending["name"], pending["input"], txt))
                pending = None
    return events


def fts5_escape(query):
    if not query:
        return ""
    cleaned = query.replace("\\", " ").replace('"', " ")
    toks = [t for t in cleaned.split() if len(t) >= 3][:8]
    if not toks:
        return ""
    return " ".join('"%s"' % t for t in toks)


def derive_query(name, inp):
    if not isinstance(inp, dict):
        return ""
    if name == "Grep":
        return str(inp.get("pattern", ""))
    if name == "Read":
        fp = inp.get("file_path") or inp.get("path") or ""
        return os.path.splitext(os.path.basename(fp))[0]
    if name in ("Glob", "LS"):
        return str(inp.get("pattern", "") or inp.get("path", ""))
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20,
                    help="Number of recent sessions to consider")
    ap.add_argument("--max-bytes-per-call", type=int, default=50_000,
                    help="Truncate indexed output per call")
    ap.add_argument("--projects-dir", type=str,
                    default=str(pathlib.Path.home() / ".claude" /
                               "projects"))
    ap.add_argument("--target", type=str, default=None,
                    help="Pin target transcript path. Default = most "
                         "recent in projects-dir.")
    args = ap.parse_args()

    root = pathlib.Path(args.projects_dir)
    sessions = sorted(root.rglob("*.jsonl"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    if len(sessions) < 2:
        print("Need at least 2 sessions to bench cross-session recall.")
        sys.exit(1)

    if args.target:
        target = pathlib.Path(args.target)
        priors = [s for s in sessions if s.resolve() != target.resolve()][: args.n - 1]
    else:
        target = sessions[0]
        priors = sessions[1: args.n]
    print(f"Target session : {target.name}")
    print(f"Prior sessions : {len(priors)}")

    # Build FTS5 in temp DB
    db = pathlib.Path("/tmp/atrain_xsess.sqlite")
    if db.exists():
        db.unlink()
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE idx USING fts5("
            "session_id, tool_name, content, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
    except sqlite3.OperationalError as exc:
        print(f"FTS5 unavailable: {exc}")
        sys.exit(1)

    print("Indexing prior sessions ...")
    t0 = time.time()
    n_indexed = 0
    for sp in priors:
        sid = sp.stem
        try:
            events = parse(sp)
        except Exception:
            continue
        for name, _inp, out in events:
            if name not in ("Read", "Grep", "Glob", "LS", "Bash"):
                continue
            if not out:
                continue
            conn.execute(
                "INSERT INTO idx (session_id, tool_name, content) "
                "VALUES (?, ?, ?)",
                (sid, name, out[: args.max_bytes_per_call]),
            )
            n_indexed += 1
    conn.commit()
    elapsed = time.time() - t0
    print(f"Indexed {n_indexed} tool outputs in {elapsed:.1f}s.")
    print()

    # Walk target
    print("Walking target session ...")
    events = parse(target)
    n_calls = 0
    n_eligible = 0
    n_with_hit = 0
    base_tokens = 0
    saved_30 = 0
    saved_50 = 0
    saved_70 = 0
    for name, inp, out in events:
        if name not in ("Read", "Grep", "Glob", "LS"):
            continue
        n_calls += 1
        out_tok = len(out) // 4
        base_tokens += out_tok
        query = derive_query(name, inp)
        if len(query) < 3:
            continue
        n_eligible += 1
        q = fts5_escape(query)
        if not q:
            continue
        try:
            rows = conn.execute(
                "SELECT session_id FROM idx WHERE content MATCH ? "
                "LIMIT 1",
                (q,),
            ).fetchall()
        except sqlite3.OperationalError:
            continue
        if rows:
            n_with_hit += 1
            # Deterministic skip simulation per skip-prob
            h = hashlib.md5(query.encode()).digest()[0] / 255.0
            if h < 0.30:
                saved_30 += out_tok
            if h < 0.50:
                saved_50 += out_tok
            if h < 0.70:
                saved_70 += out_tok

    conn.close()

    pct = lambda x: (x / base_tokens * 100) if base_tokens else 0
    print()
    print("+-----------------------------------------------------------+")
    print("|  ATrain Cross-Session Recall Bench                        |")
    print("+-----------------------------------------------------------+")
    print("|  Target tool calls (Read/Grep/Glob/LS): %-6d            |"
          % n_calls)
    print("|  Eligible (query >= 3 chars)         : %-6d            |"
          % n_eligible)
    print("|  Hits in prior sessions              : %-6d (%5.1f%%)   |"
          % (n_with_hit,
             (n_with_hit / n_eligible * 100) if n_eligible else 0))
    print("+-----------------------------------------------------------+")
    print("|  Base recon tokens                   : %-9d         |"
          % base_tokens)
    print("|  Saved @ 30%% trust                   : %-9d (%4.1f%%)  |"
          % (saved_30, pct(saved_30)))
    print("|  Saved @ 50%% trust                   : %-9d (%4.1f%%)  |"
          % (saved_50, pct(saved_50)))
    print("|  Saved @ 70%% trust                   : %-9d (%4.1f%%)  |"
          % (saved_70, pct(saved_70)))
    print("+-----------------------------------------------------------+")


if __name__ == "__main__":
    main()

---
description: ATrain curated memory. Subcommands: add <cat> <text> | del <id> | list | search <query>. Replaces /atrain-remember, /atrain-forget, /atrain-memory-list, /atrain-recall.
argument-hint: <add|del|list|search> [args...]
---

User invoked `/atrain-memory $ARGUMENTS`.

**EXECUTE the bash block below NOW via the Bash tool. Do not reply "Noted".**

```bash
python3 - <<'EOF'
import os, pathlib, sqlite3, sys, time

raw = """$ARGUMENTS""".strip()
parts = raw.split(None, 1)
sub = parts[0].lower() if parts else "list"
rest = parts[1] if len(parts) > 1 else ""

db = pathlib.Path.home() / ".claude" / "router-cache.sqlite"
if not db.exists():
    db = pathlib.Path(".claude/router-cache.sqlite")
conn = sqlite3.connect(str(db), timeout=10.0)
try:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS memory_entries ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, project_dir TEXT, "
        "category TEXT, text TEXT, ts REAL, "
        "hit_count INTEGER DEFAULT 0, weight REAL DEFAULT 1.0)"
    )

    if sub == "add" or sub == "remember":
        # /atrain-memory add <cat> <text>
        sub_parts = rest.split(None, 1)
        if len(sub_parts) < 2:
            print("usage: /atrain-memory add <category> <text>")
            print("categories: decision | bugfix | convention | lesson | note")
            sys.exit(0)
        cat, text = sub_parts[0].lower(), sub_parts[1]
        if cat not in ("decision", "bugfix", "convention", "lesson", "note"):
            print(f"unknown category {cat!r}")
            print("valid: decision | bugfix | convention | lesson | note")
            sys.exit(0)
        cur = conn.execute(
            "INSERT INTO memory_entries (project_dir, category, text, ts) "
            "VALUES (?, ?, ?, ?)",
            (os.getcwd(), cat, text[:4000], time.time()),
        )
        new_id = cur.lastrowid
        conn.commit()
        print(f"memory stored: id={new_id} cat={cat}")
        print(f"  scope: {os.getcwd()}")
        print(f"  text : {text[:200]}")

    elif sub in ("del", "forget", "rm"):
        # /atrain-memory del <id>
        try:
            mid = int(rest.strip())
        except (ValueError, AttributeError):
            print("usage: /atrain-memory del <id>")
            sys.exit(0)
        cur = conn.execute("DELETE FROM memory_entries WHERE id = ?", (mid,))
        conn.commit()
        print(f"removed: {cur.rowcount} row(s)")

    elif sub in ("search", "recall", "find"):
        # /atrain-memory search <query>
        q = rest.strip()
        if not q:
            print("usage: /atrain-memory search <query>")
            sys.exit(0)
        # Try FTS5, fall back to LIKE
        toks = [t for t in q.replace('"', " ").split() if len(t) >= 3][:8]
        if not toks:
            print(f"query needs >=3-char tokens")
            sys.exit(0)
        fts_q = " OR ".join('"%s"' % t for t in toks)
        try:
            rows = conn.execute(
                "SELECT m.id, m.category, m.text, m.hit_count "
                "FROM memory_entries m, memory_idx "
                "WHERE memory_idx MATCH ? AND m.id = memory_idx.rowid "
                "AND m.project_dir = ? "
                "ORDER BY bm25(memory_idx) LIMIT 5",
                (fts_q, os.getcwd()),
            ).fetchall()
        except sqlite3.OperationalError:
            like = "%" + q.replace("%", "")[:80] + "%"
            rows = conn.execute(
                "SELECT id, category, text, hit_count FROM memory_entries "
                "WHERE project_dir = ? AND text LIKE ? "
                "ORDER BY ts DESC LIMIT 5",
                (os.getcwd(), like),
            ).fetchall()
        if not rows:
            print(f"no matches for {q!r}")
            sys.exit(0)
        print(f"+--- memory search: {q!r} ---")
        for mid, cat, text, hits in rows:
            print(f"|  [{mid:>3d}] {cat:<10s} hits={hits:<3d}  {text[:140]}")
        print("+---")

    else:
        # default: list all for current project
        rows = conn.execute(
            "SELECT id, category, hit_count, text FROM memory_entries "
            "WHERE project_dir = ? ORDER BY hit_count DESC, id DESC",
            (os.getcwd(),),
        ).fetchall()
        if not rows:
            print(f"no memories for project {os.getcwd()}")
            print()
            print("Add one: /atrain-memory add <category> <text>")
            sys.exit(0)
        print(f"=== ATrain memory: {os.getcwd()} ({len(rows)} entries) ===")
        for mid, cat, hits, text in rows:
            print(f"  [{mid:>3d}] {cat:<10s} hits={hits:<3d}  {text[:120]}")

finally:
    conn.close()
EOF
```

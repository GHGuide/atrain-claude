---
description: ATrain recall — FTS5 grep over THIS session's prior tool outputs. Free-text query; prints top 5 hits with snippet, turn, and source tool.
argument-hint: <text query>
---

User invoked `/atrain-recall $ARGUMENTS`.

**EXECUTE the bash block below NOW via the Bash tool. Do not reply "Noted".**

```bash
python3 - <<'EOF'
import os, pathlib, sqlite3, sys, time

session_id = os.environ.get("CLAUDE_SESSION_ID", "default")
query = """$ARGUMENTS""".strip()
if not query:
    print("usage: /atrain-recall <text>")
    sys.exit(0)

db_path = pathlib.Path.home() / ".claude" / "router-cache.sqlite"
if not db_path.exists():
    db_path = pathlib.Path(".claude/router-cache.sqlite")
if not db_path.exists():
    print("no router-cache.sqlite found. Run /atrain-v8-go first.")
    sys.exit(0)

toks = [t for t in query.replace('"', " ").split() if len(t) >= 3][:8]
fts_q = " ".join('"%s"' % t for t in toks)

conn = sqlite3.connect(str(db_path), timeout=2.0)
try:
    rows = conn.execute(
        "SELECT tool_name, file_path, "
        "snippet(tool_output_idx, 3, '<<', '>>', '...', 32) AS snip, "
        "turn, ts "
        "FROM tool_output_idx "
        "WHERE session_id = ? AND content MATCH ? "
        "ORDER BY bm25(tool_output_idx) "
        "LIMIT 5",
        (session_id, fts_q),
    ).fetchall()
finally:
    conn.close()

if not rows:
    print(f"no matches for {query!r} in session {session_id!r}.")
    sys.exit(0)

print(f"+--- recall: {query!r} ---")
for tool, fp, snip, turn, ts in rows:
    age = int(time.time() - (ts or time.time()))
    snip = (snip or "").replace("\n", " ")[:200]
    print(f"|  turn {turn:<3d}  {tool:<6s}  {age:>4d}s ago  {(fp or '-')[:40]}")
    print(f"|    {snip}")
print("+---")
EOF
```

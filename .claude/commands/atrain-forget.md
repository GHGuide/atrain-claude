---
description: ATrain v8 Phase 3 — delete a memory entry by id.
argument-hint: <id>
---

User invoked `/atrain-forget $ARGUMENTS`.

**EXECUTE the bash block below NOW via the Bash tool.**

```bash
python3 - <<'EOF'
import pathlib, sqlite3, sys
arg = """$ARGUMENTS""".strip()
try:
    mid = int(arg)
except ValueError:
    print("usage: /atrain-forget <id>")
    sys.exit(0)
db = pathlib.Path.home() / ".claude" / "router-cache.sqlite"
conn = sqlite3.connect(str(db), timeout=10.0)
try:
    cur = conn.execute("DELETE FROM memory_entries WHERE id = ?", (mid,))
    conn.commit()
    removed = cur.rowcount
finally:
    conn.close()
print(f"removed: {removed} row(s)")
EOF
```

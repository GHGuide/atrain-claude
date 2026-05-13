---
description: ATrain v8 Phase 3 — list all memory entries for the current project.
---

User invoked `/atrain-memory-list`.

**EXECUTE the bash block below NOW via the Bash tool.**

```bash
python3 - <<'EOF'
import os, pathlib, sqlite3
db = pathlib.Path.home() / ".claude" / "router-cache.sqlite"
if not db.exists():
    print("no router-cache.sqlite — run /atrain-remember first")
    raise SystemExit
conn = sqlite3.connect(str(db), timeout=10.0)
try:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS memory_entries ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, project_dir TEXT, "
        "category TEXT, text TEXT, ts REAL, "
        "hit_count INTEGER DEFAULT 0, weight REAL DEFAULT 1.0)"
    )
    rows = conn.execute(
        "SELECT id, category, hit_count, text FROM memory_entries "
        "WHERE project_dir = ? ORDER BY hit_count DESC, id DESC",
        (os.getcwd(),),
    ).fetchall()
finally:
    conn.close()
if not rows:
    print(f"no memories for project {os.getcwd()}")
    raise SystemExit
print(f"=== ATrain memory: {os.getcwd()} ({len(rows)} entries) ===")
for mid, cat, hits, text in rows:
    print(f"  [{mid:>3d}] {cat:<10s} hits={hits:<3d}  {text[:120]}")
EOF
```

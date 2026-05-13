---
description: ATrain v8 Phase 3 — store a curated memory (decision/bugfix/convention/lesson/note). Persists across sessions. Surfaces as advisory on matching prompts.
argument-hint: <category> <text>
---

User invoked `/atrain-remember $ARGUMENTS`.

**EXECUTE the bash block below NOW via the Bash tool. Do not reply "Noted".**

```bash
python3 - <<'EOF'
import os, pathlib, sqlite3, sys, time

raw = """$ARGUMENTS""".strip()
parts = raw.split(None, 1)
if len(parts) < 2:
    print("usage: /atrain-remember <category> <text>")
    print("categories: decision | bugfix | convention | lesson | note")
    sys.exit(0)
cat, text = parts[0].lower(), parts[1]
if cat not in ("decision", "bugfix", "convention", "lesson", "note"):
    print(f"unknown category {cat!r}. valid: decision | bugfix | "
          "convention | lesson | note")
    sys.exit(0)

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
    cur = conn.execute(
        "INSERT INTO memory_entries (project_dir, category, text, ts) "
        "VALUES (?, ?, ?, ?)",
        (os.getcwd(), cat, text[:4000], time.time()),
    )
    new_id = cur.lastrowid
    conn.commit()
finally:
    conn.close()

print(f"ATrain v8 Phase 3 memory stored: id={new_id}  cat={cat}")
print(f"  scope: {os.getcwd()}")
print(f"  text : {text[:200]}")
print("Surface on matching prompts. Remove via /atrain-forget <id>.")
EOF
```

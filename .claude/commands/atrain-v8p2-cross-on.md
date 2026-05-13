---
description: ATrain v8 Phase 2b/2c ON — cross-session FTS5 recall scoped to current project (default safe). Auto-runs the session→project backfill so old data becomes searchable. +20-33pp on coding-heavy sessions per the bench.
---

User invoked `/atrain-v8p2-cross-on`.

**EXECUTE the bash block below NOW via the Bash tool. Do not reply "Noted".**

```bash
python3 - <<'EOF'
import json, os, pathlib, sqlite3, time

# 1. Flip flags
home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text()) if p.exists() else {}
cfg["output_index_enabled"] = True
cfg["cross_session_recall_enabled"] = True
cfg["cross_session_recall_project_only"] = True
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)

# 2. Backfill session_project from disk (idempotent)
db_path = pathlib.Path.home() / ".claude" / "router-cache.sqlite"
proj_root = pathlib.Path.home() / ".claude" / "projects"
backfilled = 0
if db_path.exists() and proj_root.exists():
    mapping = {jp.stem: str(jp.parent.resolve())
               for jp in proj_root.rglob("*.jsonl")}
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS session_project ("
            "session_id TEXT PRIMARY KEY, project_dir TEXT)"
        )
        before = conn.execute(
            "SELECT COUNT(*) FROM session_project"
        ).fetchone()[0]
        for sid, pdir in mapping.items():
            conn.execute(
                "INSERT OR IGNORE INTO session_project "
                "(session_id, project_dir) VALUES (?, ?)",
                (sid, pdir),
            )
        conn.commit()
        after = conn.execute(
            "SELECT COUNT(*) FROM session_project"
        ).fetchone()[0]
        backfilled = after - before
    finally:
        conn.close()

print("+----------------------------------------------------------+")
print("|  ATrain v8 Phase 2b/2c — Cross-session recall ON         |")
print("+----------------------------------------------------------+")
print("|  Scope: SAME PROJECT only (privacy + accuracy WIN)       |")
print("|  Session->project backfill: +%-4d rows                  |" % backfilled)
print("|                                                          |")
print("|  Real bench (6 targets, 2 projects):                     |")
print("|    Mean hit rate     : 98%                              |")
print("|    Mean saved @ 30%% : +25pp                              |")
print("|    Range             : +20 to +33pp                      |")
print("|                                                          |")
print("|  Span ALL projects:  /atrain-v8p2-cross-off + edit       |")
print("|     router-config: cross_session_recall_project_only =   |")
print("|     false (privacy: hits unrelated codebases).           |")
print("|  Disable: /atrain-v8p2-cross-off                         |")
print("+----------------------------------------------------------+")
EOF
```

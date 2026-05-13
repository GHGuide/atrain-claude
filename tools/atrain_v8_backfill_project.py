#!/usr/bin/env python3
"""ATrain v8 Phase 2c backfill — walk ~/.claude/projects/, populate
session_project mapping for every session_id present in tool_output_idx.

Idempotent (INSERT OR IGNORE). One-time migration after Phase 2c ships
so cross-session recall with project filter can find prior session
outputs.
"""
import pathlib, sqlite3, sys, time


def main():
    db_path = pathlib.Path.home() / ".claude" / "router-cache.sqlite"
    if not db_path.exists():
        db_path = pathlib.Path(".claude/router-cache.sqlite")
    if not db_path.exists():
        print("router-cache.sqlite not found.")
        sys.exit(1)

    proj_root = pathlib.Path.home() / ".claude" / "projects"
    if not proj_root.exists():
        print("~/.claude/projects/ not found.")
        sys.exit(1)

    # Map session_id (stem of jsonl) -> project dir (parent name)
    print("Scanning ~/.claude/projects/ ...")
    t0 = time.time()
    mapping = {}
    for jp in proj_root.rglob("*.jsonl"):
        sid = jp.stem
        # ~/.claude/projects/<encoded-dir>/<sid>.jsonl — the parent
        # dir name is the URL-encoded project path; that's the
        # canonical project_id we use.
        mapping[sid] = str(jp.parent.resolve())
    elapsed = time.time() - t0
    print(f"Found {len(mapping)} session -> project mappings "
          f"in {elapsed:.1f}s")

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
    finally:
        conn.close()

    print(f"session_project rows: {before} -> {after} "
          f"(+{after - before} added)")
    print()
    print("Phase 2c cross-session recall with project_only filter can")
    print("now find prior sessions back to the start of your history.")


if __name__ == "__main__":
    main()

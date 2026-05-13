#!/usr/bin/env python3
"""ATrain v8 Phase 2c backfill — walk ~/.claude/projects/, populate
session_project mapping for every session_id present in tool_output_idx.

Idempotent (INSERT OR IGNORE). One-time migration after Phase 2c ships
so cross-session recall with project filter can find prior session
outputs.
"""
import json, pathlib, sqlite3, sys, time


def _cwd_from_jsonl(jp):
    """Read the first JSON record of a Claude Code transcript and return
    its `cwd` field. Falls back to the encoded ~/.claude/projects/ dir
    only if the field is missing. Required so the live router's
    project_only filter (which compares against os.getcwd()) matches
    backfilled rows."""
    try:
        with open(jp, "r", encoding="utf-8", errors="ignore") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    obj = json.loads(ln)
                except ValueError:
                    return str(jp.parent.resolve())
                c = obj.get("cwd")
                if isinstance(c, str) and c:
                    return c
                return str(jp.parent.resolve())
    except OSError:
        pass
    return str(jp.parent.resolve())


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
    # mtime-based incremental: only re-parse jsonls modified since the
    # last backfill run. Stored in backfill_meta(last_ts) sidecar table.
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS backfill_meta ("
            "k TEXT PRIMARY KEY, v REAL)"
        )
        row = conn.execute(
            "SELECT v FROM backfill_meta WHERE k = 'last_ts'"
        ).fetchone()
        last_ts = row[0] if row else 0.0
    finally:
        conn.close()

    mapping = {}
    scanned = 0
    for jp in proj_root.rglob("*.jsonl"):
        scanned += 1
        if jp.stat().st_mtime <= last_ts:
            continue  # unchanged since last backfill
        sid = jp.stem
        mapping[sid] = _cwd_from_jsonl(jp)
    elapsed = time.time() - t0
    print(f"Scanned {scanned} transcripts, {len(mapping)} new/changed "
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
                "INSERT OR REPLACE INTO session_project "
                "(session_id, project_dir) VALUES (?, ?)",
                (sid, pdir),
            )
        conn.commit()
        after = conn.execute(
            "SELECT COUNT(*) FROM session_project"
        ).fetchone()[0]
        # Persist last_ts for next incremental run
        conn.execute(
            "INSERT OR REPLACE INTO backfill_meta (k, v) "
            "VALUES ('last_ts', ?)",
            (time.time(),),
        )
        conn.commit()
    finally:
        conn.close()

    print(f"session_project rows: {before} -> {after} "
          f"(+{after - before} added)")
    print()
    print("Phase 2c cross-session recall with project_only filter can")
    print("now find prior sessions back to the start of your history.")


if __name__ == "__main__":
    main()

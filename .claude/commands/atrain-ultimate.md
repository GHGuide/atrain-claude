---
description: ATrain ULTIMATE — max token savings. Arms base + full v8 stack + caveman ULTRA. Triggers /atrain-graphify if graphifyy is installed. Combined real measured ceiling ~80-85% saved on coding-heavy sessions with project history.
---

User invoked `/atrain-ultimate`.

**EXECUTE the bash block below NOW via the Bash tool. Do not reply "Noted".**

```bash
python3 - <<'EOF'
import json, os, pathlib, shutil, sqlite3, subprocess, time

# 1. Flip every savings flag in router-config
home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text()) if p.exists() else {}

# Base ATrain
cfg["mode"] = "balanced"
cfg["accuracy_target"] = 99.0
cfg["decompose_enabled"] = True
cfg["bash_pre_rewrite_enabled"] = True

# Caveman ULTRA (max output compression)
cfg["caveman_intensity"] = "ultra"

# v8 stack — all phases
cfg["progressive_read_enabled"] = True
cfg["output_index_enabled"] = True
cfg["cross_session_recall_enabled"] = True
cfg["cross_session_recall_project_only"] = True
cfg["memory_enabled"] = True

# Optional graphify routing if installed
graphify_installed = shutil.which("graphify") is not None
if graphify_installed:
    cfg["graph_aware"] = True
    cfg.setdefault("bash_rewrite_whitelist", [])
    if "graphify" not in cfg["bash_rewrite_whitelist"]:
        cfg["bash_rewrite_whitelist"].append("graphify")

# Reset session stats so dashboard reflects this run
empty_tier = {k: 0 for k in [
    "haiku_none","sonnet_low","sonnet_medium","sonnet_high","sonnet_max",
    "opus_low","opus_medium","opus_high","opus_xhigh","opus_max",
]}
cfg["session_stats"] = {
    "total_calls": 0,
    "calls_by_tier": dict(empty_tier),
    "tokens_by_tier": dict(empty_tier),
    "escalations_total": 0, "escalations_auth_secrets": 0,
    "escalations_multi_file": 0, "escalations_error_recovery": 0,
    "escalations_user_phrase": 0, "escalations_output_verify": 0,
    "estimated_cost_usd": 0.0, "baseline_opus_xhigh_cost_usd": 0.0,
    "estimated_savings_usd": 0.0,
    "task_dispatches": {}, "dispatch_blocks": 0, "dispatch_mismatches": 0,
    "advisory_calls": 0, "real_subagent_calls": 0,
    "real_savings_usd": 0.0, "advisory_savings_usd": 0.0,
}
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)

# 2. session->project backfill (idempotent)
db_path = pathlib.Path.home() / ".claude" / "router-cache.sqlite"
proj_root = pathlib.Path.home() / ".claude" / "projects"
backfilled = 0
prior_count = 0
mem_count = 0
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
        prior_count = conn.execute(
            "SELECT COUNT(*) FROM session_project "
            "WHERE project_dir = ?",
            (os.getcwd(),),
        ).fetchone()[0]
        try:
            mem_count = conn.execute(
                "SELECT COUNT(*) FROM memory_entries "
                "WHERE project_dir = ?",
                (os.getcwd(),),
            ).fetchone()[0]
        except sqlite3.Error:
            pass
    finally:
        conn.close()

print("+----------------------------------------------------------+")
print("|  ATrain ULTIMATE — MAX SAVINGS MODE ARMED                |")
print("+----------------------------------------------------------+")
print("|  Routing (per-call)             : ON                     |")
print("|  Decompose                      : ON                     |")
print("|  Bash pre-rewrite               : ON                     |")
print("|  Caveman intensity              : ULTRA                  |")
print("|  Progressive Read (Phase 1)     : ON                     |")
print("|  Within-session FTS5 (Phase 2)  : ON                     |")
print("|  Cross-session, same-project    : ON                     |")
print("|  Curated memory                 : ON                     |")
print("|  Graphify routing               : %-7s              |"
      % ("ON" if graphify_installed else "n/a (uninstalled)"))
print("+----------------------------------------------------------+")
print("|  session->project rows added    : %-4d                   |" % backfilled)
print("|  prior sessions this project    : %-4d                   |" % prior_count)
print("|  curated memories this project  : %-4d                   |" % mem_count)
print("+----------------------------------------------------------+")
print("|  Real measured stack (LELAU 913-prompt bench):           |")
print("|    Base ATrain        : 62.8%% saved                      |")
print("|    + v8.2c (cross)    : +33pp on recon (98%% hit rate)    |")
print("|    + caveman ULTRA    : +15-25pp output compression      |")
print("|    Combined ceiling   : ~80-85%% on coding-heavy sessions |")
print("+----------------------------------------------------------+")
print("|  Output reads like Tarzan. Switch to readable mode:      |")
print("|    /atrain-normal     # caveman OFF                      |")
print("|  Stop everything:                                        |")
print("|    /atrain-v8-stop && /atrain-kill                       |")
print("+----------------------------------------------------------+")
if not graphify_installed:
    print()
    print("To add the +8pp graphify boost (heavy install):")
    print("    pip install graphifyy  # or: uv tool install graphifyy")
    print("    /atrain-graphify       # builds graph + flips graph_aware")
EOF
```

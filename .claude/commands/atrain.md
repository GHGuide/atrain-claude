---
description: ATrain master command. /atrain ultimate (default, full v8 stack + caveman ULTRA for max savings) | /atrain regular (same v8 stack but caveman OFF for readable prose) | /atrain off (disarm).
argument-hint: [ultimate|regular|off]
---

User invoked `/atrain $ARGUMENTS`.

**EXECUTE the bash block below NOW via the Bash tool. Do not reply "Noted".**

```bash
python3 - <<'EOF'
import json, os, pathlib, sqlite3, sys, time

arg = """$ARGUMENTS""".strip().lower() or "ultimate"
home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text()) if p.exists() else {}

def save(c):
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(c, indent=2))
    os.replace(tmp, p)

if arg in ("off", "kill", "stop"):
    cfg["progressive_read_enabled"] = False
    cfg["output_index_enabled"] = False
    cfg["cross_session_recall_enabled"] = False
    cfg["advisory_pruning_enabled"] = False
    cfg["caveman_intensity"] = None
    cfg["decompose_enabled"] = False
    save(cfg)
    print("+------------------------------+")
    print("|  ATrain OFF                  |")
    print("|  All features disarmed.      |")
    print("|  Data retained in cache DB.  |")
    print("+------------------------------+")
    sys.exit(0)

# Base profile for both ultimate + regular
cfg["mode"] = "balanced"
cfg["accuracy_target"] = 99.0
cfg["decompose_enabled"] = True
cfg["bash_pre_rewrite_enabled"] = True
cfg["progressive_read_enabled"] = True
cfg["output_index_enabled"] = True
cfg["cross_session_recall_enabled"] = True
cfg["cross_session_recall_project_only"] = True
cfg["advisory_pruning_enabled"] = True
cfg["advisory_budget_chars"] = 1500

# Reset session_stats so the dashboard reflects this run
empty_tier = {k: 0 for k in [
    "haiku_none","sonnet_low","sonnet_medium","sonnet_high","sonnet_max",
    "opus_low","opus_medium","opus_high","opus_xhigh","opus_max",
]}
cfg.setdefault("session_stats", {
    "total_calls": 0, "calls_by_tier": dict(empty_tier),
    "tokens_by_tier": dict(empty_tier), "estimated_cost_usd": 0.0,
    "baseline_opus_xhigh_cost_usd": 0.0, "estimated_savings_usd": 0.0,
})

# Backfill session->project + count priors (for adaptive caveman)
db_path = pathlib.Path.home() / ".claude" / "router-cache.sqlite"
proj_root = pathlib.Path.home() / ".claude" / "projects"
prior_count = 0
if db_path.exists() and proj_root.exists():
    def _cwd(jp):
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
                    return c if isinstance(c, str) and c else str(jp.parent.resolve())
        except OSError:
            return str(jp.parent.resolve())
        return str(jp.parent.resolve())
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS session_project (session_id TEXT PRIMARY KEY, project_dir TEXT)")
        for jp in proj_root.rglob("*.jsonl"):
            conn.execute("INSERT OR REPLACE INTO session_project (session_id, project_dir) VALUES (?, ?)", (jp.stem, _cwd(jp)))
        conn.commit()
        prior_count = conn.execute("SELECT COUNT(*) FROM session_project WHERE project_dir = ?", (os.getcwd(),)).fetchone()[0]
    finally:
        conn.close()

# The only difference between ultimate and regular:
if arg in ("regular", "normal", "readable", "prose"):
    cfg["caveman_intensity"] = None
    label = "REGULAR"
    style_note = "Full prose. Readable Claude voice."
else:  # ultimate (default)
    cfg["caveman_intensity"] = "ultra" if prior_count >= 3 else "full"
    label = "ULTIMATE"
    style_note = f"Caveman {cfg['caveman_intensity'].upper()} — max compression."

save(cfg)

print("+----------------------------------------------------------+")
print(f"|  ATrain {label} — ARMED                              ".ljust(58) + "|")
print("+----------------------------------------------------------+")
print(f"|  Style: {style_note[:48]:<48s} |")
print("|  Routing per-call, decompose, bash-rewrite               |")
print("|  v8: progressive Read, FTS5 recall, same-project cross   |")
print("|       session, advisory pruning                          |")
print(f"|  Priors this project : {prior_count:<33d} |")
print("+----------------------------------------------------------+")
print("|  Switch readable: /atrain regular                        |")
print("|  Switch max save: /atrain ultimate                       |")
print("|  Stop everything: /atrain off                            |")
print("+----------------------------------------------------------+")
EOF
```

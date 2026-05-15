---
description: ATrain ULTIMATE — max savings. Caveman ULTRA output + full v8 stack. Switch to readable with /atrain-regular. Disarm with /atrain-kill.
---

User invoked `/atrain-ultimate`.

**EXECUTE the bash block below NOW via the Bash tool. Do not reply "Noted".**

```bash
python3 - <<'EOF'
import json, os, pathlib, sqlite3, sys

home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text()) if p.exists() else {}

# Base profile
cfg["mode"] = "balanced"
cfg["lean_mode"] = False
cfg["accuracy_target"] = 99.0
cfg["decompose_enabled"] = True
cfg["bash_pre_rewrite_enabled"] = True
cfg["progressive_read_enabled"] = True
cfg["output_index_enabled"] = True
cfg["cross_session_recall_enabled"] = True
cfg["cross_session_recall_project_only"] = True
cfg["advisory_pruning_enabled"] = True
cfg["advisory_budget_chars"] = 1500

# Reset session_stats
empty_tier = {k: 0 for k in [
    "haiku_none","sonnet_low","sonnet_medium","sonnet_high","sonnet_max",
    "opus_low","opus_medium","opus_high","opus_xhigh","opus_max",
]}
cfg.setdefault("session_stats", {
    "total_calls": 0, "calls_by_tier": dict(empty_tier),
    "tokens_by_tier": dict(empty_tier), "estimated_cost_usd": 0.0,
    "baseline_opus_xhigh_cost_usd": 0.0, "estimated_savings_usd": 0.0,
})

# Backfill session->project + count priors
db_path = pathlib.Path.home() / ".claude" / "router-cache.sqlite"
proj_root = pathlib.Path.home() / ".claude" / "projects"
prior_count = 0
if db_path.exists() and proj_root.exists():
    def _cwd(jp):
        try:
            with open(jp, "r", encoding="utf-8", errors="ignore") as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln: continue
                    try: obj = json.loads(ln)
                    except ValueError: return str(jp.parent.resolve())
                    c = obj.get("cwd")
                    return c if isinstance(c, str) and c else str(jp.parent.resolve())
        except OSError: return str(jp.parent.resolve())
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

# Caveman: adaptive — full (cold) / ultra (warm)
cfg["caveman_intensity"] = "ultra" if prior_count >= 3 else "full"

tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)

# Also mirror to project config for repo-local dev testing.
proj_cfg = pathlib.Path(".claude/router-config.json")
if proj_cfg.exists() and proj_cfg.resolve() != p.resolve():
    try:
        pcfg = json.loads(proj_cfg.read_text())
        for k, v in cfg.items():
            pcfg[k] = v
        tmp2 = proj_cfg.with_suffix(".json.tmp")
        tmp2.write_text(json.dumps(pcfg, indent=2))
        os.replace(tmp2, proj_cfg)
    except (OSError, ValueError):
        pass

print("+----------------------------------------------------------+")
print("|  ATrain ULTIMATE — ARMED                                 |")
print("+----------------------------------------------------------+")
print(f"|  Caveman: {cfg['caveman_intensity'].upper():<6s} (max compression)                    |")
print("|  Routing per-call, decompose, bash-rewrite               |")
print("|  v8: progressive Read, FTS5 recall, same-project cross   |")
print("|       session, advisory pruning                          |")
print(f"|  Priors this project : {prior_count:<33d} |")
print("+----------------------------------------------------------+")
print("|  Readable: /atrain-regular                               |")
print("|  Stop    : /atrain-kill                                  |")
print("+----------------------------------------------------------+")
EOF
```

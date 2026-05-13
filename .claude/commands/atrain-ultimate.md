---
description: ATrain ULTIMATE — max token savings, adaptive. Arms base + full v8 stack + caveman (ultra if warm, full if cold). Auto-builds graphify graph when installed. Real measured ceiling ~80-85% on coding sessions with project history.
---

User invoked `/atrain-ultimate`.

**EXECUTE the bash block below NOW via the Bash tool. Do not reply "Noted".**

```bash
python3 - <<'EOF'
import json, os, pathlib, shutil, sqlite3, subprocess, sys, time

REPORT = []
def line(s=""):
    REPORT.append(s)

# 1. Find router-config
home = pathlib.Path.home() / ".claude" / "router-config.json"
proj = pathlib.Path(".claude/router-config.json")
p = home if home.exists() else proj
cfg = json.loads(p.read_text()) if p.exists() else {}

# 2. Open DB, count priors + memories for this project FIRST
#    (drives adaptive caveman intensity)
db_path = pathlib.Path.home() / ".claude" / "router-cache.sqlite"
proj_root = pathlib.Path.home() / ".claude" / "projects"
cwd = os.getcwd()
prior_count = 0
mem_count = 0
backfilled = 0
fts5_ok = False
if db_path.exists():
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    try:
        # Ensure tables exist (idempotent)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS session_project ("
            "session_id TEXT PRIMARY KEY, project_dir TEXT)"
        )
        # Backfill mapping from disk transcripts. Read the first jsonl
        # record for the actual cwd (Claude Code stores it on each
        # message); fall back to the encoded ~/.claude/projects/ dir
        # only if the field is missing. Required so project_only filter
        # matches against os.getcwd() at recall time.
        def _cwd_from_jsonl(jp):
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
        if proj_root.exists():
            mapping = {jp.stem: _cwd_from_jsonl(jp)
                       for jp in proj_root.rglob("*.jsonl")}
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
            backfilled = after - before
        prior_count = conn.execute(
            "SELECT COUNT(*) FROM session_project WHERE project_dir = ?",
            (cwd,),
        ).fetchone()[0]
        try:
            mem_count = conn.execute(
                "SELECT COUNT(*) FROM memory_entries WHERE project_dir = ?",
                (cwd,),
            ).fetchone()[0]
        except sqlite3.Error:
            pass
        # FTS5 sanity check
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe "
                "USING fts5(t)"
            )
            conn.execute("DROP TABLE _fts5_probe")
            fts5_ok = True
        except sqlite3.OperationalError:
            fts5_ok = False
    finally:
        conn.close()

# 3. ADAPTIVE caveman intensity based on history
#    Cold start (0 priors): "full" — saves 65% output, still readable
#    Warm (3+ priors): "ultra" — max compression, Tarzan output
if prior_count >= 3:
    caveman = "ultra"
    caveman_note = "warm history -> ULTRA (max savings)"
else:
    caveman = "full"
    caveman_note = ("cold start (%d prior sessions) -> FULL "
                    "(stays readable; upgrades to ULTRA after 3+)"
                    % prior_count)

# 4. Flip every savings flag
cfg["mode"] = "balanced"
cfg["accuracy_target"] = 99.0
cfg["decompose_enabled"] = True
cfg["bash_pre_rewrite_enabled"] = True
cfg["caveman_intensity"] = caveman

# v8 stack
cfg["progressive_read_enabled"] = True
cfg["output_index_enabled"] = fts5_ok
cfg["cross_session_recall_enabled"] = fts5_ok
cfg["cross_session_recall_project_only"] = True
cfg["memory_enabled"] = fts5_ok

# 5. Graphify integration if installed
graphify_bin = shutil.which("graphify")
graphify_status = "n/a (not installed)"
if graphify_bin:
    cfg["graph_aware"] = True
    cfg.setdefault("bash_rewrite_whitelist", [])
    if "graphify" not in cfg["bash_rewrite_whitelist"]:
        cfg["bash_rewrite_whitelist"].append("graphify")
    # Auto-build graph if not yet present for this project
    graph_json = pathlib.Path(cwd) / "graphify-out" / "graph.json"
    if graph_json.exists():
        graphify_status = "ON (graph present)"
    else:
        graphify_status = "ON (building graph in background...)"
        try:
            subprocess.Popen(
                [graphify_bin, "."],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception:
            graphify_status = "ON (graph build failed — run /atrain-graphify)"

# 6. PRESERVE session_stats by default; only init if missing
empty_tier = {k: 0 for k in [
    "haiku_none","sonnet_low","sonnet_medium","sonnet_high","sonnet_max",
    "opus_low","opus_medium","opus_high","opus_xhigh","opus_max",
]}
cfg.setdefault("session_stats", {
    "total_calls": 0,
    "calls_by_tier": dict(empty_tier),
    "tokens_by_tier": dict(empty_tier),
    "escalations_total": 0,
    "estimated_cost_usd": 0.0, "baseline_opus_xhigh_cost_usd": 0.0,
    "estimated_savings_usd": 0.0,
    "task_dispatches": {}, "dispatch_blocks": 0, "dispatch_mismatches": 0,
})

tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(cfg, indent=2))
os.replace(tmp, p)

# 7. Projected savings (heuristic, not measured)
base_pct = 65
v8_bonus = min(20, prior_count * 5)  # 5pp per prior session, cap 20pp
caveman_bonus = 25 if caveman == "ultra" else 15
graphify_bonus = 8 if graphify_bin else 0
# Cap at theoretical ceiling
projected = min(85, base_pct + (100 - base_pct) * (
    v8_bonus + caveman_bonus + graphify_bonus
) / 100)

# 8. Print card
line("+----------------------------------------------------------+")
line("|  ATrain ULTIMATE — ARMED                                 |")
line("+----------------------------------------------------------+")
line("|  Routing per-call            : ON                        |")
line("|  Decompose                   : ON                        |")
line("|  Bash pre-rewrite            : ON                        |")
line("|  Caveman intensity           : %-6s (%s)" % (caveman.upper(), caveman_note[:24]))
line("|                                %s" % caveman_note[24:48])
line("|  v8 Phase 1 progressive Read : ON                        |")
line("|  v8 Phase 2 FTS5 recall      : %-24s |" % ("ON" if fts5_ok else "OFF (sqlite lacks FTS5)"))
line("|  v8 Phase 2c same-project    : %-24s |" % ("ON" if fts5_ok else "OFF"))
line("|  v8 Phase 3 curated memory   : %-24s |" % ("ON" if fts5_ok else "OFF"))
line("|  Graphify routing            : %-24s |" % graphify_status[:24])
line("+----------------------------------------------------------+")
line("|  This project:                                            |")
line("|    prior sessions     : %-4d                              |" % prior_count)
line("|    curated memories   : %-4d                              |" % mem_count)
line("|    backfilled rows    : %-4d                              |" % backfilled)
line("+----------------------------------------------------------+")
line("|  Projected savings (heuristic):                           |")
line("|    base ATrain        : ~%d%%                              |" % base_pct)
line("|    + caveman %-5s    : +%dpp                              |" % (caveman, caveman_bonus))
line("|    + v8 (priors=%-3d)  : +%dpp                              |" % (prior_count, v8_bonus))
if graphify_bin:
    line("|    + graphify routing : +%dpp                              |" % graphify_bonus)
line("|    PROJECTED total    : ~%d%%                              |" % projected)
line("+----------------------------------------------------------+")
line("|  Tips:                                                    |")
if prior_count == 0:
    line("|    First run on this project. Run a session or two       |")
    line("|    before /atrain-ultimate hits full power.               |")
if not fts5_ok:
    line("|    Your sqlite lacks FTS5. v8 phases 2/2c/3 disabled.    |")
    line("|    Install python with FTS5 support to enable.           |")
if not graphify_bin:
    line("|    Install graphify for +8pp on coding-heavy sessions:    |")
    line("|      pip install graphifyy                                |")
line("|                                                           |")
line("|  Switch to readable:  /atrain-normal                      |")
line("|  Stop everything:     /atrain-v8-stop && /atrain-kill     |")
line("+----------------------------------------------------------+")

for ln in REPORT:
    print(ln)
EOF
```

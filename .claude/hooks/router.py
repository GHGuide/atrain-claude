#!/usr/bin/env python3
"""smart-router: dynamic model + effort selector for Claude Code.

Stdlib only. Never crashes — wraps everything and returns {} on error.
Atomic file writes via .tmp + os.replace. Hook latency target <50ms.
"""
import ast
import contextlib
import fcntl
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "router-config.json"
TMP_DIR = Path(tempfile.gettempdir())

ERROR_SIGNATURES = (
    "Traceback", "Error:", "SyntaxError", "TypeError", "NameError",
    "undefined is not", "cannot read properties", "ENOENT",
    "ModuleNotFoundError", "ImportError",
)
TIER_KEYS = (
    "haiku_none",
    "sonnet_low", "sonnet_medium", "sonnet_high", "sonnet_max",
    "opus_low", "opus_medium", "opus_high", "opus_xhigh", "opus_max",
)
AGENT_REGISTRY = {
    "recon-haiku":    {"model": "haiku",  "tier": "recon",         "effort": "none"},
    "impl-sonnet":    {"model": "sonnet", "tier": "impl",          "effort": "medium"},
    "api-sonnet":     {"model": "sonnet", "tier": "api",           "effort": "high"},
    "architect-opus": {"model": "opus",   "tier": "architecture",  "effort": "xhigh"},
    "secure-opus":    {"model": "opus",   "tier": "sensitive",     "effort": "xhigh"},
}
OPUS_AGENTS = {"architect-opus", "secure-opus"}
ROUTER_AGENTS = set(AGENT_REGISTRY.keys())
MODELS_API_URL = "https://api.anthropic.com/v1/models"
HAIKU_BASH_RE = re.compile(
    r"^\s*(grep|ls|find|cat|echo|pwd|wc|head|tail|diff|stat|file)\b"
)
TEST_RUNNER_RE = re.compile(r"pytest|jest|vitest|npm test|cargo test|go test")
PATH_RE = re.compile(r'"path"\s*:')
EFFORT_PRIORITY = ("max", "xhigh", "high", "medium", "low")

# ─── Classification rule constants (introspectable) ─────────────────
# Lifting these from classify_task locals to module scope makes them
# discoverable via --print-rules and lintable against SKILL.md.
OPUS_KEYWORDS = (
    "refactor entire", "redesign", "optimize", "bottleneck",
    "architecture", "design pattern", "review all", "performance",
)
API_KEYWORDS = (
    "endpoint", "endpoints", "route", "routes",
    "api integration", "third-party", "graphql",
    "rest api", "http handler",
)
BOILERPLATE_STRONG = (
    "scaffold", "create a basic", "stub out", "add a simple",
)
BOILERPLATE_WEAK = ("generate", "template")
BOILERPLATE_ANCHORS = (
    "boilerplate", "scaffold", "template", "starter", "skeleton",
)
USER_PHRASES = (
    "think carefully", "be precise", "dont mess", "don't mess",
    "critical", "production", "use max effort", "spare no tokens",
)
MANIFEST_FILES = (
    "package.json", "pyproject.toml", "cargo.toml",
    "go.mod", "requirements.txt",
)


def _empty_stats() -> dict:
    return {
        "total_calls": 0,
        "calls_by_tier": {k: 0 for k in TIER_KEYS},
        "tokens_by_tier": {k: 0 for k in TIER_KEYS},
        "escalations_total": 0,
        "escalations_auth_secrets": 0,
        "escalations_multi_file": 0,
        "escalations_error_recovery": 0,
        "escalations_user_phrase": 0,
        "escalations_output_verify": 0,
        "estimated_cost_usd": 0.0,
        "baseline_opus_xhigh_cost_usd": 0.0,
        "estimated_savings_usd": 0.0,
        "task_dispatches": {},
        "dispatch_blocks": 0,
        "dispatch_mismatches": 0,
        # v4.0 honest accounting
        "advisory_calls": 0,           # main-session calls where hook ADVISED but couldn't enforce
        "real_subagent_calls": 0,      # actual Task dispatches that swapped models
        "real_savings_usd": 0.0,       # only credited for real_subagent_calls
        "advisory_savings_usd": 0.0,   # what we WOULD have saved if advisory was honored
    }


def _default_config() -> dict:
    return {
        "version": "2.0.0",
        "mode": "balanced",
        "accuracy_target": 99.0,
        "last_model_check": "2026-05-07T00:00:00",
        "model_registry": {
            "opus": {
                "id": "claude-opus-4-7",
                "alias": "claude-opus-4-7",
                "effort_support": ["low", "medium", "high", "xhigh", "max"],
                "input_price_per_1m": 5.00,
                "output_price_per_1m": 25.00,
            },
            "sonnet": {
                "id": "claude-sonnet-4-6",
                "alias": "claude-sonnet-4-6",
                "effort_support": ["low", "medium", "high", "max"],
                "input_price_per_1m": 3.00,
                "output_price_per_1m": 15.00,
            },
            "haiku": {
                "id": "claude-haiku-4-5-20251001",
                "alias": "claude-haiku-4-5",
                "effort_support": [],
                "input_price_per_1m": 0.80,
                "output_price_per_1m": 4.00,
            },
        },
        "thresholds": {
            "haiku_confidence_min": 0.88,
            "sonnet_confidence_min": 0.82,
            "haiku_pct_target": 35,
            "opus_effort": "high",
            "sonnet_effort": "high",
            "consistency_runs": 1,
        },
        "hard_escalation_keywords": [
            "auth", "authentication", "authorize", "rbac",
            "password", "secret", "api_key", "private_key",
            "access_token", "refresh_token", "bearer", "jwt",
            "encrypt", "decrypt", "aes", "rsa", "ecdsa",
            "cipher", "signing key",
            "password hash", "bcrypt", "argon2", "scrypt", "pbkdf2",
            "db migration", "schema migration", "alter table",
            "drop column", "drop table",
            ".env", "dotenv",
            "certificate", "ssl", "tls", "cors", "csrf", "samesite",
            "sanitize", "xss", "sql injection",
            "webhook signature", "hmac",
            "to production", "in production", "prod database",
            "deploy to", "main branch", "master branch",
            "oauth",
        ],
        "agent_registry": dict(AGENT_REGISTRY),
        "decompose_enabled": False,
        "force_subagent_recon": False,
        "bash_pre_rewrite_enabled": True,
        "caveman_intensity": None,  # null/lite/full/ultra; eco auto-fires "full"
        "routing_tables": {
            "eco": {
                "recon": "recon-haiku",
                "impl": "impl-sonnet",
                "api": "impl-sonnet",
                "architecture": "architect-opus",
                "sensitive": "secure-opus",
            },
            "balanced": {
                "recon": "recon-haiku",
                "impl": "impl-sonnet",
                "api": "api-sonnet",
                "architecture": "architect-opus",
                "sensitive": "secure-opus",
            },
            "quality": {
                "recon": "impl-sonnet",
                "impl": "impl-sonnet",
                "api": "architect-opus",
                "architecture": "architect-opus",
                "sensitive": "secure-opus",
            },
        },
        "session_stats": _empty_stats(),
        "calibration_history": [],
    }


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


@contextlib.contextmanager
def config_lock():
    """Cross-process lock for read-modify-write on router-config.json.
    Prevents concurrent hook invocations from losing stat increments.

    Acquisition runs in its own try-block; the yield is outside it so
    a caller's OSError (e.g. a transient FS error during atomic_write_json)
    cannot be swallowed by the acquisition's except and re-yielded —
    that would violate the contextmanager contract (generator must
    yield exactly once)."""
    lock_path = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".lock")
    fd = None
    locked = False
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = open(lock_path, "w")
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX)
            locked = True
        except (OSError, ValueError):
            locked = False
    except (OSError, ValueError):
        fd = None
        locked = False
    try:
        yield
    finally:
        if fd is not None:
            if locked:
                try:
                    fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
                except (OSError, ValueError):
                    pass
            try:
                fd.close()
            except OSError:
                pass


def rewrite_bash_command(cmd: str) -> tuple:
    """v6.4 — rtk-pattern command pre-rewriter. Operates at the shell
    level BEFORE execution, transforming bloated commands into compact
    equivalents. Returns (rewritten_cmd, was_rewritten_bool).

    Real benchmarks from rtk-ai/rtk on a 30-min Claude Code session:
      ls/tree:       -80%  (2,000 → 400 tokens)
      cat/read:      -70%  (40,000 → 12,000 tokens)
      git status:    -80%  (3,000 → 600 tokens)
      cargo test:    -90%  (25,000 → 2,500 tokens)
      pytest:        -90%  (8,000 → 800 tokens)
      Total session: -80%  (118k → 24k tokens)
    """
    if not cmd or not isinstance(cmd, str):
        return cmd, False
    stripped = cmd.strip()
    if not stripped:
        return cmd, False

    # Conservative — only rewrite when we're certain the output gets
    # compressed without information loss. Caller can opt out via
    # config.bash_pre_rewrite_enabled = false.
    rewrites = [
        # ls — quieter forms unless user passed -l/-a flags themselves
        (r"^ls\s*$", "ls -1 --color=never"),
        (r"^ls\s+([^|<>;&]*)$", lambda m:
         f"ls {m.group(1)} | head -100" if "|" not in m.group(1)
         and "head" not in m.group(1) else cmd),

        # git status — short form, untracked summary only
        (r"^git\s+status\s*$", "git status --short --untracked-files=no"),
        (r"^git\s+status\s+--short\s*$", "git status --short --untracked-files=no"),

        # git log — limit + oneline
        (r"^git\s+log\s*$", "git log --oneline -n 20"),
        (r"^git\s+log\s+(-?\d*)\s*$", lambda m:
         f"git log --oneline {m.group(1) or '-n 20'}"),

        # tree — depth limit + no summary
        (r"^tree\s*$", "tree -L 3 --noreport -I 'node_modules|.git|venv|__pycache__|dist|build'"),
        (r"^tree\s+(\S+)\s*$", lambda m:
         f"tree {m.group(1)} -L 3 --noreport "
         f"-I 'node_modules|.git|venv|__pycache__|dist|build'"),

        # find — top results only
        (r"^find\s+(.+)\s+-name\s+(\S+)\s*$", lambda m:
         f"find {m.group(1)} -name {m.group(2)} | head -50"),

        # pytest — quiet mode unless -v already specified
        (r"^pytest\s*$", "pytest -q --no-header"),
        (r"^pytest\s+([^|<>;&]*?)$", lambda m:
         f"pytest -q --no-header {m.group(1)}"
         if "-v" not in m.group(1) and "-q" not in m.group(1)
         else cmd),

        # cargo test — quiet
        (r"^cargo\s+test\s*$", "cargo test --quiet 2>&1 | tail -50"),

        # npm test — silent
        (r"^npm\s+test\s*$", "npm test --silent 2>&1 | tail -100"),
        (r"^npm\s+run\s+test\s*$", "npm run test --silent 2>&1 | tail -100"),

        # docker ps — quieter table form
        (r"^docker\s+ps\s*$", "docker ps --format 'table {{.Names}}\\t{{.Status}}\\t{{.Image}}'"),

        # npm install — silent unless --verbose
        (r"^npm\s+install\s*$", "npm install --silent 2>&1 | tail -20"),
    ]

    for pattern, replacement in rewrites:
        m = re.match(pattern, stripped)
        if m:
            new = replacement(m) if callable(replacement) else replacement
            if new != stripped and new != cmd:
                return new, True
    return cmd, False


def compact_bash_output(out: str, max_chars: int = 4000) -> str:
    """v6.0 — rtk-pattern Bash output compactor. Regex-based, stdlib only.
    Removes common noise (ANSI codes, timestamps, blank lines, dedup),
    truncates to max_chars. Reports 60-90% reduction on common dev cmds.
    """
    if not out or len(out) < 200:
        return out
    s = out
    # strip ANSI escape sequences (color codes)
    s = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", s)
    # strip carriage-return progress bars
    s = re.sub(r".*\r(?=.)", "", s)
    # strip ISO timestamps + bracketed log timestamps
    s = re.sub(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[\.\d]*Z?\s*",
               "", s, flags=re.MULTILINE)
    s = re.sub(r"^\[\d{4}-\d{2}-\d{2}[T ][^\]]+\]\s*",
               "", s, flags=re.MULTILINE)
    # collapse 3+ blank lines to 1
    s = re.sub(r"\n{3,}", "\n\n", s)
    # dedup adjacent identical lines (e.g. repeated log spam)
    lines = s.splitlines()
    deduped = []
    last = None
    skipped = 0
    for line in lines:
        if line == last:
            skipped += 1
        else:
            if skipped:
                deduped.append(f"... ({skipped} duplicate lines collapsed)")
                skipped = 0
            deduped.append(line)
            last = line
    if skipped:
        deduped.append(f"... ({skipped} duplicate lines collapsed)")
    s = "\n".join(deduped)
    # truncate with marker
    if len(s) > max_chars:
        head = s[: max_chars // 2]
        tail = s[-(max_chars // 2):]
        s = (head + f"\n\n... [truncated {len(s) - max_chars} chars] ...\n\n"
             + tail)
    return s


def compact_tool_input(tool_input, max_field_chars: int = 8000):
    """v6.0 — claw-compactor inspired tool-input compaction. Truncates
    overly long content/old_string/new_string fields with markers.
    Returns (compacted_dict, was_compacted_bool)."""
    if not isinstance(tool_input, dict):
        return tool_input, False
    out = dict(tool_input)
    compacted = False
    for k in ("content", "old_string", "new_string"):
        v = out.get(k)
        if isinstance(v, str) and len(v) > max_field_chars:
            head = v[: max_field_chars // 2]
            tail = v[-(max_field_chars // 2):]
            out[k] = (
                head
                + f"\n\n... [{k} truncated, {len(v) - max_field_chars} "
                f"chars omitted] ...\n\n"
                + tail
            )
            compacted = True
    return out, compacted


def detect_multi_faceted(prompt: str) -> tuple:
    """Heuristic — does the prompt look like it would benefit from
    decomposition? Returns (is_multi, signals_list).

    Signals (need 2+ to fire):
    - length > 200 chars
    - 2+ conjunctions ("and", "also", "plus", "then", ";")
    - 3+ list items (markdown bullets or numbered)
    - 3+ distinct action verbs
    - 2+ file/path references
    """
    if not prompt or not isinstance(prompt, str):
        return (False, [])
    p = prompt.lower()
    signals = []
    if len(prompt) > 200:
        signals.append(f"len={len(prompt)}")
    conjunctions = (" and ", " also ", " plus ", " then ", "; ", ", and ")
    n_conj = sum(p.count(c) for c in conjunctions)
    if n_conj >= 2:
        signals.append(f"conjunctions={n_conj}")
    list_items = re.findall(r"(?m)^\s*(?:[-*]\s|\d+[.)]\s)", prompt)
    if len(list_items) >= 3:
        signals.append(f"list-items={len(list_items)}")
    action_verbs = (
        "add", "write", "create", "build", "fix", "refactor",
        "implement", "design", "test", "review", "find", "update",
        "remove", "delete", "rename", "wire", "extract", "validate",
        "check", "audit", "optimize", "rewrite",
    )
    verbs_found = set()
    for v in action_verbs:
        if re.search(rf"(?<!\w){v}(?!\w)", p):
            verbs_found.add(v)
    if len(verbs_found) >= 3:
        signals.append(f"verbs={len(verbs_found)}")
    paths = re.findall(r"[\w./-]+\.(?:py|ts|tsx|js|jsx|md|json|yml|yaml|sql|go|rs|java|kt|swift|rb|php|cs|cpp|c|h|hpp)\b", prompt)
    if len(paths) >= 2:
        signals.append(f"paths={len(paths)}")
    return (len(signals) >= 2, signals)


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        cfg = _default_config()
        try:
            atomic_write_json(CONFIG_PATH, cfg)
        except Exception:
            pass
        return cfg
    cfg.setdefault("session_stats", _empty_stats())
    cfg["session_stats"].setdefault("calls_by_tier", {})
    cfg["session_stats"].setdefault("tokens_by_tier", {})
    for k in TIER_KEYS:
        cfg["session_stats"]["calls_by_tier"].setdefault(k, 0)
        cfg["session_stats"]["tokens_by_tier"].setdefault(k, 0)
    cfg.setdefault("calibration_history", [])
    cfg.setdefault("hard_escalation_keywords", _default_config()["hard_escalation_keywords"])
    return cfg


def save_config(config: dict) -> None:
    atomic_write_json(CONFIG_PATH, config)


# ─── Cross-session memory (v6.1 native, claude-mem pattern) ─────────
# Stores per-project digests of recent tool calls so SessionStart can
# inject relevant prior context. Stdlib only — no Haiku call needed;
# digest = top-N highest-signal entries from session_log compressed via
# string templating. Realistic 80-92% reduction on session continuity.
SESSION_MEMORY_DIR_NAME = "atrain-memory"
SESSION_MEMORY_MAX_DIGESTS = 5      # most recent 5 sessions per project
SESSION_MEMORY_MAX_ENTRIES = 40     # most recent 40 calls per session
SESSION_MEMORY_INJECT_CHARS = 2400  # cap injected context to ~600 tokens


def _project_hash(cwd: str = None) -> str:
    """Stable 8-byte fingerprint of the project working directory."""
    cwd = cwd or os.getcwd()
    try:
        cwd = str(Path(cwd).resolve())
    except (OSError, RuntimeError):
        pass
    if not cwd:
        cwd = "default"
    return hashlib.blake2b(cwd.encode("utf-8"), digest_size=8).hexdigest()


def _memory_dir() -> Path:
    return CONFIG_PATH.parent / SESSION_MEMORY_DIR_NAME


def _memory_file(project_hash: str) -> Path:
    return _memory_dir() / f"{project_hash}.json"


def save_session_memory(session_id: str) -> None:
    """SessionEnd hook: distill session log into a project-scoped digest.
    Stdlib-only — no Haiku call; just structural compression."""
    log = load_session_log(session_id)
    if not log:
        return
    posts = [e for e in log if e.get("phase") == "post"]
    pre_entries = [e for e in log if e.get("phase") == "pre"]
    if not posts:
        return
    # Highest-signal entries: ones that escalated, errored, or were the
    # most recent. Cap to SESSION_MEMORY_MAX_ENTRIES.
    keep = []
    for e in pre_entries[-SESSION_MEMORY_MAX_ENTRIES:]:
        keep.append({
            "tool": e.get("tool", ""),
            "tier": e.get("tier", ""),
            "reason": e.get("escalation_reason") or "",
        })
    digest = {
        "session_id": session_id,
        "ended_at": datetime.now().isoformat(),
        "n_calls": len(posts),
        "tier_breakdown": _summarize_tiers(posts),
        "notable": _extract_notable(pre_entries, posts),
        "recent": keep[-15:],
    }
    try:
        ph = _project_hash()
        mem_file = _memory_file(ph)
        mem_file.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if mem_file.exists():
            try:
                existing = json.loads(mem_file.read_text())
            except (ValueError, OSError):
                existing = []
        existing.append(digest)
        existing = existing[-SESSION_MEMORY_MAX_DIGESTS:]
        tmp = mem_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(existing, indent=1))
        os.replace(tmp, mem_file)
    except (OSError, ValueError):
        pass


def _summarize_tiers(posts: list) -> dict:
    counts = {}
    for e in posts:
        tier = e.get("tier", "unknown")
        counts[tier] = counts.get(tier, 0) + 1
    return counts


def _extract_notable(pre_entries: list, posts: list) -> list:
    """Pick high-signal moments to remember. Errors, escalations,
    sensitive routes, and the last few tool calls. Cap for digest size."""
    notable = []
    for e in pre_entries:
        if e.get("escalated"):
            notable.append(
                f"escalated [{e.get('tier','?')}]: "
                f"{(e.get('escalation_reason') or '')[:80]}"
            )
    for e in posts:
        if e.get("had_error"):
            notable.append(
                f"error in {e.get('tool','?')} on {e.get('tier','?')} tier"
            )
    return notable[-12:]


def load_session_memory_for_inject() -> str:
    """SessionStart hook: read recent project memory, format into a
    short additionalContext string for injection. Returns empty string
    when no memory exists or reads fail."""
    try:
        ph = _project_hash()
        mem_file = _memory_file(ph)
        if not mem_file.exists():
            return ""
        digests = json.loads(mem_file.read_text())
        if not digests:
            return ""
        lines = ["ATrain session memory — recent activity on this project:"]
        for d in digests[-3:]:
            ended = d.get("ended_at", "?")[:16].replace("T", " ")
            n = d.get("n_calls", 0)
            tiers = d.get("tier_breakdown", {})
            top = ", ".join(f"{k}:{v}" for k, v in
                            sorted(tiers.items(), key=lambda x: -x[1])[:3])
            lines.append(f"  • {ended} — {n} calls ({top})")
            for note in d.get("notable", [])[:3]:
                lines.append(f"      - {note}")
        text = "\n".join(lines)
        if len(text) > SESSION_MEMORY_INJECT_CHARS:
            text = text[:SESSION_MEMORY_INJECT_CHARS] + "\n  …"
        return text
    except (OSError, ValueError):
        return ""


# ─── Codebase indexer (v6.2 native, graphify pattern, stdlib-only) ──
# Walks a project, extracts symbol locations (functions, classes,
# exports), stores in per-project sqlite. PreToolUse hook on
# Read/Grep can answer "where is X defined" in <10ms instead of
# many file reads. Supports Python via ast, JS/TS/Go via regex.
INDEX_DIR_NAME = "atrain-index"
INDEX_MAX_FILE_BYTES = 200_000   # skip huge files
INDEX_MAX_FILES = 5_000
INDEX_SUPPORTED_EXTS = (".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs")

# Skip patterns for typical irrelevant directories
INDEX_SKIP_DIR_NAMES = {
    "node_modules", ".git", ".venv", "venv", "__pycache__",
    ".pytest_cache", ".mypy_cache", "dist", "build", ".next",
    "target", ".cache", "vendor", "coverage", ".idea", ".vscode",
}


def _index_db_path() -> Path:
    return CONFIG_PATH.parent / INDEX_DIR_NAME / f"{_project_hash()}.sqlite"


def _index_conn():
    p = _index_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=2.0, isolation_level=None)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS symbols ("
        "path TEXT, name TEXT, kind TEXT, signature TEXT, "
        "line INTEGER, indexed_at REAL)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_symbols_path ON symbols(path)")
    return conn


def _index_python_file(path: Path) -> list:
    """Extract symbols from a Python file via stdlib ast."""
    try:
        src = path.read_text(encoding="utf-8", errors="ignore")
        if len(src) > INDEX_MAX_FILE_BYTES:
            return []
        tree = ast.parse(src, filename=str(path))
    except (OSError, SyntaxError, ValueError):
        return []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            sig = f"def {node.name}({', '.join(args)})"
            out.append(("function", node.name, sig, node.lineno))
        elif isinstance(node, ast.ClassDef):
            out.append(("class", node.name, f"class {node.name}",
                        node.lineno))
    return out


# Regex for JS/TS function and class symbol extraction
_JS_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?"
    r"(?:function\s+(\w+)|"
    r"class\s+(\w+)|"
    r"const\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[\w]+)\s*=>)",
    re.MULTILINE,
)

_GO_RE = re.compile(
    r"^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(",
    re.MULTILINE,
)

_RS_RE = re.compile(
    r"^(?:pub\s+)?fn\s+(\w+)",
    re.MULTILINE,
)


def _index_regex_file(path: Path, ext: str) -> list:
    """Extract symbols from JS/TS/Go/Rust via regex (stdlib re)."""
    try:
        src = path.read_text(encoding="utf-8", errors="ignore")
        if len(src) > INDEX_MAX_FILE_BYTES:
            return []
    except OSError:
        return []
    out = []
    if ext in (".js", ".jsx", ".ts", ".tsx"):
        for m in _JS_RE.finditer(src):
            name = m.group(1) or m.group(2) or m.group(3)
            if not name:
                continue
            kind = ("class" if m.group(2)
                    else ("function" if m.group(1) else "arrow"))
            line = src[:m.start()].count("\n") + 1
            sig = m.group(0).strip()[:120]
            out.append((kind, name, sig, line))
    elif ext == ".go":
        for m in _GO_RE.finditer(src):
            line = src[:m.start()].count("\n") + 1
            sig = m.group(0).strip()[:120]
            out.append(("function", m.group(1), sig, line))
    elif ext == ".rs":
        for m in _RS_RE.finditer(src):
            line = src[:m.start()].count("\n") + 1
            sig = m.group(0).strip()[:120]
            out.append(("function", m.group(1), sig, line))
    return out


def index_project(root: str = None) -> dict:
    """Walk project, index all supported files. Returns summary dict."""
    root_path = Path(root or os.getcwd()).resolve()
    if not root_path.is_dir():
        return {"error": f"not a directory: {root_path}"}
    n_files = 0
    n_symbols = 0
    skipped = 0
    try:
        conn = _index_conn()
        try:
            conn.execute("DELETE FROM symbols")
            now = time.time()
            for p in root_path.rglob("*"):
                if n_files >= INDEX_MAX_FILES:
                    break
                if any(part in INDEX_SKIP_DIR_NAMES for part in p.parts):
                    continue
                if not p.is_file():
                    continue
                ext = p.suffix.lower()
                if ext not in INDEX_SUPPORTED_EXTS:
                    continue
                try:
                    if p.stat().st_size > INDEX_MAX_FILE_BYTES:
                        skipped += 1
                        continue
                except OSError:
                    skipped += 1
                    continue
                rel = str(p.relative_to(root_path))
                if ext == ".py":
                    syms = _index_python_file(p)
                else:
                    syms = _index_regex_file(p, ext)
                if not syms:
                    continue
                n_files += 1
                for kind, name, sig, line in syms:
                    conn.execute(
                        "INSERT INTO symbols "
                        "(path, name, kind, signature, line, indexed_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (rel, name, kind, sig, line, now),
                    )
                    n_symbols += 1
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as e:
        return {"error": str(e)}
    return {
        "project": str(root_path),
        "n_files_indexed": n_files,
        "n_symbols": n_symbols,
        "skipped_oversize": skipped,
    }


def lookup_symbol(name: str, limit: int = 5) -> list:
    """Query the index for a symbol name. Returns list of dicts."""
    if not name or len(name) < 2:
        return []
    try:
        conn = _index_conn()
        try:
            rows = conn.execute(
                "SELECT path, name, kind, signature, line FROM symbols "
                "WHERE name = ? OR name LIKE ? LIMIT ?",
                (name, f"%{name}%", limit),
            ).fetchall()
            return [
                {"path": r[0], "name": r[1], "kind": r[2],
                 "signature": r[3], "line": r[4]}
                for r in rows
            ]
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return []


def index_status() -> dict:
    """Quick stats on the project's index."""
    try:
        conn = _index_conn()
        try:
            total = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
            by_kind = dict(conn.execute(
                "SELECT kind, COUNT(*) FROM symbols GROUP BY kind"
            ).fetchall())
            files = conn.execute(
                "SELECT COUNT(DISTINCT path) FROM symbols"
            ).fetchone()[0]
            return {
                "indexed_symbols": total,
                "indexed_files": files,
                "by_kind": by_kind,
            }
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return {"error": "index not built"}


# ─── Tool-result cache (Pattern 4 lite) ─────────────────────────────
# stdlib-only sqlite3 cache. Detects duplicate Read/LS/Glob/Grep
# within a short window and surfaces the previous result as an
# advisory so Claude can skip the redundant call.
CACHEABLE_TOOLS = ("Read", "LS", "Glob", "Grep")
CACHE_TTL_SEC = 30
CACHE_MAX_AGE_SEC = 3600  # housekeeping prune horizon


def _cache_db_path() -> Path:
    return CONFIG_PATH.parent / "router-cache.sqlite"


def _cache_conn():
    p = _cache_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=2.0, isolation_level=None)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tool_cache ("
        "key TEXT PRIMARY KEY, tool TEXT, input_json TEXT, "
        "output TEXT, ts REAL, session_id TEXT, hits INTEGER DEFAULT 0)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS cache_stats ("
        "session_id TEXT, hits INTEGER, misses INTEGER, "
        "PRIMARY KEY(session_id))"
    )
    # v5.0 — Negative-Cache Short-Circuit (Pattern 10).
    # Track (prompt_fingerprint, alias) tuples that failed (output_verify
    # escalation, error_recovery, etc.). Skip them next time the
    # classifier would pick the same route. Effort intentionally NOT
    # part of key — once a route at any effort failed, upshift the tier.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS route_failures ("
        "fingerprint TEXT, alias TEXT, "
        "failure_kind TEXT, ts REAL, "
        "PRIMARY KEY(fingerprint, alias))"
    )
    return conn


def _route_fingerprint(text: str) -> str:
    """Stable 8-byte fingerprint of prompt prefix. blake2b is stdlib."""
    if not text:
        return ""
    return hashlib.blake2b(
        text[:512].encode("utf-8", errors="ignore"),
        digest_size=8
    ).hexdigest()


def cache_record_route_failure(text: str, alias: str,
                               failure_kind: str = "unknown") -> None:
    """Record that (fingerprint, alias) produced a bad result."""
    fp = _route_fingerprint(text)
    if not fp:
        return
    try:
        conn = _cache_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO route_failures "
                "(fingerprint, alias, failure_kind, ts) "
                "VALUES (?, ?, ?, ?)",
                (fp, alias, failure_kind, time.time()),
            )
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        pass


def cache_check_route_failure(text: str, alias: str,
                              max_age_sec: int = 24 * 3600) -> bool:
    """Returns True if this (fingerprint, alias) failed recently.
    Caller should skip directly to a higher tier."""
    fp = _route_fingerprint(text)
    if not fp:
        return False
    try:
        conn = _cache_conn()
        try:
            row = conn.execute(
                "SELECT ts FROM route_failures "
                "WHERE fingerprint=? AND alias=?",
                (fp, alias),
            ).fetchone()
            if not row:
                return False
            return (time.time() - row[0]) < max_age_sec
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return False


def _cache_key(tool_name: str, tool_input) -> str:
    try:
        ti_json = json.dumps(tool_input, sort_keys=True)
    except (TypeError, ValueError):
        ti_json = str(tool_input)
    blob = f"{tool_name}::{ti_json}".encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def cache_get(tool_name: str, tool_input, max_age_sec: int = CACHE_TTL_SEC):
    """Return cached row dict if hit within TTL, else None."""
    if tool_name not in CACHEABLE_TOOLS:
        return None
    try:
        conn = _cache_conn()
        try:
            row = conn.execute(
                "SELECT output, ts, hits FROM tool_cache WHERE key=?",
                (_cache_key(tool_name, tool_input),),
            ).fetchone()
            if not row:
                return None
            output, ts, hits = row
            age = time.time() - ts
            if age > max_age_sec:
                return None
            conn.execute(
                "UPDATE tool_cache SET hits=hits+1 WHERE key=?",
                (_cache_key(tool_name, tool_input),),
            )
            return {"output": output, "age_sec": age, "hits": hits + 1}
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return None


def cache_put(tool_name: str, tool_input, output: str, session_id: str = "") -> None:
    """Store tool output if tool is cacheable. Failures are silent."""
    if tool_name not in CACHEABLE_TOOLS:
        return
    if not output or len(output) > 200_000:
        # Skip empty + huge outputs (latter are usually streaming logs)
        return
    try:
        conn = _cache_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO tool_cache "
                "(key, tool, input_json, output, ts, session_id, hits) "
                "VALUES (?, ?, ?, ?, ?, ?, "
                "COALESCE((SELECT hits FROM tool_cache WHERE key=?), 0))",
                (
                    _cache_key(tool_name, tool_input), tool_name,
                    json.dumps(tool_input, sort_keys=True)[:8000],
                    output, time.time(), session_id,
                    _cache_key(tool_name, tool_input),
                ),
            )
            # Periodic housekeeping: prune entries older than 1h
            if hash(_cache_key(tool_name, tool_input)) % 64 == 0:
                conn.execute(
                    "DELETE FROM tool_cache WHERE ts < ?",
                    (time.time() - CACHE_MAX_AGE_SEC,),
                )
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        pass


def cache_record_stat(session_id: str, hit: bool) -> None:
    try:
        conn = _cache_conn()
        try:
            field = "hits" if hit else "misses"
            other = "misses" if hit else "hits"
            conn.execute(
                f"INSERT INTO cache_stats (session_id, {field}, {other}) "
                "VALUES (?, 1, 0) "
                f"ON CONFLICT(session_id) DO UPDATE SET {field}={field}+1",
                (session_id,),
            )
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        pass


def cache_stats_summary() -> dict:
    try:
        conn = _cache_conn()
        try:
            total_rows = conn.execute(
                "SELECT COUNT(*) FROM tool_cache"
            ).fetchone()[0]
            total_hits = conn.execute(
                "SELECT COALESCE(SUM(hits), 0) FROM tool_cache"
            ).fetchone()[0]
            agg = conn.execute(
                "SELECT COALESCE(SUM(hits), 0), COALESCE(SUM(misses), 0) "
                "FROM cache_stats"
            ).fetchone()
            sess_hits, sess_misses = agg if agg else (0, 0)
            total_q = sess_hits + sess_misses
            hit_rate = (sess_hits / total_q) if total_q else 0.0
            return {
                "rows": total_rows,
                "row_hits_total": total_hits,
                "session_hits": sess_hits,
                "session_misses": sess_misses,
                "hit_rate": hit_rate,
            }
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as e:
        return {"error": str(e)}


def session_temp_path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_\-]", "_", session_id or "default")
    return TMP_DIR / f"smart-router-{safe}.json"


def load_session_log(session_id: str) -> list:
    p = session_temp_path(session_id)
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def save_session_log(session_id: str, log: list) -> None:
    p = session_temp_path(session_id)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(log, f)
    os.replace(tmp, p)


def downgrade_effort(model_def: dict, requested: str) -> str:
    support = model_def.get("effort_support", [])
    if not support:
        return "none"
    if requested in support:
        return requested
    for level in EFFORT_PRIORITY:
        if level in support:
            return level
    return support[0]


def _tool_str(tool_input) -> str:
    try:
        return json.dumps(tool_input).lower()
    except (TypeError, ValueError):
        return str(tool_input).lower()


_ERROR_LINE_RE = re.compile(
    r"(?m)^(?:.{0,200})(Traceback \(most recent call last\)"
    r"|^[A-Z][a-zA-Z]*Error:"
    r"|undefined is not"
    r"|cannot read properties"
    r"|ENOENT"
    r"|ModuleNotFoundError"
    r"|ImportError)"
)


def _detect_error(out_str: str, exit_code=None, tool_name: str = "") -> bool:
    """Detect real errors. Skip false positives from logged/quoted strings.
    For Bash, REQUIRE non-zero exit code — many legitimate Bash outputs
    contain 'Traceback' as data (grep, git log, log files).
    """
    if not out_str:
        return False
    if tool_name == "Bash" and exit_code is not None and exit_code == 0:
        return False
    sample = out_str[-4000:]
    if "PASS\n" in sample and "test results" in sample.lower():
        return False
    if "Traceback (most recent call last):" in sample and "  File " in sample:
        return True
    for sig in ("SyntaxError:", "TypeError:", "NameError:",
                "ModuleNotFoundError", "ImportError:"):
        if re.search(r"^" + re.escape(sig), sample, re.MULTILINE):
            return True
    if "ENOENT" in sample and ("Error" in sample or "error" in sample):
        return True
    if "undefined is not" in sample:
        return True
    if "cannot read properties" in sample:
        return True
    return False


def _content_length(tool_input) -> int:
    """Raw content length, skipping JSON overhead. Falls back to full str."""
    if isinstance(tool_input, dict):
        for key in ("content", "new_string", "command"):
            v = tool_input.get(key)
            if isinstance(v, str):
                return len(v)
        if "edits" in tool_input and isinstance(tool_input["edits"], list):
            return sum(
                len(e.get("new_string", "")) for e in tool_input["edits"]
                if isinstance(e, dict)
            )
    return len(_tool_str(tool_input))


def _build_sensitive_re(keywords):
    """Compile token-boundary regex over sensitive keywords."""
    if not keywords:
        return None
    parts = [re.escape(k) for k in keywords]
    return re.compile(
        r"(?<![A-Za-z0-9_])(?:" + "|".join(parts) +
        r")(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )


def _scan_for_kw(text, pattern):
    if not pattern or not text:
        return ""
    m = pattern.search(text)
    return m.group(0).lower() if m else ""


def _location_weighted_sensitive(tool_input, keywords) -> tuple:
    """Return (matched_kw, weight) where weight 1.0 = strong signal,
    0.6 = soft signal (kw buried in free-text content)."""
    pattern = _build_sensitive_re(keywords)
    if not pattern:
        return ("", 0.0)
    if not isinstance(tool_input, dict):
        text = _tool_str(tool_input)
        kw = _scan_for_kw(text, pattern)
        return (kw, 0.6) if kw else ("", 0.0)
    strong_fields = ("path", "file_path", "command", "old_string",
                     "new_string", "pattern", "subagent_type")
    for field in strong_fields:
        v = tool_input.get(field, "")
        if isinstance(v, str):
            kw = _scan_for_kw(v, pattern)
            if kw:
                return (kw, 1.0)
    content = tool_input.get("content", "")
    if isinstance(content, str):
        hits = []
        for m in pattern.finditer(content):
            hits.append(m.group(0).lower())
            if len(hits) >= 3:
                break
        if len(hits) >= 2:
            return (hits[0], 0.9)
        if hits:
            high_risk = {"private_key", "api_key", "secret", "password",
                         "access_token", "refresh_token", ".env", "dotenv"}
            if hits[0] in high_risk:
                return (hits[0], 0.95)
            return (hits[0], 0.6)
    return ("", 0.0)


def compute_confidence(tool_name, tool_input, decision_alias) -> float:
    """0..1 — how sure the classifier is. Low confidence = escalate."""
    length = _content_length(tool_input)
    if decision_alias == "haiku":
        if length < 100:
            return 0.98
        if length < 200:
            return 0.92
        return 0.85
    if decision_alias == "sonnet":
        if 1400 <= length <= 1600 or 3800 <= length <= 4200:
            return 0.65
        return 0.88
    if decision_alias == "opus":
        if length >= 6000:
            return 0.97
        return 0.90
    return 0.80


def compute_output_confidence(out_str: str, tool_name: str,
                              had_error: bool, alias: str) -> float:
    """AutoMix-lite: score how plausible a tool output looks. Below the
    preset threshold the post-hook surfaces an escalate advisory.

    Heuristics (no model call — must stay in the <50ms hook budget):
    - Output has a real error signature → 0.10
    - Output empty or whitespace-only → 0.20
    - Output suspiciously short for the tool → 0.50
    - Output reasonable length + clean structure → 0.85
    - Output verbose with structure (lines / code blocks) → 0.95
    """
    if had_error:
        return 0.10
    if not out_str or not out_str.strip():
        return 0.20
    n = len(out_str)
    expected_min = {
        "Read": 5,
        "Glob": 1,
        "Grep": 1,
        "LS": 5,
        "Bash": 0,
        "Write": 0,
        "Edit": 0,
        "MultiEdit": 0,
    }.get(tool_name, 0)
    if n < expected_min:
        return 0.45
    structure_signals = (
        out_str.count("\n") >= 3,
        "```" in out_str,
        ":" in out_str[:200],
    )
    structure_score = sum(1 for s in structure_signals if s)
    if alias == "haiku":
        if n < 50:
            return 0.55
        if structure_score >= 2:
            return 0.92
        return 0.78
    if alias == "sonnet":
        if structure_score >= 2:
            return 0.93
        return 0.85
    return 0.95


def confidence_threshold(config: dict) -> float:
    """Per-preset acceptance threshold for output confidence.
    v6.3: quality mode threshold raised to 0.95 — quality preset
    should escalate weak outputs more aggressively, not less."""
    mode = config.get("mode", "balanced")
    return {"eco": 0.55, "balanced": 0.75,
            "quality": 0.95, "precise": 0.97}.get(mode, 0.75)


def quality_moa_recommended(config: dict, prompt_text: str) -> bool:
    """v6.3 MoA-Lite trigger. In quality mode, when prompt is complex
    AND high-stakes (touches multiple decision dimensions), recommend
    /atrain-moa for parallel multi-perspective dispatch."""
    if config.get("mode") != "quality":
        return False
    if not prompt_text or len(prompt_text) < 80:
        return False
    text = prompt_text.lower()
    # High-stakes signals — these pair well with MoA's perspective fanout
    stakes_kw = (
        "production", "ship", "deploy", "critical", "review all",
        "refactor entire", "architecture", "design pattern",
        "tradeoff", "trade-off", "choose between", "which approach",
        "best practice", "should i", "what's the best",
    )
    return any(k in text for k in stakes_kw)


def classify_task(tool_name: str, tool_input, config: dict) -> dict:
    tool_str = _tool_str(tool_input)
    length = _content_length(tool_input)
    sonnet_effort = config["thresholds"].get("sonnet_effort", "high")
    opus_effort = config["thresholds"].get("opus_effort", "high")
    precise = config.get("accuracy_target", 99.0) >= 99.9

    for kw in OPUS_KEYWORDS:
        if kw in tool_str:
            eff = "xhigh" if precise and opus_effort == "high" else opus_effort
            return {"model_alias": "opus", "effort": eff,
                    "reason": f"opus-keyword: {kw}"}

    paths = PATH_RE.findall(tool_str)
    n_paths = len(paths)

    if tool_name in ("Write", "Edit", "MultiEdit") and length >= 4000:
        eff = "xhigh" if precise and opus_effort == "high" else opus_effort
        return {"model_alias": "opus", "effort": eff,
                "reason": f"large {tool_name} ({length} chars)"}
    if n_paths >= 3:
        eff = "xhigh" if precise and opus_effort == "high" else opus_effort
        return {"model_alias": "opus", "effort": eff,
                "reason": f"multi-file ({n_paths} paths)"}

    # READ-ONLY tools route to haiku regardless of precise mode.
    # No correctness risk on Read/LS/Glob/Grep/safe-Bash — gating these
    # behind `not precise` triples cost on read-only ops. PRECISE only
    # affects writes/formatters.
    if tool_name in ("Read", "LS", "Glob") and length < 300:
        return {"model_alias": "haiku", "effort": "none",
                "reason": f"small {tool_name} ({length} chars)"}
    if tool_name == "Grep" and length < 150:
        return {"model_alias": "haiku", "effort": "none",
                "reason": "small Grep"}
    if tool_name == "WebSearch" and length < 100:
        return {"model_alias": "haiku", "effort": "none",
                "reason": "short WebSearch"}
    if tool_name == "Bash":
        cmd = ""
        if isinstance(tool_input, dict):
            cmd = str(tool_input.get("command", ""))
        if HAIKU_BASH_RE.match(cmd):
            return {"model_alias": "haiku", "effort": "none",
                    "reason": "read-only Bash"}
    if not precise:
        # Formatters (write side-effects) — only haiku in non-precise mode
        formatters = ("prettier", "black", "eslint --fix", "gofmt")
        if tool_name == "Bash" and isinstance(tool_input, dict):
            cmd_lower = str(tool_input.get("command", "")).lower().lstrip()
            for fmt in formatters:
                if cmd_lower.startswith(fmt):
                    return {"model_alias": "haiku", "effort": "none",
                            "reason": f"formatter: {fmt}"}

    if tool_name in ("Write", "Edit", "MultiEdit") and 1500 <= length < 4000:
        if precise:
            eff = "xhigh" if opus_effort == "high" else opus_effort
            return {"model_alias": "opus", "effort": eff,
                    "reason": "medium Write (precise)"}
        return {"model_alias": "sonnet", "effort": "high",
                "reason": f"medium {tool_name} ({length} chars)"}
    if n_paths == 2:
        if precise:
            eff = "xhigh" if opus_effort == "high" else opus_effort
            return {"model_alias": "opus", "effort": eff,
                    "reason": "2 paths (precise)"}
        return {"model_alias": "sonnet", "effort": "high",
                "reason": "2 paths in input"}
    api_re = re.compile(
        r"\b(?:" + "|".join(re.escape(k) for k in API_KEYWORDS) + r")\b"
    )
    api_match = api_re.search(tool_str)
    if api_match:
        if precise:
            eff = "xhigh" if opus_effort == "high" else opus_effort
            return {"model_alias": "opus", "effort": eff,
                    "reason": f"{api_match.group(0)} (precise)"}
        return {"model_alias": "sonnet", "effort": "high",
                "reason": f"api-keyword: {api_match.group(0)}"}

    if tool_name in ("Write", "Edit", "MultiEdit") and length < 1500:
        if precise:
            return {"model_alias": "opus", "effort": "high",
                    "reason": f"small {tool_name} (precise)"}
        return {"model_alias": "sonnet", "effort": "medium",
                "reason": f"small {tool_name}"}
    if tool_name == "Bash" and TEST_RUNNER_RE.search(tool_str):
        if precise:
            return {"model_alias": "opus", "effort": "high",
                    "reason": "test runner (precise)"}
        return {"model_alias": "sonnet", "effort": "medium",
                "reason": "test runner"}
    for kw in BOILERPLATE_STRONG:
        if kw in tool_str:
            if precise:
                return {"model_alias": "opus", "effort": "high",
                        "reason": "boilerplate (precise)"}
            return {"model_alias": "sonnet", "effort": "medium",
                    "reason": f"boilerplate: {kw}"}
    for kw in BOILERPLATE_WEAK:
        if kw in tool_str and any(a in tool_str for a in BOILERPLATE_ANCHORS):
            if precise:
                return {"model_alias": "opus", "effort": "high",
                        "reason": "boilerplate (precise)"}
            return {"model_alias": "sonnet", "effort": "medium",
                    "reason": f"boilerplate: {kw}+anchor"}

    if precise:
        return {"model_alias": "opus", "effort": "high",
                "reason": "default (precise)"}
    return {"model_alias": "sonnet", "effort": "medium", "reason": "default"}


def hard_escalation(tool_input, config: dict, session_id: str) -> tuple:
    tool_str = _tool_str(tool_input)
    n_paths = len(PATH_RE.findall(tool_str))
    if n_paths > 3:
        return (True, f"multi-file: >3 paths ({n_paths})")
    keywords = config.get("hard_escalation_keywords", [])
    matched_kw, weight = _location_weighted_sensitive(tool_input, keywords)
    if matched_kw and weight >= 0.85:
        return (True, f"sensitive: {matched_kw}")
    log = load_session_log(session_id)
    last_post = None
    for entry in reversed(log):
        if entry.get("phase") == "post":
            last_post = entry
            break
    if last_post and last_post.get("had_error"):
        return (True, "error recovery")
    for p in USER_PHRASES:
        if p in tool_str:
            return (True, f"user phrase: {p}")
    if isinstance(tool_input, dict):
        path = str(tool_input.get("path") or tool_input.get("file_path", "")).lower()
        cmd = str(tool_input.get("command", "")).lower()
        for mf in MANIFEST_FILES:
            if mf in path or mf in cmd:
                return (True, f"manifest: {mf}")
    if matched_kw and weight >= 0.6:
        return (True, f"sensitive (soft): {matched_kw}")
    return (False, "")


def _classify_escalation_kind(reason: str) -> str:
    r = reason.lower()
    if r.startswith("multi-file") or r.startswith("manifest"):
        return "multi_file"
    if r.startswith("sensitive"):
        return "auth_secrets"
    if "error recovery" in r:
        return "error_recovery"
    if r.startswith("user phrase"):
        return "user_phrase"
    return "auth_secrets"


def classify_to_agent(full_text: str, config: dict) -> str:
    """Pick the router agent that best fits the task text. Consults
    routing_tables[mode][tier] so eco/balanced/quality biases actually
    take effect on Task dispatches (not just per-tool-call routing).

    v5.0: also consults route_failures negative-cache. If the chosen
    agent failed on a similar prompt within the last 24h, the helper
    upshifts to the next tier automatically.

    Keyword sets are tuned against tools/evals/router_eval.json — change
    them in tandem with that corpus and re-run run_eval.py."""
    text = full_text.lower()
    mode = config.get("mode", "balanced")
    table = config.get("routing_tables", {}).get(mode, {})

    UPSHIFT = {
        "recon-haiku": "impl-sonnet",
        "impl-sonnet": "api-sonnet",
        "api-sonnet": "architect-opus",
        "architect-opus": "secure-opus",
        "secure-opus": "secure-opus",
    }

    def via_table(tier: str, fallback: str) -> str:
        agent = table.get(tier, fallback)
        # v5.0 negative-cache check: if we know this route failed recently
        # for a similar prompt, upshift one tier.
        if cache_check_route_failure(text, agent):
            return UPSHIFT.get(agent, agent)
        return agent

    sensitive_phrases = (
        "api key", "database migration", "rotate the api",
        "rotate the api key", "drop column", "drop table",
        "drops the", "alter table", "webhook handler",
        "webhook event",
    )
    if any(kw in text for kw in config.get("hard_escalation_keywords", [])):
        return via_table("sensitive", "secure-opus")
    if any(p in text for p in sensitive_phrases):
        return via_table("sensitive", "secure-opus")
    arch_kw = (
        "architecture", "design pattern", "refactor entire",
        "refactor the entire", "redesign", "bottleneck", "optimize",
        "review all", "performance optimization", "system design",
        "refactor the", "rewrite the entire",
    )
    if any(k in text for k in arch_kw):
        return via_table("architecture", "architect-opus")
    api_kw = (
        "endpoint", " route", "api integration", "third-party",
        "http handler", "rest api", "graphql", "rest endpoints",
    )
    if any(k in text for k in api_kw):
        return via_table("api", "api-sonnet")
    recon_kw = (
        "find ", "where is", "list files", "search for", "search the",
        "look up", "look at", "show me", "explore", "grep ", "locate",
        "tell me what", "what's outdated", "scan the",
    )
    write_kw = (
        "implement", "write a", "build a", "fix the", "edit ",
        "modify", "refactor ", "add a", "create a",
    )
    if any(k in text for k in recon_kw) and not any(k in text for k in write_kw):
        return via_table("recon", "recon-haiku")
    return via_table("impl", "impl-sonnet")


def handle_task_dispatch(data: dict) -> None:
    with config_lock():
        return _handle_task_dispatch_inner(data)


def _handle_task_dispatch_inner(data: dict) -> None:
    config = load_config()
    tool_input = data.get("tool_input", {}) or {}
    session_id = data.get("session_id", "default")
    subagent_type = str(tool_input.get("subagent_type", "")).strip()
    prompt = str(tool_input.get("prompt", ""))
    description = str(tool_input.get("description", ""))
    full_text = (prompt + " " + description).lower()

    recommended = classify_to_agent(full_text, config)
    is_sensitive = any(kw in full_text for kw in
                       config.get("hard_escalation_keywords", []))
    is_router_agent = subagent_type in ROUTER_AGENTS
    is_opus_agent = subagent_type in OPUS_AGENTS

    stats = config.setdefault("session_stats", _empty_stats())
    dispatches = stats.setdefault("task_dispatches", {})
    key = subagent_type or "(unknown)"
    dispatches[key] = dispatches.get(key, 0) + 1

    output = {}
    blocked = False

    if is_sensitive and not is_opus_agent:
        blocked = True
        stats["dispatch_blocks"] = stats.get("dispatch_blocks", 0) + 1
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": (
                    "smart-router: sensitive content detected "
                    f"(auth/secrets/crypto). Recommend dispatching to "
                    f"'secure-opus' instead of '{subagent_type or 'unspecified'}'."
                ),
            }
        }
    elif is_router_agent and recommended != subagent_type:
        stats["dispatch_mismatches"] = stats.get("dispatch_mismatches", 0) + 1
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": (
                    f"smart-router: routing '{subagent_type}' (Claude's "
                    f"choice). Heuristic suggested '{recommended}'."
                ),
            }
        }

    log = load_session_log(session_id)
    log.append({
        "phase": "pre",
        "tool": "Task",
        "subagent_type": subagent_type,
        "recommended": recommended,
        "blocked": blocked,
        "ts": datetime.now().isoformat(),
    })
    save_session_log(session_id, log)
    save_config(config)

    if output:
        sys.stdout.write(json.dumps(output))
    else:
        sys.stdout.write("{}")


def _apply_registry_update(config: dict, api_resp: dict) -> None:
    models = api_resp.get("data", []) if isinstance(api_resp, dict) else []

    def latest_for(prefix: str) -> str:
        candidates = [m for m in models if isinstance(m, dict)
                      and m.get("id", "").startswith(prefix)]
        if not candidates:
            return ""
        candidates.sort(key=lambda m: m.get("id", ""), reverse=True)
        return candidates[0].get("id", "")

    for alias, prefix in (
        ("opus", "claude-opus-4"),
        ("sonnet", "claude-sonnet-4"),
        ("haiku", "claude-haiku-4"),
    ):
        new_id = latest_for(prefix)
        if new_id:
            config["model_registry"][alias]["id"] = new_id
            config["model_registry"][alias]["alias"] = new_id


def handle_session_start(data: dict) -> None:
    """No network. Bundled-tokens-only. v6.1: also injects per-project
    session memory digest if available (claude-mem pattern, native)."""
    config = load_config()
    last_check = config.get("last_model_check", "")
    try:
        last_dt = datetime.fromisoformat(last_check)
        age_hours = (datetime.now() - last_dt).total_seconds() / 3600.0
    except (ValueError, TypeError):
        age_hours = 999.0

    parts = []
    # v6.1 — session memory injection for project continuity
    memory_text = load_session_memory_for_inject()
    if memory_text:
        parts.append(memory_text)

    if age_hours > 24 * 30:
        parts.append(
            "ATrain: model registry was last refreshed "
            f"{int(age_hours/24)} days ago. Refresh manually with "
            "ANTHROPIC_API_KEY set: curl -s "
            "https://api.anthropic.com/v1/models -H \"x-api-key: "
            "$ANTHROPIC_API_KEY\" -H \"anthropic-version: 2023-06-01\" "
            "| python3 .claude/hooks/router.py --update-models"
        )

    if not parts:
        sys.stdout.write("{}")
        return
    sys.stdout.write(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n\n".join(parts),
        }
    }))


def handle_user_prompt_submit(data: dict) -> None:
    """Hybrid: first prompt → suggest preset; structurally multi-faceted
    prompt → suggest decompose. v6.0: also injects terse-output style
    rules (caveman pattern) when mode is eco."""
    config = load_config()
    session_id = data.get("session_id", "default")
    prompt = str(data.get("prompt") or data.get("user_prompt") or "")
    log = load_session_log(session_id)
    is_first = not any(e.get("phase") == "pre" for e in log)
    mode = config.get("mode", "balanced")
    decompose_on = bool(config.get("decompose_enabled", False))
    is_multi, signals = detect_multi_faceted(prompt)

    parts = []
    # v6.5 — full caveman pattern injection (ported from JuliusBrussee/caveman).
    # Eco mode triggers FULL intensity; user can override via
    # config.caveman_intensity (lite|full|ultra). Real measured 65-75%
    # output reduction (median 65%, range 22-87% across 10 tasks per
    # caveman repo's three-arm eval harness).
    intensity = config.get("caveman_intensity")
    if intensity is None and mode == "eco":
        intensity = "full"
    if intensity in ("lite", "full", "ultra"):
        rules = (
            "ATrain caveman mode ACTIVE — terse output, every response.\n\n"
            "PERSISTENCE\n"
            "  Active every response in this conversation. No revert after\n"
            "  many turns. No filler drift. Still active if unsure.\n\n"
            "RULES\n"
            "  Drop: articles (a/an/the), filler (just/really/basically/\n"
            "  actually/simply), pleasantries (sure/certainly/of course/\n"
            "  happy to), hedging.\n"
            "  Fragments OK. Short synonyms (big not extensive, fix not\n"
            "  'implement a solution for'). Technical terms exact.\n"
            "  Code blocks unchanged. Errors quoted exact.\n\n"
            "PATTERN\n"
            "  '[thing] [action] [reason]. [next step].'\n"
            "  Not: 'Sure! I'd be happy to help. The issue you're\n"
            "       experiencing is likely caused by...'\n"
            "  Yes: 'Bug in auth middleware. Token expiry use `<` not\n"
            "       `<=`. Fix:'\n\n"
        )
        if intensity == "ultra":
            rules += (
                "ULTRA EXTRA\n"
                "  Abbreviate (DB/auth/config/req/res/fn/impl), strip\n"
                "  conjunctions, arrows for causality (X → Y), one word\n"
                "  when one word enough.\n\n"
            )
        elif intensity == "lite":
            rules = rules.replace(
                "Fragments OK.",
                "Keep grammar + full sentences. Professional but tight.",
            )
        rules += (
            "AUTO-CLARITY (drop caveman, resume after)\n"
            "  - Security warnings\n"
            "  - Irreversible action confirmations (delete/drop/migrate)\n"
            "  - Multi-step sequences where fragment order risks misread\n"
            "  - User asks to clarify or repeats question\n\n"
            "BOUNDARIES\n"
            "  Code/commits/PRs/security: write NORMAL. Never compress."
        )
        parts.append(rules)

    # v6.3 — MoA-Lite advisory (Mixture-of-Agents pattern).
    # Quality mode + complex high-stakes prompt → suggest /atrain-moa
    # for parallel multi-perspective dispatch with a synthesis pass.
    if quality_moa_recommended(config, prompt):
        parts.append(
            "ATrain (quality + high-stakes detected): consider "
            "/atrain-moa for this task — dispatches 2-3 architect-opus "
            "subagents in parallel with varied framings, then "
            "synthesizes. Per Wang et al. 2024, MoA-Lite beats "
            "single-Opus on multi-perspective tasks at the cost of "
            "2-3× a single dispatch. Worth it for production decisions."
        )
    if is_first:
        parts.append(
            f"smart-router active (mode: {mode}). Three presets: "
            "/router-eco (95% acc, ~90% saved), "
            "/router-balanced (99% acc, ~50% saved, default), "
            "/router-quality (99.9% acc, ~20% saved). "
            "Briefly mention these once at the start of the first response, "
            "then proceed with the user's task. Auto-pick eco only if the "
            "user signals cost-sensitivity, quality only if they signal "
            "high stakes."
        )

    if is_multi and not decompose_on:
        parts.append(
            f"This prompt looks multi-faceted (signals: {', '.join(signals)}). "
            "Consider decomposing it into 2-5 parallel subagent chunks via "
            "the smart-router pattern (recon-haiku for read-only, "
            "impl-sonnet for bounded code-writing, architect-opus for "
            "design/multi-file, secure-opus for auth/secret/crypto). "
            "Dispatch independent chunks in parallel via Task tool calls "
            "in the same assistant message. To enable this for the whole "
            "session: /router-on. To force just this one prompt: "
            "/router-once. If you decompose, print the plan first."
        )
    elif decompose_on:
        parts.append(
            f"decompose_enabled=true ({mode} bias). Reason about this "
            "prompt's subtasks, plan 2-7 chunks with subagent assignments, "
            "print the plan, then dispatch independent chunks in parallel. "
            "Skip decomposition only if the prompt is trivially single-step."
        )
    elif is_multi and decompose_on:
        # both true — same as decompose_on path
        pass

    if not parts:
        sys.stdout.write("{}")
        return
    sys.stdout.write(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "\n\n".join(parts),
        }
    }))


def handle_pre_tool_use(data: dict) -> None:
    if data.get("tool_name") == "Task":
        return handle_task_dispatch(data)
    with config_lock():
        return _handle_pre_tool_use_inner(data)


def _handle_pre_tool_use_inner(data: dict) -> None:
    config = load_config()
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {}) or {}
    session_id = data.get("session_id", "default")

    if tool_name == "Task":
        return handle_task_dispatch(data)

    # v5.0 — aggressive Task forcing in eco mode for cacheable tools.
    # Hook returns permissionDecision: ask with a clear suggestion to
    # use Task dispatch instead. User can approve to bypass. Pushes
    # eco mode toward its real -70% savings target by making subagent
    # dispatch the path of least resistance.
    mode = config.get("mode", "balanced")
    if (mode == "eco"
            and tool_name in CACHEABLE_TOOLS
            and config.get("force_subagent_recon", False)):
        suggested_agent = (
            config.get("routing_tables", {})
            .get("eco", {}).get("recon", "recon-haiku")
        )
        sys.stdout.write(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": (
                    f"ATrain (eco): {tool_name} is recon-class. "
                    f"Spawn Task(subagent_type='{suggested_agent}', "
                    f"prompt='...') instead — runs on Haiku at "
                    f"~80% bundled-token discount. Approve to run "
                    f"on parent session anyway."
                ),
            }
        }))
        return

    # Pattern 4 lite: detect duplicate cacheable tool calls within TTL
    cache_advisory = ""
    if tool_name in CACHEABLE_TOOLS:
        hit = cache_get(tool_name, tool_input)
        cache_record_stat(session_id, bool(hit))
        if hit:
            excerpt = hit["output"][:300].replace("\n", " ")
            cache_advisory = (
                f"smart-router: duplicate {tool_name} detected — same "
                f"input was called {int(hit['age_sec'])}s ago and returned "
                f"~{len(hit['output'])} chars. Output excerpt: '{excerpt}…'. "
                f"Skip re-running this if the underlying file/state hasn't "
                f"changed."
            )

    cls = classify_task(tool_name, tool_input, config)
    model_alias = cls["model_alias"]
    effort = cls["effort"]
    reason = cls["reason"]

    escalated, esc_reason = hard_escalation(tool_input, config, session_id)
    if escalated:
        model_alias = "opus"
        effort = "xhigh"
        reason = esc_reason
        kind = _classify_escalation_kind(esc_reason)
        stats = config.setdefault("session_stats", _empty_stats())
        stats["escalations_total"] = stats.get("escalations_total", 0) + 1
        key = f"escalations_{kind}"
        stats[key] = stats.get(key, 0) + 1

    precise = config.get("accuracy_target", 99.0) >= 99.9
    if precise and model_alias == "sonnet":
        model_alias = "opus"
        effort = "high"
    if precise and model_alias == "opus" and effort == "high":
        effort = "xhigh"

    model_def = config["model_registry"].get(model_alias, {})
    full_id = model_def.get("id", model_alias)

    if model_alias == "haiku":
        log_effort = "none"
        tier_label = f"{model_alias}+none"
        effort_text = ""
    else:
        effort = downgrade_effort(model_def, effort)
        log_effort = effort
        tier_label = f"{model_alias}+{effort}"
        effort_text = f"+{effort}"

    confidence = compute_confidence(tool_name, tool_input, model_alias)

    if confidence < 0.70 and model_alias == "haiku":
        model_alias = "sonnet"
        effort = downgrade_effort(
            config["model_registry"]["sonnet"], "medium"
        )
        log_effort = effort
        tier_label = f"sonnet+{effort}"
        effort_text = f"+{effort}"
        full_id = config["model_registry"]["sonnet"]["id"]
        reason = f"{reason} (conf {confidence:.2f} → bump)"

    # v4.0 — honest advisory. The Claude Code runtime ignores any
    # model_override field a hook returns; the ONLY real per-call
    # model swap on bundled-token subscriptions is via subagent
    # dispatch (Task tool with subagent_type). The advisory below
    # tells Claude what would have been cheap if dispatched, so the
    # parent session can choose to spawn a subagent instead.
    advice = (
        f"smart-router: would route {tool_name} → {model_alias}"
        f"{effort_text} ({reason} | conf={confidence:.2f})."
    )

    # v6.2 — Layer 4 codebase index lookup (graphify pattern, native).
    # When user does Grep for what looks like a symbol name AND the
    # project index has been built, surface the symbol's location as an
    # advisory. Claude can choose to skip the grep entirely.
    index_advisory = ""
    if tool_name == "Grep" and isinstance(tool_input, dict):
        pat = str(tool_input.get("pattern", "")).strip()
        # Heuristic: short, identifier-shaped → likely a symbol name
        if pat and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", pat) and 2 < len(pat) < 60:
            hits = lookup_symbol(pat, limit=5)
            if hits:
                lines = [f"ATrain index: '{pat}' found in pre-built index:"]
                for h in hits[:5]:
                    lines.append(f"  • {h['path']}:{h['line']}  "
                                 f"{h['kind']}  {h['signature'][:80]}")
                lines.append("Skip the Grep if you only needed locations — "
                             "the index is fresh as of last /atrain-index.")
                index_advisory = "\n".join(lines)

    # v6.0 — Layer 2 tool-input compaction (claw-compactor pattern).
    # When tool_input has huge content/old_string/new_string fields,
    # rewrite via updatedInput so the parent session sees a truncated
    # version. Saves 30-50% on bloated inputs. Runtime DOES honor
    # updatedInput as of v2.0.10.
    compacted_input, was_compacted = compact_tool_input(tool_input)

    # v6.4 — rtk-pattern Bash command pre-rewriter.
    # Operates BEFORE the shell executes the command. Rewrites bloated
    # commands into compact equivalents (ls → ls | head -100, pytest →
    # pytest -q, git log → git log --oneline -n 20, etc.). The runtime
    # honors updatedInput.command so the rewrite IS executed; subsequent
    # Bash output is naturally smaller. Real measured savings up to 90%
    # on test runners and find/git commands per rtk-ai/rtk benchmarks.
    if (tool_name == "Bash"
            and config.get("bash_pre_rewrite_enabled", True)
            and isinstance(compacted_input, dict)):
        original_cmd = compacted_input.get("command", "")
        if original_cmd:
            new_cmd, was_rewritten = rewrite_bash_command(original_cmd)
            if was_rewritten:
                compacted_input = dict(compacted_input)
                compacted_input["command"] = new_cmd
                was_compacted = True
                advice = (advice + "\n\nATrain v6.4: rewrote bash command "
                          f"{original_cmd!r} → {new_cmd!r} for compact output "
                          "(rtk pattern, real -80% measured).")
    mode = config.get("mode", "balanced")
    if tool_name in CACHEABLE_TOOLS and mode == "eco":
        suggested_agent = (
            config.get("routing_tables", {})
            .get("eco", {}).get("recon", "recon-haiku")
        )
        advice += (
            f"\n\nECO MODE TIP: this is a recon-class call. "
            f"Consider Task(subagent_type='{suggested_agent}', prompt=...) "
            "to run it on a cheaper bundled-token tier in parallel — "
            "saves ~80% bundled tokens vs the parent session."
        )
    if cache_advisory:
        advice = advice + "\n\n" + cache_advisory
    if index_advisory:
        advice = advice + "\n\n" + index_advisory
    hso = {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "additionalContext": advice,
    }
    # v6.0 — runtime-honored input rewrite (claw-compactor pattern).
    if was_compacted:
        hso["updatedInput"] = compacted_input
    output = {
        "hookSpecificOutput": hso,
        # v4.0: model_override + effort REMOVED — runtime ignored them.
        # advised_* fields kept for plugin's analytics consumers only;
        # they are not interpreted by Claude Code's runtime.
        "tier_label": tier_label,
        "advised_model": full_id,
        "advised_effort": log_effort,
        "reason": reason,
        "confidence": round(confidence, 3),
    }

    log = load_session_log(session_id)
    log.append({
        "phase": "pre",
        "tool": tool_name,
        "tier": output["tier_label"],
        "model": full_id,
        "model_alias": model_alias,
        "effort": log_effort,
        "escalated": escalated,
        "escalation_reason": esc_reason if escalated else "",
        "had_error": False,
        "ts": datetime.now().isoformat(),
    })
    save_session_log(session_id, log)
    if escalated:
        save_config(config)

    sys.stdout.write(json.dumps(output))


def _alias_from_model(model_used: str) -> str:
    m = (model_used or "").lower()
    if "haiku" in m:
        return "haiku"
    if "opus" in m:
        return "opus"
    return "sonnet"


def handle_post_tool_use(data: dict) -> None:
    with config_lock():
        return _handle_post_tool_use_inner(data)


def _handle_post_tool_use_inner(data: dict) -> None:
    config = load_config()
    tool_name = data.get("tool_name", "")
    tool_output = (data.get("tool_output", "")
                   or data.get("tool_response", "") or "")
    session_id = data.get("session_id", "default")

    model_used = data.get("model_used", "")
    effort_used = data.get("effort_used", "none")
    if not model_used:
        log_seek = load_session_log(session_id)
        for entry in reversed(log_seek):
            if entry.get("phase") == "pre":
                model_used = entry.get("model", "")
                effort_used = entry.get("effort", "none")
                break

    alias = _alias_from_model(model_used)
    if alias == "haiku":
        effort_used = "none"
    if not effort_used:
        effort_used = "none"

    tier_key = f"{alias}_{effort_used}"
    out_str = str(tool_output)
    token_est = len(out_str) // 4

    stats = config.setdefault("session_stats", _empty_stats())
    stats.setdefault("calls_by_tier", {})
    stats.setdefault("tokens_by_tier", {})
    stats["calls_by_tier"][tier_key] = stats["calls_by_tier"].get(tier_key, 0) + 1
    stats["tokens_by_tier"][tier_key] = stats["tokens_by_tier"].get(tier_key, 0) + token_est
    stats["total_calls"] = stats.get("total_calls", 0) + 1

    model_def = config["model_registry"].get(alias, {})
    out_price = model_def.get("output_price_per_1m", 15.0)
    actual_cost = token_est * (out_price / 1_000_000.0)
    baseline_cost = token_est * (25.0 / 1_000_000.0)
    stats["estimated_cost_usd"] = stats.get("estimated_cost_usd", 0.0) + actual_cost
    stats["baseline_opus_xhigh_cost_usd"] = (
        stats.get("baseline_opus_xhigh_cost_usd", 0.0) + baseline_cost
    )
    stats["estimated_savings_usd"] = (
        stats["baseline_opus_xhigh_cost_usd"] - stats["estimated_cost_usd"]
    )

    # v4.0 honest accounting — only credit "real_savings_usd" when the
    # call actually fanned out via Task to a different-model subagent.
    # Main-session tool calls go to "advisory_savings_usd" because the
    # runtime did not honor any model swap; the savings are aspirational.
    saving = baseline_cost - actual_cost
    is_subagent_dispatch = tool_name == "Task"
    if is_subagent_dispatch and saving > 0:
        stats["real_subagent_calls"] = stats.get("real_subagent_calls", 0) + 1
        stats["real_savings_usd"] = stats.get("real_savings_usd", 0.0) + saving
    else:
        stats["advisory_calls"] = stats.get("advisory_calls", 0) + 1
        stats["advisory_savings_usd"] = (
            stats.get("advisory_savings_usd", 0.0) + max(0.0, saving)
        )

    exit_code = data.get("exit_code")
    if exit_code is None and isinstance(data.get("tool_response"), dict):
        exit_code = data["tool_response"].get("exit_code")
    had_error = _detect_error(out_str, exit_code=exit_code, tool_name=tool_name)

    precise = config.get("accuracy_target", 99.0) >= 99.9
    verify_resp = None
    if precise:
        if had_error:
            verify_resp = {"verified": False, "reason": "error_in_output"}
        elif not out_str.strip():
            verify_resp = {"verified": False, "reason": "empty_output"}

    log = load_session_log(session_id)
    escalated_flag = bool(verify_resp) or had_error
    esc_reason = ""
    if verify_resp:
        esc_reason = verify_resp["reason"]
    elif had_error:
        esc_reason = "error_in_output"
    log.append({
        "phase": "post",
        "tool": tool_name,
        "tier": tier_key,
        "tokens": token_est,
        "had_error": had_error,
        "escalated": escalated_flag,
        "escalation_reason": esc_reason,
        "ts": datetime.now().isoformat(),
    })
    save_session_log(session_id, log)

    # v6.0 — Layer 8 Bash output compaction (rtk pattern).
    # Compress raw Bash output before caching it. Reduces cache size
    # AND if the runtime exposes the compacted form to Claude on the
    # NEXT call, saves bundled tokens proportionally.
    bash_compaction_saved = 0
    if tool_name == "Bash" and out_str:
        original_len = len(out_str)
        compacted_out = compact_bash_output(out_str)
        if len(compacted_out) < original_len:
            bash_compaction_saved = original_len - len(compacted_out)
            out_str = compacted_out
            stats.setdefault("bash_compaction_chars_saved", 0)
            stats["bash_compaction_chars_saved"] += bash_compaction_saved

    # Pattern 4 lite: cache successful cacheable tool outputs.
    # PostToolUse data mirrors tool_input from the dispatch; reuse it
    # directly so cache key matches the PreToolUse lookup.
    if not had_error and tool_name in CACHEABLE_TOOLS:
        cache_input = data.get("tool_input", {}) or {}
        cache_put(tool_name, cache_input, out_str, session_id=session_id)

    if had_error:
        stats["escalations_error_recovery"] = stats.get("escalations_error_recovery", 0) + 1
        stats["escalations_total"] = stats.get("escalations_total", 0) + 1
        # v5.0 negative-cache: record this route failed for the prompt
        prompt_text = ""
        if isinstance(data.get("tool_input"), dict):
            prompt_text = (
                str(data["tool_input"].get("prompt", ""))
                + " " + str(data["tool_input"].get("description", ""))
            )
        if prompt_text and alias:
            cache_record_route_failure(
                prompt_text, alias, "error_recovery"
            )
    if verify_resp and not verify_resp.get("verified"):
        stats["escalations_output_verify"] = stats.get("escalations_output_verify", 0) + 1
        stats["escalations_total"] = stats.get("escalations_total", 0) + 1
        prompt_text = ""
        if isinstance(data.get("tool_input"), dict):
            prompt_text = (
                str(data["tool_input"].get("prompt", ""))
                + " " + str(data["tool_input"].get("description", ""))
            )
        if prompt_text and alias:
            cache_record_route_failure(
                prompt_text, alias, "output_verify"
            )

    save_config(config)

    if verify_resp and not verify_resp.get("verified"):
        opus_id = config["model_registry"]["opus"]["id"]
        out = {
            "escalate": True,
            "reason": verify_resp["reason"],
            "retry_with_model": opus_id,
            "retry_effort": "xhigh",
        }
        sys.stdout.write(json.dumps(out))
        return
    if had_error:
        opus_id = config["model_registry"]["opus"]["id"]
        out = {
            "escalate": True,
            "reason": "error_in_output",
            "retry_with_model": opus_id,
            "retry_effort": "xhigh",
        }
        sys.stdout.write(json.dumps(out))
        return

    # AutoMix-lite confidence-gated escalation (Pattern 3).
    # Cheap heuristic: detect implausible output, advise retry on a
    # stronger tier. Surfaces via additionalContext so Claude itself
    # decides whether to redo the work — no silent retry loop.
    out_conf = compute_output_confidence(out_str, tool_name, had_error, alias)
    threshold = confidence_threshold(config)
    advisory_parts = []
    if out_conf < threshold and alias in ("haiku", "sonnet"):
        next_tier = {"haiku": "sonnet+high", "sonnet": "opus+high"}[alias]
        advisory_parts.append(
            f"smart-router: previous {tool_name} output scored "
            f"{out_conf:.2f} confidence (threshold {threshold:.2f} for "
            f"{config.get('mode','balanced')} mode). "
            f"Consider redoing this step on {next_tier} if the output "
            "looks wrong, sparse, or truncated."
        )
        stats["escalations_output_verify"] = stats.get("escalations_output_verify", 0) + 1
        save_config(config)

    # Pattern 5 — sub-thread distillation hint for verbose Task results.
    # When a subagent returns a long blob, suggest Claude distill it
    # before merging into the supervisor context. Keeps the parent
    # context lean across multi-chunk decompositions.
    if tool_name == "Task" and len(out_str) > 8000:
        approx_tokens = len(out_str) // 4
        advisory_parts.append(
            f"smart-router: Task subagent returned ~{approx_tokens} tokens "
            f"({len(out_str)} chars). Before merging into your reply, distill "
            "to <400 tokens — keep findings + file:line citations, drop "
            "scratch reasoning. Cite the chunk so the user can audit."
        )

    if advisory_parts:
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "\n\n".join(advisory_parts),
            }
        }
        sys.stdout.write(json.dumps(out))
        return
    sys.stdout.write("{}")


def handle_session_end(data: dict) -> None:
    """Bounded calibration. Floor 20 haiku calls; bound delta to ±0.005;
    skip if 7-session moving average diverges (noisy signal)."""
    with config_lock():
        config = load_config()
        session_id = data.get("session_id", "default")
        log = load_session_log(session_id)

        posts = [e for e in log if e.get("phase") == "post"]
        haiku_posts = [e for e in posts if e.get("tier", "").startswith("haiku")]
        haiku_trusted = sum(1 for e in haiku_posts if not e.get("escalated"))
        haiku_escalated = sum(1 for e in haiku_posts if e.get("escalated"))
        total_haiku = haiku_trusted + haiku_escalated
        trust_rate = 0.0
        delta = 0.0
        mode = config.get("mode", "balanced")
        history = config.get("calibration_history", [])
        recent_avg = None

        if total_haiku >= 20:
            trust_rate = haiku_trusted / total_haiku
            recent = [h.get("trust_rate", 0.0) for h in history[-6:]] + [trust_rate]
            recent_avg = sum(recent) / len(recent)
            if abs(recent_avg - trust_rate) > 0.20:
                # noisy single-session signal — skip drift
                pass
            elif trust_rate > 0.92 and mode not in ("fast", "eco"):
                current = config["thresholds"].get("haiku_confidence_min", 0.88)
                config["thresholds"]["haiku_confidence_min"] = max(0.5, current - 0.005)
                delta = -0.005
                sys.stdout.write("smart-router: haiku threshold relaxed\n")
            elif trust_rate < 0.70:
                current = config["thresholds"].get("haiku_confidence_min", 0.88)
                config["thresholds"]["haiku_confidence_min"] = min(0.99, current + 0.005)
                delta = 0.005
                sys.stdout.write("smart-router: haiku threshold tightened\n")

        output_verify_count = sum(
            1 for e in posts if e.get("escalation_reason") in ("error_in_output", "empty_output")
        )
        if output_verify_count > 0 and total_haiku >= 20:
            current = config["thresholds"].get("haiku_confidence_min", 0.88)
            tighten = min(0.005, 0.005 - delta if delta < 0 else 0.005)
            config["thresholds"]["haiku_confidence_min"] = min(0.99, current + tighten)
            delta += tighten

        config.setdefault("calibration_history", []).append({
            "date": datetime.now().isoformat(),
            "mode": mode,
            "trust_rate": trust_rate,
            "adjustment": delta,
            "total_calls": len(posts),
            "total_haiku": total_haiku,
            "moving_avg": recent_avg,
        })
        save_config(config)
        # v6.1 — persist session memory for cross-session continuity
        save_session_memory(session_id)
        sys.stdout.write("smart-router: session calibration complete.\n")


def update_model_registry() -> None:
    """Refresh model IDs from Anthropic API JSON on stdin.
    Only bumps last_model_check when at least one ID actually changed —
    silent no-ops (auth failure, empty response, no newer model) emit
    a clear stderr message and exit 1, so the staleness reminder fires
    next session instead of being suppressed by a misleading timestamp."""
    config = load_config()
    try:
        raw = sys.stdin.read()
        api_resp = json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError):
        api_resp = {}
    before = {a: config["model_registry"][a]["id"]
              for a in ("opus", "sonnet", "haiku")}
    _apply_registry_update(config, api_resp)
    after = {a: config["model_registry"][a]["id"]
             for a in ("opus", "sonnet", "haiku")}
    changed = {a: (before[a], after[a]) for a in before if before[a] != after[a]}

    if not changed:
        sys.stderr.write(
            "smart-router: --update-models ran but no IDs changed.\n"
            "Possible causes: auth failure, empty response, or registry "
            "already current. last_model_check NOT bumped.\n"
        )
        sys.exit(1)

    config["last_model_check"] = datetime.now().isoformat()
    save_config(config)
    diffs = " | ".join(f"{a}: {b}→{c}" for a, (b, c) in changed.items())
    sys.stdout.write(f"smart-router: registry updated — {diffs}\n")


def run_tests() -> None:
    global CONFIG_PATH
    saved_config_path = CONFIG_PATH
    results = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, "PASS" if ok else "FAIL", detail))

    def capture(fn, data) -> dict:
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            fn(data)
        finally:
            sys.stdout = old
        text = buf.getvalue().strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except (ValueError, json.JSONDecodeError):
            return {"_raw": text}

    with tempfile.TemporaryDirectory() as td:
        CONFIG_PATH = Path(td) / "router-config.json"
        atomic_write_json(CONFIG_PATH, _default_config())

        # T01
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"path": "src/index.ts"},
            "session_id": "t01",
        })
        record("T01", "haiku" in out.get("tier_label", "")
               and "effort" not in out, f"out={out}")

        # T02
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"path": "src/auth/login.ts", "content": "x"},
            "session_id": "t02",
        })
        record("T02", "opus" in out.get("tier_label", "")
               and "auth" in out.get("reason", "").lower(), f"out={out}")

        # T03
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "grep -r TODO src/"},
            "session_id": "t03",
        })
        record("T03", "haiku" in out.get("tier_label", ""), f"out={out}")

        # T04
        big = "x" * 5000
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"path": "src/large.ts", "content": big},
            "session_id": "t04",
        })
        record("T04", "opus" in out.get("tier_label", "")
               and out.get("advised_effort") in ("high", "xhigh"), f"out={out}")

        # T05
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "npm test"},
            "session_id": "t05",
        })
        record("T05", "sonnet" in out.get("tier_label", "")
               and out.get("advised_effort") == "medium", f"out={out}")

        # T06
        med = "x" * 2000
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"path": "src/file.ts", "content": med},
            "session_id": "t06",
        })
        record("T06", "sonnet" in out.get("tier_label", "")
               and out.get("advised_effort") == "high", f"out={out}")

        # T07
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {"path": "src/x.ts", "old_string": "a",
                           "new_string": "architecture design patterns review"},
            "session_id": "t07",
        })
        record("T07", "opus" in out.get("tier_label", ""), f"out={out}")

        # T08
        capture(handle_post_tool_use, {
            "hook_event": "PostToolUse",
            "tool_name": "Read",
            "tool_output": "file contents here, no errors",
            "model_used": "claude-haiku-4-5-20251001",
            "effort_used": "none",
            "session_id": "t08",
        })
        cfg = load_config()
        record("T08", cfg["session_stats"]["calls_by_tier"]["haiku_none"] >= 1,
               f"calls={cfg['session_stats']['calls_by_tier']}")

        # T09
        out = capture(handle_post_tool_use, {
            "hook_event": "PostToolUse",
            "tool_name": "Bash",
            "tool_output": "Traceback (most recent call last):\n  File ...",
            "model_used": "claude-haiku-4-5-20251001",
            "effort_used": "none",
            "session_id": "t09",
        })
        record("T09", out.get("escalate") is True, f"out={out}")

        # T10
        capture(handle_post_tool_use, {
            "hook_event": "PostToolUse",
            "tool_name": "Write",
            "tool_output": "wrote file successfully",
            "model_used": "claude-sonnet-4-6",
            "effort_used": "high",
            "session_id": "t10",
        })
        cfg = load_config()
        record("T10", cfg["session_stats"]["calls_by_tier"]["sonnet_high"] >= 1,
               f"calls={cfg['session_stats']['calls_by_tier']}")

        # T11
        capture(handle_post_tool_use, {
            "hook_event": "PostToolUse",
            "tool_name": "Write",
            "tool_output": "refactor complete",
            "model_used": "claude-opus-4-7",
            "effort_used": "xhigh",
            "session_id": "t11",
        })
        cfg = load_config()
        record("T11", cfg["session_stats"]["calls_by_tier"]["opus_xhigh"] >= 1,
               f"calls={cfg['session_stats']['calls_by_tier']}")

        # T12 — 20-call floor: 16 trusted + 4 errored = trust 0.80
        sid = "t12_unique"
        save_session_log(sid, [])
        for _ in range(16):
            capture(handle_post_tool_use, {
                "hook_event": "PostToolUse",
                "tool_name": "Read",
                "tool_output": "clean output, all good",
                "model_used": "claude-haiku-4-5-20251001",
                "effort_used": "none",
                "session_id": sid,
            })
        for _ in range(4):
            capture(handle_post_tool_use, {
                "hook_event": "PostToolUse",
                "tool_name": "Bash",
                "tool_output": "Traceback (most recent call last):\n  File \"a.py\", line 1\nNameError: x",
                "model_used": "claude-haiku-4-5-20251001",
                "effort_used": "none",
                "exit_code": 1,
                "session_id": sid,
            })
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            handle_session_end({"hook_event": "SessionEnd", "session_id": sid})
        finally:
            sys.stdout = old
        cfg = load_config()
        hist = cfg.get("calibration_history", [])
        last = hist[-1] if hist else {}
        record("T12", abs(last.get("trust_rate", 0) - 0.8) < 1e-9
               and "calibration complete" in buf.getvalue().lower(),
               f"hist_last={last}, msg={buf.getvalue().strip()}")

        # T13: Task dispatch — sensitive content to general-purpose blocks
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "description": "fix bug in auth flow",
                "prompt": "Refactor the password hashing logic.",
            },
            "session_id": "t13",
        })
        decision = (out.get("hookSpecificOutput", {})
                       .get("permissionDecision", ""))
        reason = (out.get("hookSpecificOutput", {})
                     .get("permissionDecisionReason", "")).lower()
        record("T13", decision == "ask" and "secure-opus" in reason,
               f"out={out}")

        # T14: Task dispatch — clean recon to recon-haiku, allowed
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "recon-haiku",
                "description": "find usages of foo()",
                "prompt": "Find where foo() is called in src/",
            },
            "session_id": "t14",
        })
        cfg = load_config()
        n_haiku_dispatch = cfg["session_stats"].get("task_dispatches", {}).get(
            "recon-haiku", 0)
        record("T14",
               (out == {} or "permissionDecision" not in str(out))
               and n_haiku_dispatch >= 1,
               f"out={out}, dispatches={cfg['session_stats'].get('task_dispatches')}")

        # T15: SessionStart with no API key + no memory → no crash, no network
        # Clear any session memory from earlier tests so this test isolates
        # the API-key-only-warning path (v6.1 added memory injection which
        # changed the semantic of an empty SessionStart response).
        ph = _project_hash()
        mem_file = _memory_file(ph)
        if mem_file.exists():
            mem_file.unlink()
        old_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            buf = io.StringIO()
            old = sys.stdout
            sys.stdout = buf
            try:
                handle_session_start({"hook_event": "SessionStart",
                                      "session_id": "t15"})
            finally:
                sys.stdout = old
            out_str = buf.getvalue().strip()
            # v6.1: passes if either (a) clean {} OR (b) injected memory
            # but NOT a crash or stale-registry warning
            record("T15",
                   out_str == "{}" or "ATrain session memory" in out_str,
                   f"out={out_str!r}")
        finally:
            if old_key:
                os.environ["ANTHROPIC_API_KEY"] = old_key

        # T16: --update-models (fed via _apply_registry_update directly)
        cfg = load_config()
        fake_resp = {"data": [
            {"id": "claude-opus-4-9"},
            {"id": "claude-opus-4-7"},
            {"id": "claude-sonnet-4-8"},
            {"id": "claude-haiku-4-5-20251001"},
            {"id": "claude-haiku-4-6-20260301"},
        ]}
        _apply_registry_update(cfg, fake_resp)
        record("T16", cfg["model_registry"]["opus"]["id"] == "claude-opus-4-9"
               and cfg["model_registry"]["sonnet"]["id"] == "claude-sonnet-4-8"
               and cfg["model_registry"]["haiku"]["id"] == "claude-haiku-4-6-20260301",
               f"registry={cfg['model_registry']}")

        # T17: detect_multi_faceted — multi-faceted prompt → True
        is_multi, sigs = detect_multi_faceted(
            "Add a webhook handler with HMAC verification and write tests "
            "for it. Also update the README and refactor the auth module "
            "to use the new logger."
        )
        record("T17", is_multi and len(sigs) >= 2,
               f"is_multi={is_multi}, signals={sigs}")

        # T18: detect_multi_faceted — simple prompt → False
        is_multi, sigs = detect_multi_faceted("show me the package.json")
        record("T18", not is_multi, f"is_multi={is_multi}, signals={sigs}")

        # T19: UserPromptSubmit injects decompose suggestion when multi-faceted
        out = capture(handle_user_prompt_submit, {
            "hook_event": "UserPromptSubmit",
            "session_id": "t19_unique",
            "prompt": "build a CRUD API for users with bcrypt password "
                      "hashing, add input validation, write integration "
                      "tests, and update the OpenAPI spec",
        })
        ctx = (out.get("hookSpecificOutput") or {}).get("additionalContext", "")
        record("T19", "multi-faceted" in ctx.lower() or "decompos" in ctx.lower(),
               f"ctx_excerpt={ctx[:140]!r}")

        # T20: _detect_error skips Bash with exit_code=0
        record("T20", _detect_error(
            "grep result: line with Traceback (most recent call last):",
            exit_code=0, tool_name="Bash") is False,
            "Bash exit_code=0 should not flag errors")

        # T21: _detect_error fires on Bash exit_code != 0 with traceback
        record("T21", _detect_error(
            "Traceback (most recent call last):\n  File \"x.py\", line 1\n",
            exit_code=1, tool_name="Bash") is True,
            "Bash exit_code=1 with traceback should flag")

        # T22: _build_sensitive_re respects token boundaries
        rx = _build_sensitive_re(["auth", "api_key"])
        record("T22",
               rx.search("src/auth/login.ts") is not None
               and rx.search("author of the book") is None
               and rx.search("api_keyword variable") is None,
               "boundary regex must not match author/api_keyword")

        # T23: precise mode allows haiku for read-only tools (regression
        # fix from v3.2 — was forcing opus on Read in precise mode)
        precise_cfg = _default_config()
        precise_cfg["accuracy_target"] = 99.9
        atomic_write_json(CONFIG_PATH, precise_cfg)
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"path": "src/index.ts"},
            "session_id": "t23",
        })
        record("T23",
               "haiku" in out.get("tier_label", "")
               and "effort" not in out,
               f"out={out}")

        # T24: classify_to_agent honors routing_tables[mode]
        #      quality mode maps recon → impl-sonnet (not recon-haiku).
        #      Use a pure-recon prompt that triggers no sensitive
        #      phrases (webhook/auth/etc).
        quality_cfg = _default_config()
        quality_cfg["mode"] = "quality"
        quality_cfg["accuracy_target"] = 99.9
        atomic_write_json(CONFIG_PATH, quality_cfg)
        agent = classify_to_agent("find usages of the foo() helper",
                                  quality_cfg)
        record("T24", agent == "impl-sonnet",
               f"got {agent}, expected impl-sonnet")

        # T25: update_model_registry with empty response → exit 1, no bump
        atomic_write_json(CONFIG_PATH, _default_config())
        original_check = load_config()["last_model_check"]
        old_stdin = sys.stdin
        sys.stdin = io.StringIO("")  # empty stdin
        old_stderr = sys.stderr
        sys.stderr = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        exit_code = 0
        try:
            update_model_registry()
        except SystemExit as e:
            exit_code = e.code or 0
        finally:
            sys.stdin = old_stdin
            sys.stderr = old_stderr
            sys.stdout = old_stdout
        after = load_config()["last_model_check"]
        record("T25",
               exit_code == 1 and after == original_check,
               f"exit_code={exit_code}, before={original_check}, after={after}")

        # T26: config_lock survives caller-raised exception cleanly
        atomic_write_json(CONFIG_PATH, _default_config())
        raised = False
        try:
            with config_lock():
                raise OSError("simulated FS error during caller body")
        except OSError:
            raised = True
        # second use must work — not contaminated by previous exception
        worked = False
        try:
            with config_lock():
                worked = True
        except Exception:
            worked = False
        record("T26", raised and worked,
               f"raised={raised}, second_use_worked={worked}")

        # T27: compute_output_confidence on plausible vs implausible outputs
        c_empty = compute_output_confidence("", "Read", False, "haiku")
        c_short = compute_output_confidence("ok", "Read", False, "haiku")
        c_good = compute_output_confidence(
            "found 3 matches:\n  src/a.ts:12 TODO\n  src/b.ts:5 TODO\n",
            "Grep", False, "haiku")
        record("T27",
               c_empty < 0.30 and c_short < 0.70 and c_good > 0.85,
               f"empty={c_empty}, short={c_short}, good={c_good}")

        # T28: post-hook injects confidence advisory on weak haiku output
        atomic_write_json(CONFIG_PATH, _default_config())
        save_session_log("t28", [])
        out = capture(handle_post_tool_use, {
            "hook_event": "PostToolUse",
            "tool_name": "Read",
            "tool_output": "x",  # implausibly short
            "model_used": "claude-haiku-4-5-20251001",
            "effort_used": "none",
            "session_id": "t28",
        })
        ctx = (out.get("hookSpecificOutput") or {}).get("additionalContext", "")
        record("T28",
               "confidence" in ctx.lower() and ("sonnet" in ctx.lower()
                                                or "opus" in ctx.lower()),
               f"ctx={ctx[:140]!r}")

        # T29: post-hook injects distillation advisory on verbose Task output
        save_session_log("t29", [])
        out = capture(handle_post_tool_use, {
            "hook_event": "PostToolUse",
            "tool_name": "Task",
            "tool_output": "X" * 9000,
            "model_used": "claude-sonnet-4-6",
            "effort_used": "high",
            "session_id": "t29",
        })
        ctx = (out.get("hookSpecificOutput") or {}).get("additionalContext", "")
        record("T29",
               "distill" in ctx.lower() and "400" in ctx,
               f"ctx={ctx[:160]!r}")

        # T30: cache miss returns None
        atomic_write_json(CONFIG_PATH, _default_config())
        # Force fresh cache db in temp dir
        cache_db = CONFIG_PATH.parent / "router-cache.sqlite"
        if cache_db.exists():
            cache_db.unlink()
        miss = cache_get("Read", {"path": "fresh.ts"})
        record("T30", miss is None, f"miss={miss}")

        # T31: cache put then get returns hit with output
        cache_put("Read", {"path": "cached.ts"},
                  "file content here", session_id="t31")
        hit = cache_get("Read", {"path": "cached.ts"})
        record("T31",
               hit is not None and hit.get("output") == "file content here"
               and hit.get("age_sec", 999) < 5,
               f"hit={hit}")

        # T32: non-cacheable tool returns None even with same path
        cache_put("Bash", {"command": "echo x"}, "x", session_id="t32")
        bash_hit = cache_get("Bash", {"command": "echo x"})
        record("T32", bash_hit is None, f"bash_hit={bash_hit}")

        # T33: PreToolUse on duplicate Read injects cache advisory
        save_session_log("t33", [])
        cache_put("Read", {"path": "/etc/hosts"},
                  "127.0.0.1 localhost", session_id="t33")
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"path": "/etc/hosts"},
            "session_id": "t33",
        })
        ctx = (out.get("hookSpecificOutput") or {}).get("additionalContext", "")
        record("T33",
               "duplicate" in ctx.lower() and "127.0.0.1" in ctx,
               f"ctx={ctx[:200]!r}")

        # T34 v4.0 honesty: model_override + effort fields are GONE from
        # PreToolUse output. Runtime ignored them anyway. Replaced by
        # tier_label / advised_model / advised_effort which are clearly
        # marked as analytics-only.
        atomic_write_json(CONFIG_PATH, _default_config())
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"path": "src/index.ts"},
            "session_id": "t34",
        })
        record("T34",
               "model_override" not in out
               and "effort" not in out
               and "tier_label" in out
               and "advised_model" in out,
               f"keys={sorted(out.keys())}")

        # T35 v4.0 honest accounting: Task dispatches credit
        # real_savings_usd; main-session calls credit advisory_savings_usd
        # only. The two ledgers stay separate.
        atomic_write_json(CONFIG_PATH, _default_config())
        capture(handle_post_tool_use, {
            "hook_event": "PostToolUse",
            "tool_name": "Read",  # main session call
            "tool_output": "x" * 200,
            "model_used": "claude-haiku-4-5-20251001",
            "effort_used": "none",
            "session_id": "t35a",
        })
        cfg = load_config()
        advisory_after_main = cfg["session_stats"].get("advisory_calls", 0)
        real_after_main = cfg["session_stats"].get("real_subagent_calls", 0)

        capture(handle_post_tool_use, {
            "hook_event": "PostToolUse",
            "tool_name": "Task",  # subagent dispatch
            "tool_output": "x" * 200,
            "model_used": "claude-haiku-4-5-20251001",
            "effort_used": "none",
            "session_id": "t35b",
        })
        cfg = load_config()
        record("T35",
               advisory_after_main == 1 and real_after_main == 0
               and cfg["session_stats"].get("real_subagent_calls", 0) == 1
               and cfg["session_stats"].get("real_savings_usd", 0.0) > 0,
               f"after main: advisory={advisory_after_main}, "
               f"real={real_after_main}; after task: "
               f"advisory={cfg['session_stats'].get('advisory_calls')}, "
               f"real={cfg['session_stats'].get('real_subagent_calls')}, "
               f"real_savings=${cfg['session_stats'].get('real_savings_usd', 0):.5f}")

        # T36 v4.0 eco mode: PreToolUse on Read in eco injects
        # subagent-dispatch nudge in additionalContext.
        eco_cfg = _default_config()
        eco_cfg["mode"] = "eco"
        atomic_write_json(CONFIG_PATH, eco_cfg)
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Grep",
            "tool_input": {"pattern": "TODO"},
            "session_id": "t36",
        })
        ctx = (out.get("hookSpecificOutput") or {}).get("additionalContext", "")
        record("T36",
               "eco mode" in ctx.lower()
               and "task(" in ctx.lower()
               and "recon-haiku" in ctx,
               f"ctx_excerpt={ctx[:240]!r}")

        # T37 v5.0 negative-cache: record + check route failure
        atomic_write_json(CONFIG_PATH, _default_config())
        # ensure clean cache db for this test
        cache_db = CONFIG_PATH.parent / "router-cache.sqlite"
        if cache_db.exists():
            cache_db.unlink()
        prompt = "find usages of foo() helper"
        cache_record_route_failure(prompt, "recon-haiku", "output_verify")
        had_failure = cache_check_route_failure(prompt, "recon-haiku")
        no_failure_for_other = cache_check_route_failure(
            "totally different unrelated prompt about pizza", "recon-haiku"
        )
        record("T37",
               had_failure and not no_failure_for_other,
               f"failure_recorded={had_failure}, "
               f"unrelated={no_failure_for_other}")

        # T38 v5.0 classify_to_agent upshifts when route_failures matches
        cache_record_route_failure(
            "find todos in src", "recon-haiku", "output_verify"
        )
        balanced_cfg = _default_config()
        balanced_cfg["mode"] = "balanced"
        agent = classify_to_agent("find todos in src", balanced_cfg)
        record("T38",
               agent == "impl-sonnet",
               f"got {agent}, expected impl-sonnet (upshifted from "
               f"recon-haiku due to negative cache)")

        # T39 v5.0 eco + force_subagent_recon: hook returns permissionDecision
        # 'ask' on Read with Task spawn suggestion
        eco_force = _default_config()
        eco_force["mode"] = "eco"
        eco_force["force_subagent_recon"] = True
        atomic_write_json(CONFIG_PATH, eco_force)
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"path": "src/index.ts"},
            "session_id": "t39",
        })
        h = out.get("hookSpecificOutput", {}) or {}
        decision = h.get("permissionDecision", "")
        reason = (h.get("permissionDecisionReason", "") or "").lower()
        record("T39",
               decision == "ask"
               and ("task(" in reason or "subagent_type" in reason)
               and "recon-haiku" in reason,
               f"decision={decision}, reason={reason[:160]!r}")

        # T40 v6.0 Bash output compactor (rtk pattern, native)
        # Synthetic noisy output: ANSI codes, repeated lines, blank lines
        noisy = (
            "\x1b[32m[2026-05-08T22:00:00Z]\x1b[0m starting build\n"
            "\n\n\n"
            + "\n".join(["WARN: deprecated foo()"] * 50)
            + "\n\n"
            + "real signal: 3 errors found\n"
        )
        compacted = compact_bash_output(noisy)
        record("T40",
               len(compacted) < len(noisy) // 2
               and "duplicate lines collapsed" in compacted
               and "real signal" in compacted,
               f"original={len(noisy)} compacted={len(compacted)} "
               f"sample={compacted[:200]!r}")

        # T41 v6.0 tool_input compactor (claw-compactor pattern)
        bloated = {"path": "src/x.ts", "content": "x" * 20000}
        compacted_in, was_compacted = compact_tool_input(bloated, max_field_chars=4000)
        record("T41",
               was_compacted
               and "[content truncated" in compacted_in["content"]
               and len(compacted_in["content"]) < 5000
               and compacted_in["path"] == "src/x.ts",
               f"was_compacted={was_compacted}, "
               f"new_len={len(compacted_in['content'])}")

        # T42 v6.0 eco mode injects terse-output style guidance
        eco_terse = _default_config()
        eco_terse["mode"] = "eco"
        atomic_write_json(CONFIG_PATH, eco_terse)
        save_session_log("t42", [])
        out = capture(handle_user_prompt_submit, {
            "hook_event": "UserPromptSubmit",
            "session_id": "t42",
            "prompt": "build me a CRUD API for users",
        })
        ctx = (out.get("hookSpecificOutput") or {}).get("additionalContext", "")
        record("T42",
               "terse" in ctx.lower()
               and "filler" in ctx.lower()
               and ("code blocks" in ctx.lower()
                    or "commit" in ctx.lower()
                    or "security" in ctx.lower()),
               f"ctx_excerpt={ctx[:200]!r}")

        # T43 v6.1 session memory persistence (claude-mem native pattern)
        # Synthesize a fake session log, save digest, reload it.
        sid = "t43_session"
        save_session_log(sid, [])
        # populate session log with mixed entries
        for i in range(5):
            log = load_session_log(sid)
            log.append({
                "phase": "pre", "tool": "Read",
                "tier": "haiku+none", "escalated": False,
                "escalation_reason": "", "had_error": False,
                "ts": datetime.now().isoformat(),
            })
            log.append({
                "phase": "post", "tool": "Read",
                "tier": "haiku+none", "had_error": False,
                "escalated": False, "escalation_reason": "",
                "ts": datetime.now().isoformat(),
            })
            save_session_log(sid, log)
        # add an escalation entry
        log = load_session_log(sid)
        log.append({
            "phase": "pre", "tool": "Write",
            "tier": "opus+xhigh", "escalated": True,
            "escalation_reason": "sensitive: auth",
            "had_error": False, "ts": datetime.now().isoformat(),
        })
        save_session_log(sid, log)
        # ensure clean memory file for this project hash
        ph = _project_hash()
        mem_file = _memory_file(ph)
        if mem_file.exists():
            mem_file.unlink()
        save_session_memory(sid)
        record("T43",
               mem_file.exists() and len(mem_file.read_text()) > 50,
               f"memory file={mem_file}, "
               f"size={mem_file.stat().st_size if mem_file.exists() else 0}")

        # T44 v6.1 SessionStart injects loaded memory as additionalContext
        out = capture(handle_session_start, {
            "hook_event": "SessionStart",
            "session_id": "t44_fresh",
        })
        ctx = (out.get("hookSpecificOutput") or {}).get("additionalContext", "")
        record("T44",
               "ATrain session memory" in ctx
               and "calls" in ctx,
               f"ctx_excerpt={ctx[:240]!r}")

        # T45 v6.2 codebase indexer — index a temp dir with sample files
        with tempfile.TemporaryDirectory() as proj_td:
            proj_path = Path(proj_td)
            (proj_path / "module_a.py").write_text(
                "def hello_world():\n    return 'hi'\n\n"
                "class FooHandler:\n    pass\n\n"
                "def parse_config(path):\n    pass\n"
            )
            (proj_path / "ui.tsx").write_text(
                "export function MyButton(props) { return null; }\n"
                "class Widget {}\n"
                "const handleClick = (e) => console.log(e);\n"
            )
            (proj_path / "main.go").write_text(
                "package main\n\nfunc Main() {}\n\n"
                "func processRequest(r *Request) error { return nil }\n"
            )
            old_cwd = os.getcwd()
            try:
                os.chdir(proj_td)
                result = index_project()
                # lookups must run in same cwd — _project_hash uses cwd
                hits_hello = lookup_symbol("hello_world")
                hits_button = lookup_symbol("MyButton")
                hits_main = lookup_symbol("Main")
            finally:
                os.chdir(old_cwd)
        record("T45",
               result.get("n_files_indexed", 0) >= 3
               and result.get("n_symbols", 0) >= 6
               and len(hits_hello) >= 1
               and any(h["name"] == "MyButton" for h in hits_button)
               and len(hits_main) >= 1,
               f"result={result}, "
               f"hello={len(hits_hello)}, button={len(hits_button)}, "
               f"main={len(hits_main)}")

        # T46 v6.2 PreToolUse Grep on indexed symbol injects advisory
        # First seed the index for symbol "MyButton" in the live db
        try:
            conn = _index_conn()
            try:
                conn.execute(
                    "INSERT INTO symbols "
                    "(path, name, kind, signature, line, indexed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    ("ui.tsx", "MyButton", "function",
                     "export function MyButton(props)", 1, time.time()),
                )
            finally:
                conn.close()
        except (sqlite3.Error, OSError):
            pass
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Grep",
            "tool_input": {"pattern": "MyButton"},
            "session_id": "t46",
        })
        ctx = (out.get("hookSpecificOutput") or {}).get("additionalContext", "")
        record("T46",
               "ATrain index" in ctx and "MyButton" in ctx
               and ("ui.tsx:1" in ctx or "ui.tsx" in ctx),
               f"ctx_excerpt={ctx[:240]!r}")

        # T47 v6.3 MoA-Lite advisory in quality mode + high-stakes prompt
        quality_cfg = _default_config()
        quality_cfg["mode"] = "quality"
        atomic_write_json(CONFIG_PATH, quality_cfg)
        save_session_log("t47", [])
        # high-stakes prompt: contains "production" + complex framing
        out = capture(handle_user_prompt_submit, {
            "hook_event": "UserPromptSubmit",
            "session_id": "t47",
            "prompt": ("we need to choose between event-driven and "
                       "polling architecture for the production "
                       "deployment of the new analytics service. "
                       "what's the best tradeoff for our scale?"),
        })
        ctx = (out.get("hookSpecificOutput") or {}).get("additionalContext", "")
        record("T47",
               "/atrain-moa" in ctx and "high-stakes" in ctx.lower(),
               f"ctx_excerpt={ctx[:240]!r}")

        # T48: simple quality-mode prompt should NOT trigger MoA
        save_session_log("t48", [])
        out = capture(handle_user_prompt_submit, {
            "hook_event": "UserPromptSubmit",
            "session_id": "t48",
            "prompt": "find foo() in src",
        })
        ctx = (out.get("hookSpecificOutput") or {}).get("additionalContext", "")
        record("T48",
               "/atrain-moa" not in ctx,
               f"ctx_excerpt={ctx[:240]!r}")

        # T49 v6.4 rtk-pattern bash pre-rewriter — common cmds rewrite
        # ls → ls -1 + head, pytest → -q --no-header, git log → oneline
        ls_new, ls_done = rewrite_bash_command("ls")
        pytest_new, pytest_done = rewrite_bash_command("pytest")
        gitlog_new, gitlog_done = rewrite_bash_command("git log")
        gitstatus_new, gitstatus_done = rewrite_bash_command("git status")
        # commands NOT in our rewrite list should pass through unchanged
        echo_new, echo_done = rewrite_bash_command("echo hello")
        record("T49",
               ls_done and "1" in ls_new
               and pytest_done and "-q" in pytest_new
               and gitlog_done and "oneline" in gitlog_new
               and gitstatus_done and "short" in gitstatus_new
               and not echo_done,
               f"ls={ls_new!r}, pytest={pytest_new!r}, "
               f"gitlog={gitlog_new!r}, gitstatus={gitstatus_new!r}, "
               f"echo_done={echo_done}")

        # T50 v6.4 PreToolUse on Bash with rewritable command emits
        # updatedInput with the new command so the runtime executes it
        atomic_write_json(CONFIG_PATH, _default_config())
        save_session_log("t50", [])
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "pytest"},
            "session_id": "t50",
        })
        h = out.get("hookSpecificOutput", {}) or {}
        updated = h.get("updatedInput", {}) or {}
        new_cmd = updated.get("command", "")
        ctx = h.get("additionalContext", "")
        record("T50",
               "-q" in new_cmd
               and "rewrote bash command" in ctx,
               f"updated_cmd={new_cmd!r}, ctx_excerpt={ctx[:200]!r}")

        # T51 v6.5 caveman intensity full integration
        # eco mode auto-fires "full" — should include persistence, rules,
        # pattern, auto-clarity, boundaries sections
        eco_cfg = _default_config()
        eco_cfg["mode"] = "eco"
        atomic_write_json(CONFIG_PATH, eco_cfg)
        save_session_log("t51_eco", [])
        out = capture(handle_user_prompt_submit, {
            "hook_event": "UserPromptSubmit",
            "session_id": "t51_eco",
            "prompt": "build a small helper",
        })
        ctx = (out.get("hookSpecificOutput") or {}).get("additionalContext", "")
        eco_full_caveman = (
            "caveman mode ACTIVE" in ctx
            and "PERSISTENCE" in ctx
            and "RULES" in ctx
            and "PATTERN" in ctx
            and "AUTO-CLARITY" in ctx
            and "BOUNDARIES" in ctx
        )

        # ultra intensity adds the ULTRA EXTRA section
        ultra_cfg = _default_config()
        ultra_cfg["caveman_intensity"] = "ultra"
        atomic_write_json(CONFIG_PATH, ultra_cfg)
        save_session_log("t51_ultra", [])
        out = capture(handle_user_prompt_submit, {
            "hook_event": "UserPromptSubmit",
            "session_id": "t51_ultra",
            "prompt": "build a small helper",
        })
        ctx_ultra = (out.get("hookSpecificOutput") or {}).get("additionalContext", "")
        ultra_active = "ULTRA EXTRA" in ctx_ultra and "Abbreviate" in ctx_ultra

        # off intensity (None) and balanced mode → no caveman injection
        off_cfg = _default_config()
        off_cfg["mode"] = "balanced"
        off_cfg["caveman_intensity"] = None
        atomic_write_json(CONFIG_PATH, off_cfg)
        save_session_log("t51_off", [])
        out = capture(handle_user_prompt_submit, {
            "hook_event": "UserPromptSubmit",
            "session_id": "t51_off",
            "prompt": "build a small helper",
        })
        ctx_off = (out.get("hookSpecificOutput") or {}).get("additionalContext", "")
        no_caveman = "caveman mode" not in ctx_off.lower()

        record("T51",
               eco_full_caveman and ultra_active and no_caveman,
               f"eco_full={eco_full_caveman}, ultra={ultra_active}, "
               f"off_clean={no_caveman}")

    CONFIG_PATH = saved_config_path

    passed = sum(1 for _, s, _ in results if s == "PASS")
    sys.stdout.write("smart-router test results\n")
    sys.stdout.write("=" * 50 + "\n")
    for name, status, detail in results:
        line = f"  {name}: {status}"
        if status == "FAIL":
            line += f"  [{detail}]"
        sys.stdout.write(line + "\n")
    sys.stdout.write("=" * 50 + "\n")
    sys.stdout.write(f"  {passed}/{len(results)} tests passed\n")
    if passed != len(results):
        sys.exit(1)


def print_rules() -> None:
    """Dump every classification rule the hook applies. Reflects what
    classify_task and hard_escalation do today — pair with --lint-skill
    to verify SKILL.md mirrors the same set."""
    sys.stdout.write("=== smart-router classification rules ===\n\n")
    sys.stdout.write("OPUS keywords (force opus tier):\n  ")
    sys.stdout.write(", ".join(OPUS_KEYWORDS) + "\n\n")
    sys.stdout.write("API keywords (force sonnet+high or opus in precise):\n  ")
    sys.stdout.write(", ".join(API_KEYWORDS) + "\n\n")
    sys.stdout.write("Boilerplate strong (force sonnet+medium):\n  ")
    sys.stdout.write(", ".join(BOILERPLATE_STRONG) + "\n\n")
    sys.stdout.write("Boilerplate weak (need anchor co-occurrence):\n  ")
    sys.stdout.write(", ".join(BOILERPLATE_WEAK) + "\n  anchors: ")
    sys.stdout.write(", ".join(BOILERPLATE_ANCHORS) + "\n\n")
    sys.stdout.write("User phrases (force opus xhigh):\n  ")
    sys.stdout.write(", ".join(USER_PHRASES) + "\n\n")
    sys.stdout.write("Manifest files (force opus xhigh):\n  ")
    sys.stdout.write(", ".join(MANIFEST_FILES) + "\n\n")
    sys.stdout.write("Tool-name + length rules:\n")
    sys.stdout.write("  Read/LS/Glob with length < 300        → haiku+none\n")
    sys.stdout.write("  Grep with length < 150                 → haiku+none\n")
    sys.stdout.write("  WebSearch with length < 100            → haiku+none\n")
    sys.stdout.write("  Bash starting with grep/ls/find/cat/echo/pwd/wc/head/tail/diff/stat/file → haiku+none\n")
    sys.stdout.write("  Write/Edit/MultiEdit length < 1500    → sonnet+medium\n")
    sys.stdout.write("  Write/Edit/MultiEdit 1500-3999        → sonnet+high\n")
    sys.stdout.write("  Write/Edit/MultiEdit length >= 4000   → opus+high\n")
    sys.stdout.write("  paths >= 3                             → opus+high\n")
    sys.stdout.write("  paths > 3 (multi-file)                 → opus+xhigh (escalation)\n")


def lint_skill(skill_path: Path = None) -> int:
    """Verify SKILL.md mentions every keyword classify_task uses.
    Returns exit code: 0 = clean, 1 = drift detected."""
    if skill_path is None:
        candidates = [
            # v4.1+ ATrain branding
            ROOT / "skills" / "atrain" / "SKILL.md",
            Path.home() / ".claude" / "skills" / "atrain" / "SKILL.md",
            # legacy paths kept for back-compat
            ROOT / "skills" / "smart-router" / "SKILL.md",
            Path.home() / ".claude" / "skills" / "smart-router" / "SKILL.md",
        ]
        skill_path = next((c for c in candidates if c.exists()), None)
    if skill_path is None or not skill_path.exists():
        sys.stdout.write("smart-router lint: SKILL.md not found\n")
        return 1
    text = skill_path.read_text(encoding="utf-8").lower()
    issues = []
    for kw in OPUS_KEYWORDS:
        if kw not in text:
            issues.append(f"OPUS keyword '{kw}' missing from SKILL.md")
    for kw in API_KEYWORDS:
        if kw not in text and kw not in ("endpoints", "routes"):
            issues.append(f"API keyword '{kw}' missing from SKILL.md")
    for kw in BOILERPLATE_STRONG:
        if kw not in text:
            issues.append(f"Boilerplate-strong '{kw}' missing from SKILL.md")
    if issues:
        sys.stdout.write(
            f"smart-router lint: {len(issues)} drift issues\n"
        )
        for i in issues[:20]:
            sys.stdout.write(f"  - {i}\n")
        return 1
    sys.stdout.write("smart-router lint: SKILL.md mirrors classify_task. OK.\n")
    return 0


def health_check() -> int:
    """Comprehensive reliability audit. Returns exit code."""
    sys.stdout.write("=== smart-router health check ===\n\n")
    issues = []

    # 1. Config integrity
    sys.stdout.write("[1/6] config integrity\n")
    try:
        cfg = load_config()
        required = ("model_registry", "thresholds", "agent_registry",
                    "routing_tables", "session_stats")
        missing = [k for k in required if k not in cfg]
        if missing:
            issues.append(f"config missing keys: {missing}")
            sys.stdout.write(f"  FAIL — missing: {missing}\n")
        else:
            sys.stdout.write(f"  OK — version={cfg.get('version', '?')}, "
                             f"mode={cfg.get('mode', '?')}\n")
    except Exception as e:
        issues.append(f"config load failed: {e}")
        sys.stdout.write(f"  FAIL — {e}\n")

    # 2. Lock acquisition
    sys.stdout.write("[2/6] config_lock acquisition\n")
    try:
        with config_lock():
            pass
        sys.stdout.write("  OK\n")
    except Exception as e:
        issues.append(f"lock acquisition failed: {e}")
        sys.stdout.write(f"  FAIL — {e}\n")

    # 3. Routing decision smoke-test
    sys.stdout.write("[3/6] routing decision smoke-test\n")
    try:
        cfg2 = load_config()
        decision = classify_task("Read", {"path": "x.ts"}, cfg2)
        if decision.get("model_alias") == "haiku":
            sys.stdout.write("  OK — Read → haiku\n")
        else:
            issues.append(f"routing regression: Read returned {decision}")
            sys.stdout.write(f"  FAIL — Read returned {decision}\n")
    except Exception as e:
        issues.append(f"classify_task error: {e}")
        sys.stdout.write(f"  FAIL — {e}\n")

    # 4. SKILL.md drift lint
    sys.stdout.write("[4/6] SKILL.md drift lint\n")
    lint_buf = io.StringIO()
    saved_stdout = sys.stdout
    sys.stdout = lint_buf
    try:
        lint_code = lint_skill()
    except SystemExit as e:
        lint_code = e.code or 0
    finally:
        sys.stdout = saved_stdout
    if lint_code == 0:
        sys.stdout.write("  OK — SKILL.md mirrors classify_task\n")
    else:
        issues.append("SKILL.md drift detected")
        sys.stdout.write(f"  FAIL — {lint_buf.getvalue().strip()}\n")

    # 5. Test suite
    sys.stdout.write("[5/6] test suite\n")
    test_buf = io.StringIO()
    saved_stdout = sys.stdout
    sys.stdout = test_buf
    try:
        run_tests()
        test_code = 0
    except SystemExit as e:
        test_code = e.code or 0
    finally:
        sys.stdout = saved_stdout
    test_output = test_buf.getvalue()
    last_line = test_output.strip().splitlines()[-1] if test_output.strip() else ""
    if test_code == 0 and "passed" in last_line:
        sys.stdout.write(f"  OK — {last_line.strip()}\n")
    else:
        issues.append(f"test failure: {last_line}")
        sys.stdout.write(f"  FAIL — {last_line}\n")

    # 6. Stats summary from real session data
    sys.stdout.write("[6/6] real session stats summary\n")
    try:
        cfg3 = load_config()
        s = cfg3.get("session_stats", {})
        total = s.get("total_calls", 0)
        cost = s.get("estimated_cost_usd", 0.0)
        baseline = s.get("baseline_opus_xhigh_cost_usd", 0.0)
        saved = baseline - cost if baseline > cost else 0.0
        pct = (100 * saved / baseline) if baseline > 0 else 0.0
        sys.stdout.write(f"  total calls: {total}\n")
        sys.stdout.write(f"  cost actual:    ${cost:.4f}\n")
        sys.stdout.write(f"  cost baseline:  ${baseline:.4f}\n")
        sys.stdout.write(f"  saved:          ${saved:.4f} ({pct:.1f}%)\n")
    except Exception as e:
        issues.append(f"stats summary failed: {e}")
        sys.stdout.write(f"  FAIL — {e}\n")

    sys.stdout.write("\n" + "=" * 50 + "\n")
    if issues:
        sys.stdout.write(f"  HEALTH: DEGRADED — {len(issues)} issue(s)\n")
        for i in issues:
            sys.stdout.write(f"    - {i}\n")
        return 1
    sys.stdout.write("  HEALTH: GREEN — all checks passed\n")
    return 0


def main() -> None:
    try:
        if "--update-models" in sys.argv:
            update_model_registry()
            return
        if "--test" in sys.argv:
            run_tests()
            return
        if "--print-rules" in sys.argv:
            print_rules()
            return
        if "--lint-skill" in sys.argv:
            sys.exit(lint_skill())
        if "--health-check" in sys.argv:
            sys.exit(health_check())
        if "--cache-stats" in sys.argv:
            stats = cache_stats_summary()
            sys.stdout.write("=== smart-router cache stats ===\n")
            for k, v in stats.items():
                if isinstance(v, float):
                    sys.stdout.write(f"  {k}: {v:.3f}\n")
                else:
                    sys.stdout.write(f"  {k}: {v}\n")
            return
        if "--index" in sys.argv:
            # Optional second arg: path to index (defaults to cwd)
            root = None
            for i, arg in enumerate(sys.argv):
                if arg == "--index" and i + 1 < len(sys.argv):
                    candidate = sys.argv[i + 1]
                    if not candidate.startswith("--"):
                        root = candidate
            sys.stdout.write("=== ATrain codebase indexer ===\n")
            sys.stdout.write(f"Indexing {root or os.getcwd()}...\n")
            result = index_project(root)
            for k, v in result.items():
                sys.stdout.write(f"  {k}: {v}\n")
            return
        if "--index-status" in sys.argv:
            sys.stdout.write("=== ATrain index status ===\n")
            for k, v in index_status().items():
                sys.stdout.write(f"  {k}: {v}\n")
            return
        if "--lookup" in sys.argv:
            for i, arg in enumerate(sys.argv):
                if arg == "--lookup" and i + 1 < len(sys.argv):
                    sym = sys.argv[i + 1]
                    sys.stdout.write(f"=== ATrain symbol lookup: {sym} ===\n")
                    for r in lookup_symbol(sym):
                        sys.stdout.write(
                            f"  {r['path']}:{r['line']}  {r['kind']}  "
                            f"{r['signature']}\n"
                        )
                    return
            return
        try:
            is_tty = sys.stdin.isatty()
        except (OSError, ValueError):
            is_tty = True
        if is_tty:
            run_tests()
            return
        raw = sys.stdin.read()
        if not raw.strip():
            run_tests()
            return
        try:
            data = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            sys.stdout.write("{}")
            return
        event = data.get("hook_event", "") or data.get("hook_event_name", "")
        if event == "PreToolUse":
            handle_pre_tool_use(data)
        elif event == "PostToolUse":
            handle_post_tool_use(data)
        elif event == "UserPromptSubmit":
            handle_user_prompt_submit(data)
        elif event == "SessionStart":
            handle_session_start(data)
        elif event == "SessionEnd":
            handle_session_end(data)
        else:
            sys.stdout.write("{}")
    except SystemExit:
        raise
    except Exception:
        try:
            sys.stdout.write("{}")
        except Exception:
            pass
        sys.exit(0)


if __name__ == "__main__":
    main()

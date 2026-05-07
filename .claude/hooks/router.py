#!/usr/bin/env python3
"""smart-router: dynamic model + effort selector for Claude Code.

Stdlib only. Never crashes — wraps everything and returns {} on error.
Atomic file writes via .tmp + os.replace. Hook latency target <50ms.
"""
import contextlib
import fcntl
import io
import json
import os
import re
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
    """Per-preset acceptance threshold for output confidence."""
    mode = config.get("mode", "balanced")
    return {"eco": 0.55, "balanced": 0.75,
            "quality": 0.92, "precise": 0.95}.get(mode, 0.75)


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
    take effect on Task dispatches (not just per-tool-call routing)."""
    text = full_text.lower()
    mode = config.get("mode", "balanced")
    table = config.get("routing_tables", {}).get(mode, {})

    def via_table(tier: str, fallback: str) -> str:
        return table.get(tier, fallback)

    if any(kw in text for kw in config.get("hard_escalation_keywords", [])):
        return via_table("sensitive", "secure-opus")
    arch_kw = ("architecture", "design pattern", "refactor entire",
               "redesign", "bottleneck", "optimize", "review all",
               "performance optimization", "system design")
    if any(k in text for k in arch_kw):
        return via_table("architecture", "architect-opus")
    api_kw = ("endpoint", " route", "api integration", "third-party",
              "http handler", "rest api", "graphql")
    if any(k in text for k in api_kw):
        return via_table("api", "api-sonnet")
    recon_kw = ("find ", "where is", "list files", "search for",
                "look up", "show me", "explore", "grep ", "locate")
    write_kw = ("implement", "write a", "build a", "fix the",
                "edit ", "modify", "refactor ", "add a", "create a")
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
    """No network. Bundled-tokens-only. Manual refresh via --update-models."""
    config = load_config()
    last_check = config.get("last_model_check", "")
    try:
        last_dt = datetime.fromisoformat(last_check)
        age_hours = (datetime.now() - last_dt).total_seconds() / 3600.0
    except (ValueError, TypeError):
        age_hours = 999.0
    if age_hours > 24 * 30:
        sys.stdout.write(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": (
                    "smart-router: model registry was last refreshed "
                    f"{int(age_hours/24)} days ago. To pick up newer "
                    "Anthropic models, run from a shell with "
                    "ANTHROPIC_API_KEY set:\n"
                    "  curl -s https://api.anthropic.com/v1/models "
                    "-H \"x-api-key: $ANTHROPIC_API_KEY\" "
                    "-H \"anthropic-version: 2023-06-01\" | "
                    "python3 .claude/hooks/router.py --update-models"
                ),
            }
        }))
        return
    sys.stdout.write("{}")


def handle_user_prompt_submit(data: dict) -> None:
    """Hybrid: first prompt → suggest preset; structurally multi-faceted
    prompt → suggest decompose. Both run silently as advisory context."""
    config = load_config()
    session_id = data.get("session_id", "default")
    prompt = str(data.get("prompt") or data.get("user_prompt") or "")
    log = load_session_log(session_id)
    is_first = not any(e.get("phase") == "pre" for e in log)
    mode = config.get("mode", "balanced")
    decompose_on = bool(config.get("decompose_enabled", False))
    is_multi, signals = detect_multi_faceted(prompt)

    parts = []
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

    advice = (
        f"smart-router: {model_alias}{effort_text} "
        f"({full_id}) — {reason} | conf={confidence:.2f}"
    )
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "additionalContext": advice,
        },
        "model_override": full_id,
        "reason": reason,
        "tier_label": tier_label,
        "confidence": round(confidence, 3),
    }
    if model_alias != "haiku":
        output["effort"] = effort

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

    if had_error:
        stats["escalations_error_recovery"] = stats.get("escalations_error_recovery", 0) + 1
        stats["escalations_total"] = stats.get("escalations_total", 0) + 1
    if verify_resp and not verify_resp.get("verified"):
        stats["escalations_output_verify"] = stats.get("escalations_output_verify", 0) + 1
        stats["escalations_total"] = stats.get("escalations_total", 0) + 1

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
        record("T01", "haiku" in out.get("model_override", "")
               and "effort" not in out, f"out={out}")

        # T02
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"path": "src/auth/login.ts", "content": "x"},
            "session_id": "t02",
        })
        record("T02", "opus" in out.get("model_override", "")
               and "auth" in out.get("reason", "").lower(), f"out={out}")

        # T03
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "grep -r TODO src/"},
            "session_id": "t03",
        })
        record("T03", "haiku" in out.get("model_override", ""), f"out={out}")

        # T04
        big = "x" * 5000
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"path": "src/large.ts", "content": big},
            "session_id": "t04",
        })
        record("T04", "opus" in out.get("model_override", "")
               and out.get("effort") in ("high", "xhigh"), f"out={out}")

        # T05
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "npm test"},
            "session_id": "t05",
        })
        record("T05", "sonnet" in out.get("model_override", "")
               and out.get("effort") == "medium", f"out={out}")

        # T06
        med = "x" * 2000
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"path": "src/file.ts", "content": med},
            "session_id": "t06",
        })
        record("T06", "sonnet" in out.get("model_override", "")
               and out.get("effort") == "high", f"out={out}")

        # T07
        out = capture(handle_pre_tool_use, {
            "hook_event": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {"path": "src/x.ts", "old_string": "a",
                           "new_string": "architecture design patterns review"},
            "session_id": "t07",
        })
        record("T07", "opus" in out.get("model_override", ""), f"out={out}")

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

        # T15: SessionStart with no API key → no crash, no network
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
            record("T15", buf.getvalue().strip() == "{}",
                   f"out={buf.getvalue()!r}")
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
               "haiku" in out.get("model_override", "")
               and "effort" not in out,
               f"out={out}")

        # T24: classify_to_agent honors routing_tables[mode]
        #      quality mode maps recon → impl-sonnet (not recon-haiku)
        quality_cfg = _default_config()
        quality_cfg["mode"] = "quality"
        quality_cfg["accuracy_target"] = 99.9
        atomic_write_json(CONFIG_PATH, quality_cfg)
        agent = classify_to_agent("find existing webhook handlers",
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

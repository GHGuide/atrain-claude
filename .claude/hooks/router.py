#!/usr/bin/env python3
"""smart-router: dynamic model + effort selector for Claude Code.

Stdlib only. Never crashes — wraps everything and returns {} on error.
Atomic file writes via .tmp + os.replace. Hook latency target <50ms.
"""
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
            "auth", "authentication", "password", "secret", "api_key",
            "private_key", "access_token", "refresh_token", "crypto",
            "encrypt", "decrypt", "hash", "migration", "sql schema",
            "production", "deploy to", "main branch", "master branch",
            ".env", "dotenv", "certificate", "ssl", "tls",
        ],
        "agent_registry": dict(AGENT_REGISTRY),
        "session_stats": _empty_stats(),
        "calibration_history": [],
    }


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


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


def classify_task(tool_name: str, tool_input, config: dict) -> dict:
    tool_str = _tool_str(tool_input)
    length = len(tool_str)
    sonnet_effort = config["thresholds"].get("sonnet_effort", "high")
    opus_effort = config["thresholds"].get("opus_effort", "high")
    precise = config.get("accuracy_target", 99.0) >= 99.9

    opus_keywords = (
        "refactor entire", "redesign", "optimize", "bottleneck",
        "architecture", "design pattern", "review all", "performance",
    )
    for kw in opus_keywords:
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

    if not precise:
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
    api_keywords = ("endpoint", "route", "api", "integration")
    for kw in api_keywords:
        if kw in tool_str:
            if precise:
                eff = "xhigh" if opus_effort == "high" else opus_effort
                return {"model_alias": "opus", "effort": eff,
                        "reason": f"{kw} (precise)"}
            return {"model_alias": "sonnet", "effort": "high",
                    "reason": f"api-keyword: {kw}"}

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
    boilerplate_kw = ("scaffold", "create a basic", "stub out",
                      "add a simple", "template", "generate")
    for kw in boilerplate_kw:
        if kw in tool_str:
            if precise:
                return {"model_alias": "opus", "effort": "high",
                        "reason": "boilerplate (precise)"}
            return {"model_alias": "sonnet", "effort": "medium",
                    "reason": f"boilerplate: {kw}"}

    if precise:
        return {"model_alias": "opus", "effort": "high",
                "reason": "default (precise)"}
    return {"model_alias": "sonnet", "effort": "medium", "reason": "default"}


def hard_escalation(tool_input, config: dict, session_id: str) -> tuple:
    tool_str = _tool_str(tool_input)
    n_paths = len(PATH_RE.findall(tool_str))
    if n_paths > 3:
        return (True, f"multi-file: >3 paths ({n_paths})")
    for kw in config.get("hard_escalation_keywords", []):
        if kw in tool_str:
            return (True, f"sensitive: {kw}")
    log = load_session_log(session_id)
    last_post = None
    for entry in reversed(log):
        if entry.get("phase") == "post":
            last_post = entry
            break
    if last_post and last_post.get("had_error"):
        return (True, "error recovery")
    user_phrases = (
        "think carefully", "be precise", "dont mess", "don't mess",
        "critical", "production", "use max effort", "spare no tokens",
    )
    for p in user_phrases:
        if p in tool_str:
            return (True, f"user phrase: {p}")
    manifest_files = (
        "package.json", "pyproject.toml", "cargo.toml",
        "go.mod", "requirements.txt",
    )
    for mf in manifest_files:
        if mf in tool_str:
            return (True, f"manifest: {mf}")
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
    """Pick the router agent that best fits the task text."""
    text = full_text.lower()
    if any(kw in text for kw in config.get("hard_escalation_keywords", [])):
        return "secure-opus"
    arch_kw = ("architecture", "design pattern", "refactor entire",
               "redesign", "bottleneck", "optimize", "review all",
               "performance optimization", "system design")
    if any(k in text for k in arch_kw):
        return "architect-opus"
    api_kw = ("endpoint", " route", "api integration", "third-party",
              "http handler", "rest api", "graphql")
    if any(k in text for k in api_kw):
        return "api-sonnet"
    recon_kw = ("find ", "where is", "list files", "search for",
                "look up", "show me", "explore", "grep ", "locate")
    write_kw = ("implement", "write a", "build a", "fix the",
                "edit ", "modify", "refactor ", "add a", "create a")
    if any(k in text for k in recon_kw) and not any(k in text for k in write_kw):
        return "recon-haiku"
    return "impl-sonnet"


def handle_task_dispatch(data: dict) -> None:
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
    config = load_config()
    last_check = config.get("last_model_check", "")
    age_hours = 999.0
    try:
        last_dt = datetime.fromisoformat(last_check)
        age_hours = (datetime.now() - last_dt).total_seconds() / 3600.0
    except (ValueError, TypeError):
        pass

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if age_hours > 24 and api_key:
        try:
            req = urllib.request.Request(
                MODELS_API_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            with urllib.request.urlopen(req, timeout=2) as r:
                api_resp = json.loads(r.read().decode("utf-8"))
            _apply_registry_update(config, api_resp)
            config["last_model_check"] = datetime.now().isoformat()
            save_config(config)
        except (urllib.error.URLError, ValueError, OSError, TimeoutError):
            pass

    sys.stdout.write("{}")


def handle_pre_tool_use(data: dict) -> None:
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
        output = {
            "model_override": full_id,
            "reason": reason,
            "tier_label": f"{model_alias}+none",
        }
        log_effort = "none"
    else:
        effort = downgrade_effort(model_def, effort)
        output = {
            "model_override": full_id,
            "effort": effort,
            "reason": reason,
            "tier_label": f"{model_alias}+{effort}",
        }
        log_effort = effort

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

    had_error = any(sig in out_str for sig in ERROR_SIGNATURES)

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
    sys.stdout.write("{}")


def handle_session_end(data: dict) -> None:
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

    if total_haiku > 5:
        trust_rate = haiku_trusted / total_haiku
        if trust_rate > 0.90 and mode != "fast":
            current = config["thresholds"].get("haiku_confidence_min", 0.88)
            config["thresholds"]["haiku_confidence_min"] = max(0.5, current - 0.005)
            delta -= 0.005
            sys.stdout.write("smart-router: haiku threshold relaxed\n")
        if trust_rate < 0.70:
            current = config["thresholds"].get("haiku_confidence_min", 0.88)
            config["thresholds"]["haiku_confidence_min"] = min(0.99, current + 0.01)
            delta += 0.01
            sys.stdout.write("smart-router: haiku threshold tightened\n")

    output_verify_count = sum(
        1 for e in posts if e.get("escalation_reason") in ("error_in_output", "empty_output")
    )
    if output_verify_count > 0:
        current = config["thresholds"].get("haiku_confidence_min", 0.88)
        config["thresholds"]["haiku_confidence_min"] = min(0.99, current + 0.01)
        delta += 0.01

    config.setdefault("calibration_history", []).append({
        "date": datetime.now().isoformat(),
        "mode": mode,
        "trust_rate": trust_rate,
        "adjustment": delta,
        "total_calls": len(posts),
    })
    save_config(config)
    sys.stdout.write("smart-router: session calibration complete.\n")


def update_model_registry() -> None:
    config = load_config()
    try:
        raw = sys.stdin.read()
        api_resp = json.loads(raw) if raw.strip() else {}
    except (ValueError, OSError):
        api_resp = {}
    _apply_registry_update(config, api_resp)
    config["last_model_check"] = datetime.now().isoformat()
    save_config(config)
    o = config["model_registry"]["opus"]["id"]
    s = config["model_registry"]["sonnet"]["id"]
    h = config["model_registry"]["haiku"]["id"]
    sys.stdout.write(f"smart-router: registry updated → {o} | {s} | {h}\n")


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

        # T12
        sid = "t12_unique"
        save_session_log(sid, [])
        for _ in range(8):
            capture(handle_post_tool_use, {
                "hook_event": "PostToolUse",
                "tool_name": "Read",
                "tool_output": "clean output, all good",
                "model_used": "claude-haiku-4-5-20251001",
                "effort_used": "none",
                "session_id": sid,
            })
        for _ in range(2):
            capture(handle_post_tool_use, {
                "hook_event": "PostToolUse",
                "tool_name": "Bash",
                "tool_output": "Traceback (most recent call last)",
                "model_used": "claude-haiku-4-5-20251001",
                "effort_used": "none",
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


def main() -> None:
    try:
        if "--update-models" in sys.argv:
            update_model_registry()
            return
        if "--test" in sys.argv:
            run_tests()
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

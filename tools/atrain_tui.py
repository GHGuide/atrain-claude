#!/usr/bin/env python3
"""ATrain Live TUI Dashboard — htop-style for Claude Code routing.

Stdlib-only (curses + json). Refreshes every 1s. Reads
~/.claude/router-config.json + tails session log to render:

  - Tier histogram bars (live)
  - Cost meter (actual vs baseline)
  - Sparkline of last 30 ticks
  - Hotkeys: [s]hare receipt, [c]lear, [q]uit

Usage:
    python3 tools/atrain_tui.py
    atrain   # if installed via install.sh
"""
import curses
import json
import pathlib
import subprocess
import sys
import time
from collections import deque


REFRESH_SEC = 1.0
SPARK_LEN = 30
SPARK_CHARS = "▁▂▃▄▅▆▇█"


def load_state():
    home = pathlib.Path.home() / ".claude" / "router-config.json"
    proj = pathlib.Path(".claude/router-config.json")
    p = home if home.exists() else proj
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (ValueError, OSError):
        return None


def spark(values):
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if hi == lo:
        return SPARK_CHARS[0] * len(values)
    out = []
    for v in values:
        idx = int((v - lo) / (hi - lo) * (len(SPARK_CHARS) - 1))
        out.append(SPARK_CHARS[idx])
    return "".join(out)


def tier_bar(n, max_n, width=30):
    if max_n <= 0:
        return " " * width
    filled = int(n / max_n * width)
    return "█" * filled + "░" * (width - filled)


def draw(stdscr, history):
    stdscr.clear()
    cfg = load_state()
    if not cfg:
        stdscr.addstr(0, 0, "No router-config.json found.")
        stdscr.addstr(2, 0, "Run /atrain-go in Claude Code first.")
        stdscr.refresh()
        return

    mode = cfg.get("mode", "balanced")
    target = cfg.get("accuracy_target", 99.0)
    stats = cfg.get("session_stats", {}) or {}
    calls = stats.get("calls_by_tier", {}) or {}

    total = stats.get("total_calls", 0)
    misroutes = stats.get("dispatch_mismatches", 0)
    esc = stats.get("escalations_total", 0)
    cost = stats.get("estimated_cost_usd", 0.0)
    base = stats.get("baseline_opus_xhigh_cost_usd", 0.0)
    saved = stats.get("estimated_savings_usd", 0.0)
    saved_pct = (saved / base * 100) if base > 0 else 0.0
    accuracy = (1 - misroutes / max(total, 1)) * 100 if total > 0 else 100.0

    history.append(saved_pct)

    h, w = stdscr.getmaxyx()
    line = 0
    title = f" 🚂 ATrain Dashboard — [{mode}] target {target:.0f}% — {time.strftime('%H:%M:%S')} "
    stdscr.addstr(line, 0, title.center(w - 1, "─"), curses.A_BOLD)
    line += 2

    stdscr.addstr(line, 2, "Tier Distribution", curses.A_BOLD)
    line += 1
    max_n = max(calls.values()) if calls else 1
    tier_order = ("haiku_none", "sonnet_medium", "sonnet_high",
                  "opus_high", "opus_xhigh", "opus_max")
    for tier in tier_order:
        n = calls.get(tier, 0)
        if n == 0:
            continue
        pct = n / max(total, 1) * 100
        bar = tier_bar(n, max_n, 28)
        stdscr.addstr(line, 4,
                      f"{tier:<16s} {bar} {n:>4d} ({pct:>4.1f}%)")
        line += 1
    line += 1

    stdscr.addstr(line, 2, "Cost", curses.A_BOLD)
    line += 1
    stdscr.addstr(line, 4,
                  f"Actual    ${cost:>7.2f}    Baseline ${base:>7.2f}")
    line += 1
    stdscr.addstr(line, 4, f"Saved     ${saved:>7.2f}    ({saved_pct:.1f}%)")
    line += 2

    stdscr.addstr(line, 2, "Save % (last 30 ticks)", curses.A_BOLD)
    line += 1
    stdscr.addstr(line, 4, spark(list(history)))
    line += 2

    stdscr.addstr(line, 2, "Health", curses.A_BOLD)
    line += 1
    flags = []
    if cost > 5.0 and saved_pct < 30.0:
        flags.append(f"⚠ HIGH-COST + LOW SAVE")
    opus_xh = calls.get("opus_xhigh", 0)
    if total > 100 and opus_xh / max(total, 1) > 0.30:
        flags.append("⚠ Over-escalating to opus_xhigh")
    if total > 50 and calls.get("haiku_none", 0) / max(total, 1) < 0.10:
        flags.append("⚠ Under-using haiku")
    if total > 80:
        flags.append(f"ℹ Long session ({total} calls) — consider /clear")
    if not flags:
        stdscr.addstr(line, 4, "✓ Healthy")
        line += 1
    else:
        for f in flags[:3]:
            stdscr.addstr(line, 4, f[:w - 6])
            line += 1
    line += 1

    stdscr.addstr(line, 2,
                  f"Calls {total}  Misroutes {misroutes}  Sensitive {esc}",
                  curses.A_DIM)
    line += 2

    hint = " [s]hare receipt   [c]lear stats   [q]uit "
    stdscr.addstr(h - 2, 0, hint.center(w - 1, "─"))

    stdscr.refresh()


def share_receipt():
    candidates = [
        pathlib.Path("tools/atrain_receipt.py"),
        pathlib.Path.home() / ".claude" / "tools" / "atrain_receipt.py",
    ]
    script = next((c for c in candidates if c.exists()), None)
    if script is None:
        return
    out = pathlib.Path.cwd() / "atrain-receipt.svg"
    subprocess.run(["python3", str(script), "--out", str(out), "--tweet"],
                   capture_output=False)


def clear_stats():
    home = pathlib.Path.home() / ".claude" / "router-config.json"
    proj = pathlib.Path(".claude/router-config.json")
    p = home if home.exists() else proj
    if not p.exists():
        return
    cfg = json.loads(p.read_text())
    empty = {k: 0 for k in [
        "haiku_none", "sonnet_low", "sonnet_medium", "sonnet_high",
        "sonnet_max", "opus_low", "opus_medium", "opus_high",
        "opus_xhigh", "opus_max",
    ]}
    cfg["session_stats"] = {
        "total_calls": 0, "calls_by_tier": dict(empty),
        "tokens_by_tier": dict(empty),
        "escalations_total": 0, "estimated_cost_usd": 0.0,
        "baseline_opus_xhigh_cost_usd": 0.0,
        "estimated_savings_usd": 0.0,
        "dispatch_mismatches": 0, "dispatch_blocks": 0,
    }
    import os
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2))
    os.replace(tmp, p)


def run(stdscr):
    curses.curs_set(0)
    stdscr.timeout(int(REFRESH_SEC * 1000))
    history = deque(maxlen=SPARK_LEN)
    while True:
        try:
            draw(stdscr, history)
        except curses.error:
            pass
        ch = stdscr.getch()
        if ch in (ord("q"), ord("Q"), 27):
            break
        elif ch in (ord("s"), ord("S")):
            curses.endwin()
            share_receipt()
            stdscr = curses.initscr()
            curses.curs_set(0)
            stdscr.timeout(int(REFRESH_SEC * 1000))
        elif ch in (ord("c"), ord("C")):
            clear_stats()
            history.clear()


def main():
    if "--once" in sys.argv:
        # Non-interactive: render once then exit (for screenshot bots)
        cfg = load_state()
        if not cfg:
            print("No config.")
            return
        stats = cfg.get("session_stats", {})
        print(json.dumps(stats, indent=2))
        return
    curses.wrapper(run)


if __name__ == "__main__":
    main()

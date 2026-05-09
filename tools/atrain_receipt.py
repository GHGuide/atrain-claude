#!/usr/bin/env python3
"""ATrain Save Receipt — generate shareable SVG card from session stats.

Stdlib-only. No PIL/cairo. SVG renders identically in browser, Twitter,
GitHub README, Discord. Pure text → also embeddable in markdown.

Usage:
    python3 tools/atrain_receipt.py                # writes receipt.svg
    python3 tools/atrain_receipt.py --out card.svg # custom path
    python3 tools/atrain_receipt.py --tweet        # also print Twitter intent URL
"""
import argparse
import html
import json
import pathlib
import sys
import urllib.parse
from datetime import datetime


def load_stats() -> dict:
    home = pathlib.Path.home() / ".claude" / "router-config.json"
    proj = pathlib.Path(".claude/router-config.json")
    p = home if home.exists() else proj
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text()).get("session_stats", {})
    except (ValueError, OSError):
        return {}


def render_svg(stats: dict, mode: str = "balanced") -> str:
    total = stats.get("total_calls", 0)
    cost = stats.get("estimated_cost_usd", 0.0)
    base = stats.get("baseline_opus_xhigh_cost_usd", 0.0)
    saved = stats.get("estimated_savings_usd", 0.0)
    saved_pct = (saved / base * 100) if base > 0 else 0.0

    today = datetime.now().strftime("%a %d %b %Y")
    bar_w = 540
    fill_w = int(min(saved_pct, 100) / 100 * bar_w)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="700" height="380" viewBox="0 0 700 380">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#0f172a"/>
      <stop offset="100%" stop-color="#1e293b"/>
    </linearGradient>
    <linearGradient id="bar" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#10b981"/>
      <stop offset="100%" stop-color="#34d399"/>
    </linearGradient>
  </defs>
  <rect width="700" height="380" rx="20" fill="url(#bg)"/>
  <rect x="20" y="20" width="660" height="340" rx="14"
        fill="none" stroke="#334155" stroke-width="1"/>

  <text x="50" y="70" fill="#f1f5f9" font-family="ui-monospace,Menlo,monospace"
        font-size="28" font-weight="700">🚂 ATrain Save Receipt</text>
  <text x="50" y="100" fill="#94a3b8" font-family="ui-monospace,Menlo,monospace"
        font-size="14">{html.escape(today)} · mode: {html.escape(mode)}</text>

  <text x="50" y="170" fill="#10b981" font-family="ui-monospace,Menlo,monospace"
        font-size="64" font-weight="700">${saved:.2f}</text>
  <text x="50" y="200" fill="#94a3b8" font-family="ui-monospace,Menlo,monospace"
        font-size="14">saved vs all-Opus baseline ({saved_pct:.1f}%)</text>

  <rect x="50" y="225" width="{bar_w}" height="20" rx="10" fill="#1e293b"/>
  <rect x="50" y="225" width="{fill_w}" height="20" rx="10" fill="url(#bar)"/>

  <text x="50" y="295" fill="#cbd5e1" font-family="ui-monospace,Menlo,monospace"
        font-size="14">{total} tool calls · ${cost:.2f} actual · ${base:.2f} baseline</text>

  <text x="50" y="335" fill="#64748b" font-family="ui-monospace,Menlo,monospace"
        font-size="12">github.com/LeonardoCalancea/atrain-claude · /atrain-receipt</text>
</svg>"""


def tweet_intent(stats: dict) -> str:
    saved = stats.get("estimated_savings_usd", 0.0)
    base = stats.get("baseline_opus_xhigh_cost_usd", 0.0)
    pct = (saved / base * 100) if base > 0 else 0.0
    text = (
        f"ATrain just saved me ${saved:.2f} ({pct:.0f}%) on this Claude Code "
        f"session. Same accuracy, fraction of the cost. "
        f"github.com/LeonardoCalancea/atrain-claude"
    )
    return "https://twitter.com/intent/tweet?text=" + urllib.parse.quote(text)


def autopsy_stats(jsonl_path: str) -> dict:
    """Generate stats dict from a past Claude transcript via autopsy."""
    import subprocess
    here = pathlib.Path(__file__).resolve().parent
    autopsy = here / "atrain_autopsy.py"
    if not autopsy.exists():
        return {}
    r = subprocess.run(
        ["python3", str(autopsy), jsonl_path],
        capture_output=True, text=True, timeout=30
    )
    if r.returncode != 0:
        return {}
    out = r.stdout
    # Parse the simple table — pull "Cost with ATrain" "Cost all-Opus" "WOULD HAVE SAVED"
    import re as _re
    m_cost = _re.search(r"Cost with ATrain\s*:\s*\$([\d.]+)", out)
    m_base = _re.search(r"Cost all-Opus\s*:\s*\$([\d.]+)", out)
    m_save = _re.search(r"WOULD HAVE SAVED\s*:\s*\$([\d.]+)\s*\(\s*([\d.]+)%\)", out)
    m_total = _re.search(r"Prompts analyzed\s*:\s*(\d+)", out)
    if not (m_cost and m_base and m_save and m_total):
        return {}
    return {
        "total_calls": int(m_total.group(1)),
        "estimated_cost_usd": float(m_cost.group(1)),
        "baseline_opus_xhigh_cost_usd": float(m_base.group(1)),
        "estimated_savings_usd": float(m_save.group(1)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="receipt.svg")
    ap.add_argument("--tweet", action="store_true")
    ap.add_argument("--autopsy",
                    help="Path to a Claude Code transcript .jsonl. "
                         "Generates receipt from autopsy projection "
                         "instead of live session stats.")
    args = ap.parse_args()

    if args.autopsy:
        stats = autopsy_stats(args.autopsy)
        if not stats:
            print(f"Autopsy failed for {args.autopsy}", file=sys.stderr)
            sys.exit(1)
    else:
        stats = load_stats()
    if not stats:
        print("No session stats found. Run /atrain-go and use ATrain first.",
              file=sys.stderr)
        sys.exit(1)

    home = pathlib.Path.home() / ".claude" / "router-config.json"
    proj = pathlib.Path(".claude/router-config.json")
    p = home if home.exists() else proj
    cfg = json.loads(p.read_text()) if p.exists() else {}
    mode = cfg.get("mode", "balanced")

    svg = render_svg(stats, mode)
    out = pathlib.Path(args.out)
    out.write_text(svg)
    print(f"Wrote {out}")
    if args.tweet:
        print(f"Tweet: {tweet_intent(stats)}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""ATrain IO sanity check. Inspects session_log files in $TMPDIR and
reports which ones would benefit from /atrain-go reload (forces a
save_session_log that applies the v9 cap). Stdlib-only."""
import json, pathlib, sys, tempfile, time


def main():
    tmp = pathlib.Path(tempfile.gettempdir())
    files = sorted(tmp.glob("smart-router-*.json"),
                   key=lambda p: p.stat().st_size, reverse=True)
    if not files:
        print("No ATrain session logs found in $TMPDIR.")
        return
    print("ATrain session_log IO check")
    print("---")
    print(f"{'file':<48s}  {'size':>7s}  {'entries':>8s}  {'age':>6s}  "
          f"{'over_cap':>9s}")
    over_count = 0
    total_excess = 0
    cap = 500
    for p in files[:20]:
        sz = p.stat().st_size
        age = (time.time() - p.stat().st_mtime) / 60
        try:
            entries = len(json.loads(p.read_text()))
        except Exception:
            entries = -1
        if entries > cap:
            over_count += 1
            est_after_cap = int(sz * cap / max(1, entries))
            total_excess += sz - est_after_cap
            tag = "YES"
        else:
            tag = "no"
        print(f"  {p.name[14:62]:<48s}  {sz//1024:>5d}KB  "
              f"{entries:>8d}  {age:>4.0f}m  {tag:>9s}")
    print("---")
    print(f"Logs over cap : {over_count}")
    if over_count:
        print(f"Excess bytes  : ~{total_excess//1024} KB across {over_count} "
              "logs")
        print("Each will auto-trim on the next save_session_log call.")


if __name__ == "__main__":
    main()

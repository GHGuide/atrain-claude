#!/usr/bin/env python3
"""Test harness: extract inline python from each /atrain-*.md and exec.
Backs up router-config.json before each cmd that mutates state."""
import json, os, pathlib, re, shutil, subprocess, sys, tempfile, time

CMDS_DIR = pathlib.Path(__file__).resolve().parent
if not CMDS_DIR.name == "commands":
    CMDS_DIR = pathlib.Path(
        "/Users/leonardo/Downloads/idea for hackathon/.claude/commands"
    )

CONFIG = pathlib.Path.home() / ".claude" / "router-config.json"
backup = json.loads(CONFIG.read_text())

results = []
for md in sorted(CMDS_DIR.glob("atrain*.md")):
    name = md.stem
    src = md.read_text()
    # Extract first python heredoc body
    m = re.search(r"python3\s+-\s+<<'EOF'\n(.*?)\nEOF", src, re.DOTALL)
    if not m:
        results.append((name, "NO_INLINE_PY", ""))
        continue
    body = m.group(1)
    # Substitute $ARGUMENTS with empty string for testing
    body = body.replace("$ARGUMENTS", "")
    # Write to temp file, exec in subprocess so it's isolated
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False) as f:
        f.write(body)
        tmp = f.name
    try:
        r = subprocess.run(
            ["python3", tmp],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "CLAUDE_SESSION_ID": "test_cmd_harness"},
        )
        ok = r.returncode == 0
        first_out_line = (r.stdout.splitlines() or [""])[0][:60]
        err_line = (r.stderr.splitlines() or [""])[-1][:60] if r.stderr else ""
        tag = "PASS" if ok else "FAIL"
        results.append((name, tag, first_out_line or err_line))
    except subprocess.TimeoutExpired:
        results.append((name, "TIMEOUT", ""))
    finally:
        os.unlink(tmp)
        # Restore config after each potentially-mutating cmd
        CONFIG.write_text(json.dumps(backup, indent=2))

print(f"{'command':<28s} {'result':<10s} first-output-line")
print("-" * 80)
fail_n = 0
for name, tag, line in results:
    print(f"{name:<28s} {tag:<10s} {line}")
    if tag != "PASS":
        fail_n += 1
print("-" * 80)
print(f"{len(results)} commands, {len(results)-fail_n} pass, {fail_n} fail")
sys.exit(fail_n)

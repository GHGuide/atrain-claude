# smart-router

Dynamic per-call selection of Claude model + effort level for Claude
Code. Routes recon to **Haiku 4.5**, mid-size edits to **Sonnet 4.6**,
architecture and security work to **Opus 4.7** — while keeping a
configurable accuracy target. Auto-discovers new Claude models from
the Anthropic API so the registry never goes stale.

## What it does

Two layers working together:

1. **Subagent dispatch (real, runtime-respected).** Five pre-built
   subagents in `.claude/agents/` with `model:` frontmatter that
   Claude Code actually honors:

   | Subagent          | Model       | Use for                                   |
   |-------------------|-------------|-------------------------------------------|
   | `recon-haiku`     | Haiku 4.5   | read-only recon, search, grep, list       |
   | `impl-sonnet`     | Sonnet 4.6  | default — single/2-file edits, tests      |
   | `api-sonnet`      | Sonnet 4.6  | endpoints, routes, integrations           |
   | `architect-opus`  | Opus 4.7    | multi-file refactors, design, perf        |
   | `secure-opus`     | Opus 4.7    | MANDATORY for auth/secrets/crypto         |

2. **Per-tool classification (analytics + enforcement).** A Python
   `PreToolUse` hook classifies every tool call into a `(model,
   effort)` tier, blocks sensitive Task dispatches headed to a
   non-Opus subagent, and tracks cost / savings / escalations.

## Install — global (recommended)

Slash commands appear in Claude Code's command picker in **every**
project. One install script does everything:

```bash
git clone https://github.com/Metrcih/smart-router.git
cd smart-router
./install.sh        # copies into ~/.claude/, merges hooks into settings.json
```

What the script does:

- Copies `commands/`, `agents/`, `skills/smart-router/`, `hooks/router.py`
  into `~/.claude/`
- Merges four hook entries (`SessionStart`, `UserPromptSubmit`,
  `PreToolUse`, `PostToolUse`) into `~/.claude/settings.json` —
  it does **not** clobber existing hooks
- Drops a default `~/.claude/router-config.json` (kept on re-install
  unless you set `FORCE=1`)

Restart Claude Code. In any project, the picker now shows
`/router-eco`, `/router-balanced`, `/router-quality`, plus the
five tiered subagents.

Uninstall: `./uninstall.sh` (cleans files + detaches hook entries
without touching the rest of your settings).

## Install — single project (alternative)

If you only want the plugin in one project:

```bash
cp -r /path/to/smart-router/.claude /path/to/your-project/
cp -r /path/to/smart-router/.claude-plugin /path/to/your-project/
```

Restart Claude Code in that project.

## Verify

```bash
python3 .claude/hooks/router.py --test    # 16/16 should pass
```

## Pick a preset (one click per conversation)

Three slash commands. Pick one at the start of a conversation based
on how much accuracy you'll trade for token savings.

| Command            | Accuracy | Token savings | Use for                             |
|--------------------|----------|---------------|-------------------------------------|
| `/router-eco`      | 95%      | ~90% saved    | exploration, prototypes, sketches   |
| `/router-balanced` | 99%      | ~50% saved    | day-to-day work (default)           |
| `/router-quality`  | 99.9%    | ~20% saved    | production code, security, finals   |

Each preset prints a confirmation card and resets per-session stats
so `/smart-router-report` gives you a clean picture.

### Other commands

- `/smart-router-set <fast|balanced|precise|max|<num>>` — fine-grained
  mode for power users.
- `/smart-router-status` — current mode + active thresholds + session
  stats + smart recommendation.
- `/smart-router-report` — full session breakdown with progress bars,
  escalation reasons, token totals, cost vs baseline.

## Effort levels

| Level    | Models supported           | Behaviour                       |
|----------|----------------------------|---------------------------------|
| `low`    | opus, sonnet               | minimal thinking, fastest       |
| `medium` | opus, sonnet               | moderate, may skip simple work  |
| `high`   | opus, sonnet               | always thinks                   |
| `xhigh`  | opus only                  | always thinks deeply            |
| `max`    | opus, sonnet (session-only)| deepest, no token ceiling       |
| (none)   | haiku                      | Haiku has no `effort` parameter |

`max` is **session-scoped** — never persisted to `router-config.json`,
reverts on the next call.

## Bundled tokens — no API key required

The plugin uses your existing Claude Code subscription quota. The
hook never makes network calls during routing — all classification
runs locally in stdlib Python. Actual model calls (the work Claude
performs) go through Claude Code using your logged-in account.

The model registry (the list of `claude-opus-4-*`, `claude-sonnet-4-*`,
`claude-haiku-4-*` IDs) is shipped in `router-config.json` and stays
current via plugin updates (`git pull`). If you want to refresh it
yourself between releases, that one-shot refresh does need an API
key:

```bash
curl -s https://api.anthropic.com/v1/models \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  | python3 .claude/hooks/router.py --update-models
```

If the registry is older than 30 days, the SessionStart hook prints
a non-blocking reminder. Day-to-day routing keeps working with the
shipped registry.

## Tests

```bash
python3 .claude/hooks/router.py --test
```

16 tests covering classification, escalation, post-call stats,
session calibration, Task dispatch, SessionStart, and registry
updates.

## License

MIT — see [LICENSE](LICENSE).

<h1 align="center">🚂 ATrain</h1>
<p align="center">
  <b>Cut your Claude Code bill ~80%. Same accuracy. No API key. 30-second install.</b>
</p>
<p align="center">
  <a href="#try-it-on-your-own-past-sessions-first">Try first</a> ·
  <a href="#install">Install</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#honest-numbers">Honest numbers</a>
</p>

<p align="center">
  <img src="docs/receipt-lelau-ultra.svg" width="640" alt="ATrain save receipt"/>
</p>

---

## What is this

Claude Code runs every tool call on the same model. A 50-character `Read` pays the same Opus rate as a 4-file refactor.

ATrain is a hook plugin that watches each tool call and routes it to the cheapest Claude model that can handle it. Haiku for reads. Sonnet for edits. Opus only for architecture, security, and anything sensitive.

You write code the same way. Your bill shrinks.

---

## Try it on your own past sessions first

No install needed. The autopsy script reads any past Claude Code transcript and tells you exactly what ATrain would have saved.

```bash
git clone https://github.com/LeonardoCalancea/atrain-claude
cd atrain-claude
python3 tools/atrain_autopsy.py ~/.claude/projects/*/<session-id>.jsonl
```

Output on a real 913-prompt session:

```
🚂 ATrain Token Autopsy
─────────────────────────────────
Prompts analyzed   : 913
Routed to haiku    : 127 (14%)
Routed to sonnet   : 494 (54%)
Routed to opus     : 292 (32%)
─────────────────────────────────
Cost with ATrain   : $12.96
Cost all-Opus      : $44.59
SAVED              : $31.63  (70.9%)
```

If the number isn't convincing, don't install. If it is, keep reading.

---

## Install

```bash
git clone https://github.com/LeonardoCalancea/atrain-claude && cd atrain-claude
bash install.sh
```

Restart Claude Code. Then:

```
/atrain-ultimate
```

That's it. Stack armed for the whole conversation. Switch to readable prose with `/atrain-regular` or disarm with `/atrain-kill`.

---

## Five commands. That's the whole surface.

| Command | What it does |
|---------|--------------|
| `/atrain-ultimate` | Max savings. Caveman ULTRA output + full v8 stack. |
| `/atrain-regular`  | Same v8 stack, caveman OFF, readable prose. |
| `/atrain-kill`     | Disarm everything. Data retained in cache DB. |
| `/atrain-status`   | Live card — cost, savings %, accuracy, tier mix. |
| `/atrain-autopsy`  | Project savings on any past transcript. |

---

## How it works

1. **Routes every tool call.** Recon (`Read`, `Grep`, `LS`) → Haiku. Edits → Sonnet. Architecture, security, large refactors → Opus. Sensitive keywords (auth, payment, crypto, schema migrations, prod deploys) always force Opus, never silently downgraded.
2. **Compresses output.** Caveman terse mode strips filler from natural-language responses. Code, commits, and security writeups stay normal.
3. **Caches and indexes.** Repeated `Read`s served from SQLite. Codebase symbol index built once per session. Cross-session FTS5 recall surfaces prior tool outputs when you ask similar questions.
4. **Rewrites bash output.** `pytest`/`cargo test`/`npm test`/`git status` all get compressed before hitting context (Copilot pattern).

Pure stdlib Python. No PyPI dependencies. No API key. No new CLI. Runs inside Claude Code on bundled tokens.

---

## Honest numbers

Two real-world measurements. Pick the one that matches your baseline.

| Baseline | Saved |
|----------|-------|
| Naive Opus xhigh + no output compression | **~95%** |
| Same Opus xhigh + same caveman output compression (apples-to-apples) | **~80%** |
| Typical Claude Code Sonnet defaults | **~40-50%** |

Across 13 real coding sessions (6,000+ prompts), full-cost accounting including input tokens:
- `/atrain` average: **~73%** saved
- Range: 64–82%
- Classifier accuracy: 108/108

Reproduce yourself:

```bash
python3 tools/atrain_full_efficiency_bench.py --stack ultimate
python3 -c "import json, pathlib; print(json.load(open(pathlib.Path.home()/'.claude'/'router-config.json'))['session_stats'])"
```

---

## Drawbacks

- `/atrain-ultimate` gives terse output. Use `/atrain-regular` for full prose.
- First session on a new project: no prior cache, savings start lower and ramp up after 2-3 sessions.
- Doesn't help if you're already running everything on Haiku. Helps most against Opus-heavy or default Sonnet workloads.

---

## Built on

Patterns credited inline in `router.py`. Highlights: Skeleton-of-Thought (arxiv 2307.15337), TokenSkip (2502.12067), Adaptive-Consistency (2305.11860), Speculative Cascade (2506.04203), MemGPT (2310.08560), Selective Context (2310.06201), Anthropic's Code-Execution-with-MCP, JuliusBrussee/caveman, rtk-ai/rtk.

---

## License

MIT. Use it, fork it, ship it.

---

<p align="center"><b>If it saves you money, star the repo.</b></p>

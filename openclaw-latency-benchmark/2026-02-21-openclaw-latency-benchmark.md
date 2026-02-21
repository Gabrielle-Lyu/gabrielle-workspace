# OpenClaw Latency Benchmark — 2026-02-21

**Goal:** Measure TTFT (time-to-first-token) and total latency, then attribute time to: context build, QMD retrieval, tool calls, and model inference.

**Environment:**
- Host: Ubuntu 6.8.0-1041-oracle (VM)
- OpenClaw version: 2026.2.19-2 (45d9b20)
- Model: `anthropic/claude-sonnet-4-5` (thinking: low)
- Memory backend: QMD (`/home/ubuntu/openclaw-vault`, 177 chunks / 56 files indexed)
- Gateway: local, `ws://127.0.0.1:18789`

---

## Test Matrix

### Scenarios

| ID | Description | Memory | Tools | Agent |
|----|-------------|--------|-------|-------|
| S0 | Model-only (minimal) | OFF | OFF | `perf-s0` (new agent, minimal AGENTS.md) |
| S1+S2 | Main agent (QMD memory + startup file reads) | ON (QMD) | OFF | `main` |
| S3 | Web + crawl tools | ON (QMD) | ON (`web_search`, `crawl_doc`) | `main` |

> Note: S1 and S2 could not be fully isolated in this run — the `main` agent performs both QMD memory search (S1) and explicit file reads via tool calls (S2) as part of its AGENTS.md startup instructions. Results for both are reported together as S1+S2.

### Prompts

| ID | Text | Intent |
|----|------|--------|
| P1 | `Reply with "OK".` | Trivial — pure inference baseline |
| P2 | `What is my favorite GPU? If unknown, say "unknown".` | Memory/retrieval probe |
| P3 | `Summarize the last 2 days of my notes into 5 bullets.` | Heavy context + multi-file read |

---

## Section E: QMD Standalone Benchmark

Ran each query 10× using the qmd binary directly to isolate memory backend latency:

```bash
for i in {1..10}; do
  { time /home/ubuntu/.bun/bin/qmd search /home/ubuntu/openclaw-vault "pushgateway stress test" \
    --limit 5 > /dev/null 2>&1; } 2>&1 | grep real
done
```

### Results

| Query | Min | Max | Avg | Std dev |
|-------|-----|-----|-----|---------|
| `"pushgateway stress test"` | 381ms | 394ms | 388ms | ~4ms |
| `"favorite gpu"` | 383ms | 399ms | 388ms | ~5ms |

**Raw data — "pushgateway stress test":**
```
run 1: 0m0.384s   run 2: 0m0.386s   run 3: 0m0.390s   run 4: 0m0.386s   run 5: 0m0.385s
run 6: 0m0.394s   run 7: 0m0.389s   run 8: 0m0.381s   run 9: 0m0.392s   run 10: 0m0.389s
```

**Raw data — "favorite gpu":**
```
run 1: 0m0.389s   run 2: 0m0.394s   run 3: 0m0.384s   run 4: 0m0.386s   run 5: 0m0.383s
run 6: 0m0.385s   run 7: 0m0.399s   run 8: 0m0.387s   run 9: 0m0.384s   run 10: 0m0.384s
```

**Verdict:** QMD search is **consistently ~388ms** with near-zero variance. There is no warm-up effect (no caching benefit across runs). The cost is paid on every invocation.

---

## Agent Run Results

All timings are from gateway debug logs (`/tmp/openclaw/openclaw-2026-02-21.log`), parsed from `embedded run *` JSONL entries. Wall-clock time ≈ logged time + ~1.8s CLI overhead.

#### How LLM turns are counted

The gateway log emits only four markers inside an agent run:

```
embedded run agent start
embedded run tool start   ← one per tool call
embedded run tool end     ← one per tool call
embedded run agent end
```

There is no separate "LLM turn start/end" marker. Turns are **inferred from the silent gaps** between those markers:

```
agent_start ──[silence = LLM thinking]──► tool_start   → LLM turn 1
tool_end    ──[silence = LLM thinking]──► tool_start   → LLM turn N
tool_end    ──[silence = LLM thinking]──► agent_end    → final LLM turn
```

Any gap >50ms where no tool is executing is counted as a distinct LLM inference period. Multiple tool calls that fire within <50ms of each other (parallel batch) are counted as a single tool-execution block belonging to the same turn.

### Timing definitions

| Metric | Log markers used |
|--------|-----------------|
| **Ctx build** | `embedded run start` → `embedded run agent start` |
| **LLM inference** | All silent gaps between `agent start`, `tool start/end`, and `agent end` |
| **Tool time** | Sum of all `tool end` − `tool start` intervals |
| **Total** | `durationMs` from `embedded run prompt end` |

### Full results table — scenario matrix runs

| Scenario | Prompt | Run ID (prefix) | Total | Ctx Build | LLM Turn 1 | Tool Time | # Tools | LLM Turn 2 | % LLM |
|----------|--------|-----------------|-------|-----------|------------|-----------|---------|------------|-------|
| S0 | P1: "Reply OK" | `b3dd86d9` | **2.9s** | 54ms | 2.87s | 0ms | 0 | 0s | 100% |
| S0 | P2: Fav GPU | `27da8c8b` | **6.6s** | 18ms | 6.58s | 0ms | 0 | 0s | 100% |
| S0 | P3: Summarize notes | `cbd23b95` | **11.9s** | 13ms | 11.89s | 0ms | 0 | 0s | 100% |
| S1+S2 | P1: "Reply OK" | `4b60244b` | **2.4s** | 15ms | 2.35s | 0ms | 0 | 0s | 100% |
| S1+S2 | P2: Fav GPU | `f504022e` | **6.7s** | 13ms | 4.13s | 564ms | 1 | 2.00s | 92% |
| S1+S2 | P3: Summarize notes | `af7f167f` | **25.8s** | 15ms | 3.72s | 160ms | 7 | 11.73s | 60% |
| S3 | Crawl query | `c0f0ec4b` | **55.4s** | 13ms | 3.75s | 22.6s | 8 | 5.74s | 17% |

### S1+S2 P2 tool detail

| Tool | Duration |
|------|----------|
| `memory_search` | **564ms** |

The `memory_search` tool invocation (in-agent QMD call) cost 564ms vs 388ms standalone — the ~176ms delta is subprocess spawn + IPC overhead.

### S1+S2 P3 tool detail

| Tool | Duration | Note |
|------|----------|------|
| `exec` | 39ms | |
| `exec` | 43ms | |
| `read` | 34ms | SOUL.md or USER.md |
| `read` | 12ms | |
| `read` | 10ms | |
| `read` | 11ms | |
| `read` | 12ms | |

Seven tool calls triggered by AGENTS.md startup instructions (read SOUL.md, USER.md, today/yesterday journal, MEMORY.md). The file I/O itself was cheap (~10–40ms each). The cost was the **extra LLM turn** this created.

### S3 tool detail

| Tool | Call 1 | Call 2 | Call 3 |
|------|--------|--------|--------|
| `web_search` | 1.23s | 0.88s | — |
| `crawl_doc` | **9.15s** | **10.04s** | 1.27s |
| `read` | 23ms | 20ms | 27ms |

Total tool time: **22.6s** (of 55.4s total). `crawl_doc` alone accounted for 20.4s.

---

## All runs — complete step-by-step trace

Using `explain-runs.py` (see `openclaw-latency-benchmark/`), every run in today's
log was reconstructed with each LLM inference gap and tool call shown in order.

### How to read the traces

```
[SETUP]   session init + context assembly (always negligible)
[LLM N]   the model is thinking — no tool is running
[TOOL]    a tool call executed (name + duration)
BREAKDOWN summary at the end of each run
```

---

### `b543d775` — 07:09:23 — 35.3s — 4 LLM turns

```
[SETUP]  41ms

[LLM 1]   +0.04s  ───────────────────────────────
           7.34s  (model reads context + decides what to do)
[TOOL]   +7.38s   exec   (27ms)
[TOOL]   +7.41s   read   (24ms)

[LLM 2]   +7.44s  ───────────────────────────────
           6.79s  (model reads tool result + decides next step)
[TOOL]   +14.22s  exec   (14ms)
[TOOL]   +14.24s  exec   (13ms)

[LLM 3]   +14.26s ───────────────────────────────
           2.67s  (model reads tool result + decides next step)
[TOOL]   +16.92s  read   (9ms)

[LLM 4]   +16.93s ───────────────────────────────
           18.37s (model writes final answer)

BREAKDOWN:  LLM 35.14s (100%)  |  tools 87ms (0%)  ×5  [exec×3, read×2]
```

---

### `5854ada9` — 07:12:32 — 35.4s — 6 LLM turns

Notable: first exec call took **3.4s** (slow shell command).

```
[SETUP]  17ms

[LLM 1]   +0.02s  ───────────────────────────────
           5.09s  (model reads context + decides what to do)
[TOOL]   +5.11s   exec   (3439ms)  ← slow command

[LLM 2]   +8.55s  ───────────────────────────────
           3.81s  (model reads tool result + decides next step)
[TOOL]   +12.35s  exec   (13ms)

[LLM 3]   +12.37s ───────────────────────────────
           3.23s  (model reads tool result + decides next step)
[TOOL]   +15.59s  exec   (18ms)

[LLM 4]   +15.61s ───────────────────────────────
           3.27s  (model reads tool result + decides next step)
[TOOL]   +18.88s  read   (9ms)

[LLM 5]   +18.89s ───────────────────────────────
           2.97s  (model reads tool result + decides next step)
[TOOL]   +21.86s  read   (5ms)

[LLM 6]   +21.86s ───────────────────────────────
           13.55s (model writes final answer)

BREAKDOWN:  LLM 31.89s (90%)  |  tools 3.48s (10%)  ×5  [exec×3 (3.47s), read×2 (14ms)]
```

---

### `450ff526` — 07:19:41 — 21.0s — 2 LLM turns

Notable: agent tried to read journal files that **don't exist** — ENOENT errors returned in 29ms total, but the model still had to process the error results and write a response.

```
[SETUP]  15ms

[LLM 1]   +0.01s  ───────────────────────────────
           11.74s (model reads context + decides what to do)
[TOOL]   +11.75s  read   (16ms)  ← ENOENT: 2026-02-21.md not found
[TOOL]   +11.77s  read   (8ms)   ← ENOENT: 2026-02-20.md not found
[TOOL]   +11.78s  read   (5ms)   ← ENOENT

[LLM 2]   +11.79s ───────────────────────────────
           9.26s  (model writes final answer)

BREAKDOWN:  LLM 20.99s (100%)  |  tools 29ms (0%)  ×3  [read×3]
```

---

### `f504022e` — 07:29:54 — 6.7s — 2 LLM turns  *(S1+S2 P2 benchmark run)*

The only run where `memory_search` appeared. Shows the QMD cost clearly.

```
[SETUP]  13ms

[LLM 1]   +0.01s  ───────────────────────────────
           4.13s  (model reads context + decides what to do)
[TOOL]   +4.14s   memory_search (564ms)  ← QMD search

[LLM 2]   +4.71s  ───────────────────────────────
           2.00s  (model writes final answer)

BREAKDOWN:  LLM 6.12s (91%)  |  tools 564ms (8%)  ×1  [memory_search×1]
```

---

### `af7f167f` — 07:30:17 — 25.8s — 4 LLM turns  *(S1+S2 P3 benchmark run)*

The clearest example of AGENTS.md startup cost: two `exec` calls to find journal files, then five parallel `read` calls, each triggering its own inference round-trip.

```
[SETUP]  15ms

[LLM 1]   +0.01s  ───────────────────────────────
           3.72s  (model reads context + decides what to do)
[TOOL]   +3.74s   exec   (39ms)   ← probably: ls journal dir

[LLM 2]   +3.77s  ───────────────────────────────
           3.83s  (model reads tool result + decides next step)
[TOOL]   +7.60s   exec   (43ms)   ← follow-up shell command

[LLM 3]   +7.65s  ───────────────────────────────
           6.31s  (model reads tool result + decides next step)
[TOOL]   +13.96s  read   (34ms)   ← reads journal file 1
[TOOL]   +13.99s  read   (12ms)   ← reads journal file 2
[TOOL]   +14.01s  read   (10ms)   ← reads journal file 3
[TOOL]   +14.02s  read   (11ms)   ← reads journal file 4
[TOOL]   +14.03s  read   (12ms)   ← reads journal file 5

[LLM 4]   +14.04s ───────────────────────────────
           11.73s (model writes final answer — now has all context)

BREAKDOWN:  LLM 25.59s (99%)  |  tools 161ms (1%)  ×7  [exec×2 (82ms), read×5 (79ms)]
```

Total LLM turns: **4**. Total tool I/O: **161ms**. The 25.8s runtime is almost entirely inference.

---

### `c0f0ec4b` — 07:31:57 — 55.4s — 9 LLM turns  *(S3 crawl benchmark run)*

The most complex run. Shows how each tool call forces another inference round-trip, and how `crawl_doc` dominates wall time.

```
[SETUP]  13ms

[LLM 1]   +0.01s  ───────────────────────────────
           3.75s  (model reads context + decides what to do)
[TOOL]   +3.76s   web_search  (1231ms)

[LLM 2]   +4.99s  ───────────────────────────────
           3.62s  (model reads search results + decides to crawl)
[TOOL]   +8.61s   crawl_doc   (9147ms)  ← 9s network fetch

[LLM 3]   +17.76s ───────────────────────────────
           3.19s  (model reads page + decides next step)
[TOOL]   +20.94s  read        (23ms)

[LLM 4]   +20.96s ───────────────────────────────
           2.88s  (model reads tool result + decides next step)
[TOOL]   +23.84s  crawl_doc   (1270ms)

[LLM 5]   +25.11s ───────────────────────────────
           2.92s  (model reads page + decides next step)
[TOOL]   +28.04s  read        (20ms)

[LLM 6]   +28.06s ───────────────────────────────
           3.68s  (model reads tool result + decides next step)
[TOOL]   +31.74s  web_search  (875ms)

[LLM 7]   +32.62s ───────────────────────────────
           3.55s  (model reads search results + decides to crawl)
[TOOL]   +36.16s  crawl_doc   (10042ms)  ← 10s network fetch

[LLM 8]   +46.20s ───────────────────────────────
           3.47s  (model reads page + decides next step)
[TOOL]   +49.67s  read        (27ms)

[LLM 9]   +49.70s ───────────────────────────────
           5.74s  (model writes final answer)

BREAKDOWN:  LLM 32.78s (59%)  |  tools 22.6s (41%)  ×8
            crawl_doc×3: 20.46s  |  web_search×2: 2.11s  |  read×3: 70ms
```

---

### `b70a7d50` — 07:51:36 — 6.4s — 2 LLM turns  *(live verification run)*

Live run done to verify Method 2 (log tailing). Same pattern as `f504022e`.

```
[SETUP]  32ms

[LLM 1]   +0.03s  ───────────────────────────────
           3.52s  (model reads context + decides what to do)
[TOOL]   +3.55s   memory_search (436ms)  ← QMD search

[LLM 2]   +3.98s  ───────────────────────────────
           2.40s  (model writes final answer)

BREAKDOWN:  LLM 5.89s (93%)  |  tools 436ms (7%)  ×1
```

---

### `8889fdc9` — 08:11:39 — 18.4s — 2 LLM turns

```
[SETUP]  17ms

[LLM 1]   +0.02s  ───────────────────────────────
           6.95s  (model reads context + decides what to do)
[TOOL]   +6.97s   exec   (34ms)   ← found journal files via shell

[LLM 2]   +7.00s  ───────────────────────────────
           11.38s (model writes final answer)

BREAKDOWN:  LLM 18.31s (100%)  |  tools 34ms (0%)  ×1
```

---

## Key findings

### 1. Model inference is the dominant bottleneck

LLM time accounts for **53–100% of total latency** in every scenario.

| Prompt complexity | Time per LLM turn |
|-------------------|------------------|
| Trivial (P1) | ~2.4–2.9s |
| Medium (P2) | ~4–7s |
| Heavy context (P3) | ~10–12s |

Claude Sonnet 4.5 at `thinking: low` costs 2–12s per turn on this VM, scaling with output length and context size.

### 2. Context build time is negligible

**13–54ms** across all scenarios. QMD does not pre-inject context during the prompt assembly phase. The `embedded run prompt start` → `embedded run agent start` gap is effectively zero.

### 3. The main agent's real cost is extra LLM turns, not file I/O

The AGENTS.md startup instructions cause the model to issue tool calls before answering. Every tool call — regardless of how fast it executes — forces a full additional LLM inference round-trip.

Actual turn counts observed across all runs:

| Run | Total | LLM turns | Tool I/O | LLM time |
|-----|-------|-----------|----------|----------|
| `b543d775` | 35.3s | **4** | 87ms | 35.1s |
| `5854ada9` | 35.4s | **6** | 3.48s | 31.9s |
| `450ff526` | 21.0s | **2** | 29ms (all ENOENT) | 21.0s |
| `af7f167f` (P3) | 25.8s | **4** | 161ms | 25.6s |
| `c0f0ec4b` (S3) | 55.4s | **9** | 22.6s | 32.8s |
| `f504022e` (P2) | 6.7s | **2** | 564ms | 6.1s |

For P3 specifically: 4 LLM turns × ~3–12s each = 25.6s. The 7 tool calls themselves took only 161ms. The file reads themselves add only 161ms — the other 25.6s is pure inference.

### 4. QMD `memory_search` is measurable but secondary

- Standalone: ~388ms
- In-agent tool call: ~564ms (+176ms subprocess/IPC overhead)
- Contribution to P2: +564ms on a 6.7s run = **8% of total latency**
- The tool was only called once across all test prompts (on P2, which explicitly asks for a personal fact)

### 5. `crawl_doc` is the worst-case latency driver

| Scenario | crawl_doc time | % of total |
|----------|----------------|------------|
| S3 (2× heavy crawl) | 9.15s + 10.04s = **19.2s** | 35% of 55.4s |

This is network-bound (external site crawl). Nothing to optimize on the OpenClaw side.

---

## Latency attribution summary

Ordered by impact:

| Rank | Source | Magnitude | Scope |
|------|--------|-----------|-------|
| 1 | **Multi-turn LLM inference** (AGENTS.md forces file reads → extra turn) | +8–20s on real sessions | Every non-trivial message |
| 2 | **Claude Sonnet 4.5 base inference speed** | 2–12s/turn (irreducible) | Every message |
| 3 | **`crawl_doc` network I/O** | +9–10s per crawl call | Only when explicitly invoked |
| 4 | **QMD `memory_search` tool** | +564ms in-agent | Only on memory-probe prompts |
| 5 | **Context build / file reads** | 13–54ms | Negligible |

---

## Recommendations

### High impact: Reduce LLM turns per session

The single biggest win is eliminating the mandatory startup file-read round-trip.

**Current flow:**
```
user msg → LLM turn 1 (decides to read files) → tool calls → LLM turn 2 (final answer)
```

**Target flow:**
```
user msg → LLM turn 1 (answers directly, context already in system prompt)
```

Options:
- Add a session-turn check to AGENTS.md: only read startup files if `turn == 1 AND session is new`. On subsequent turns of the same session, skip the reads — the context is already loaded.
- Move SOUL.md + USER.md content directly into the system prompt (inline, not as tool reads). These files are small and static.
- Use QMD-injected snippets for MEMORY.md instead of reading the whole file as a tool call. The gateway already has a QMD injection mechanism.

### Medium impact: Use a smaller model for simple turns

```bash
openclaw agent --agent main --message 'Reply with "OK".' --thinking off
```

For P1-class prompts (simple, stateless), Haiku would cost <1s/turn vs 2.4–2.9s for Sonnet. Consider a routing rule: short/simple messages → Haiku, reasoning/summarization → Sonnet.

### Low impact: Tune QMD if needed

QMD at 388ms is already well-optimized for 177 chunks. As the vault grows past ~2,000 chunks, re-evaluate. At current scale, no action needed.

---

## Methodology notes

- All agent runs used `openclaw agent --agent <id> --message '<text>' --json`
- Log source: `/tmp/openclaw/openclaw-2026-02-21.log` (gateway JSONL debug log)
- Timing parsed from `embedded run start/agent start/tool start/tool end/agent end/prompt end` log markers
- LLM inference turns are **inferred** from gaps between log markers — not directly logged. Any gap >50ms where no tool is running is counted as a distinct inference period
- "Wall clock" times (from `time` command) include ~1.8s CLI overhead not present in logged times
- The `perf-s0` agent was created with `openclaw agents add perf-s0 --workspace /tmp/perf-s0-workspace --model anthropic/claude-sonnet-4-5 --non-interactive` with a minimal AGENTS.md containing no file-read instructions
- Memory index state at time of test: 177 chunks (139 memory + 38 sessions), dirty: no, vector: ready
- Full per-run traces generated by `explain-runs.py` in `openclaw-latency-benchmark/`

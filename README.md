# gabrielle-workspace

Research, benchmarks, and tooling from Gabrielle's OpenClaw setup.

## Contents

| Folder | Description |
|--------|-------------|
| [`openclaw-latency-benchmark/`](./openclaw-latency-benchmark/) | Latency profiling scripts and findings for OpenClaw (TTFT, LLM turns, QMD, tool call attribution) |

## openclaw-latency-benchmark

Measured TTFT and total latency across 4 scenarios (model-only, QMD memory, heavy context, web tools) and reconstructed every agent run step-by-step from gateway logs.

**Key finding:** LLM inference accounts for 53–100% of latency. Each tool call forces a full additional inference round-trip (~3–12s). QMD search adds ~564ms per call. `crawl_doc` is the worst-case outlier at 9–10s per fetch.

→ See [`openclaw-latency-benchmark/README.md`](./openclaw-latency-benchmark/README.md) for full details and how to run the scripts.

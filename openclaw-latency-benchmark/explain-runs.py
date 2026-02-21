#!/usr/bin/env python3
"""
Reads the OpenClaw gateway log and for each completed agent run shows:
  - Every inference gap (model is thinking)
  - Every tool call (name + duration + what was passed)
  - A plain-English reconstruction of what the agent did and why it took that long
"""

import json, re, sys
from datetime import datetime
from pathlib import Path

LOG = Path(f"/tmp/openclaw/openclaw-2026-02-21.log")

def ts(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))
def ms(a, b): return round((ts(b) - ts(a)).total_seconds() * 1000)
def sec(a, b): return round((ts(b) - ts(a)).total_seconds(), 2)

# ── Parse ──────────────────────────────────────────────────────────────────────
runs = {}
order = []

with open(LOG) as f:
    for line in f:
        try:
            d = json.loads(line.strip())
            msg = str(d.get("1", ""))
            t   = d["_meta"]["date"]

            if "embedded run start:" in msg:
                m = re.search(r"runId=(\S+).*sessionId=(\S+?)(?:\s|$)", msg)
                mm = re.search(r"model=(\S+)", msg)
                if m:
                    rid = m.group(1)
                    runs[rid] = {
                        "start": t, "session": m.group(2)[:16],
                        "model": mm.group(1) if mm else "?",
                        "events": [("run_start", t, None)],
                        "tools": [],
                    }
                    order.append(rid)

            elif "embedded run prompt start:" in msg:
                m = re.search(r"runId=(\S+)", msg)
                if m and m.group(1) in runs:
                    runs[m.group(1)]["events"].append(("prompt_start", t, None))

            elif "embedded run agent start:" in msg:
                m = re.search(r"runId=(\S+)", msg)
                if m and m.group(1) in runs:
                    runs[m.group(1)]["events"].append(("agent_start", t, None))
                    runs[m.group(1)]["agent_start"] = t

            elif "embedded run tool start:" in msg:
                m = re.search(r"runId=(\S+).*tool=(\S+).*toolCallId=(\S+)", msg)
                if m and m.group(1) in runs:
                    entry = {"name": m.group(2), "call_id": m.group(3), "start": t}
                    runs[m.group(1)]["tools"].append(entry)
                    runs[m.group(1)]["events"].append(("tool_start", t, entry))

            elif "embedded run tool end:" in msg:
                m = re.search(r"runId=(\S+).*toolCallId=(\S+)", msg)
                if m and m.group(1) in runs:
                    for tool in reversed(runs[m.group(1)]["tools"]):
                        if tool.get("call_id") == m.group(2) and "end" not in tool:
                            tool["end"] = t
                            runs[m.group(1)]["events"].append(("tool_end", t, tool))
                            break

            elif "embedded run agent end:" in msg:
                m = re.search(r"runId=(\S+)", msg)
                if m and m.group(1) in runs:
                    runs[m.group(1)]["events"].append(("agent_end", t, None))
                    runs[m.group(1)]["agent_end"] = t

            elif "embedded run prompt end:" in msg:
                m = re.search(r"runId=(\S+).*durationMs=(\d+)", msg)
                if m and m.group(1) in runs:
                    runs[m.group(1)]["total_ms"] = int(m.group(2))
                    runs[m.group(1)]["events"].append(("prompt_end", t, m.group(2)))

        except: pass

# ── Render ─────────────────────────────────────────────────────────────────────
TOOL_DESC = {
    "read":           "read file from disk",
    "exec":           "run a shell command",
    "memory_search":  "search QMD memory index",
    "memory_get":     "read a specific memory file",
    "web_search":     "search the web",
    "crawl_doc":      "crawl a web page",
    "write":          "write file to disk",
    "list":           "list directory",
}

completed = [rid for rid in order if "total_ms" in runs[rid]]
print(f"Found {len(completed)} completed run(s) in today's log.\n")

for rid in completed:
    r = runs[rid]
    t0 = ts(r["start"])
    total = r["total_ms"]

    print("=" * 70)
    print(f"RUN:     {rid}")
    print(f"SESSION: {r['session']}...")
    print(f"MODEL:   {r['model']}")
    print(f"TOTAL:   {total/1000:.2f}s")
    print("=" * 70)

    # Walk events and reconstruct inference gaps
    events = r["events"]
    agent_start_t = r.get("agent_start")
    agent_end_t   = r.get("agent_end")
    tools         = [t for t in r["tools"] if "end" in t]

    # Ctx build
    if agent_start_t:
        ctx_ms = ms(r["start"], agent_start_t)
        print(f"\n  [SETUP]  session + context assembly: {ctx_ms}ms")

    # Walk through inference gaps and tool calls in chronological order
    if agent_start_t:
        # Build a flat timeline of: inference_start, (tool_start, tool_end)*, inference_end
        # An "inference period" is time between:
        #   - agent_start → first tool_start (or agent_end)
        #   - tool_end[i] → tool_start[i+1] (or agent_end)
        inference_num = 0
        prev_t = agent_start_t

        # Collect all tool call pairs in order
        tool_pairs = [(t["start"], t["end"], t["name"]) for t in tools]

        for i, (ts_start, ts_end, tname) in enumerate(tool_pairs):
            gap = sec(prev_t, ts_start)
            if gap > 0.05:  # >50ms = real inference, not just scheduling
                inference_num += 1
                offset = sec(r["start"], prev_t)
                desc = "model reads context + decides what to do" if inference_num == 1 else "model reads tool result + decides next step"
                print(f"\n  [LLM {inference_num}]   +{offset:.2f}s  ───────────────────────────────")
                print(f"           {gap:.2f}s inference  ({desc})")

            tool_ms = ms(ts_start, ts_end)
            offset = sec(r["start"], ts_start)
            friendly = TOOL_DESC.get(tname, tname)
            print(f"  [TOOL]   +{offset:.2f}s  {tname} ({tool_ms}ms) — {friendly}")
            prev_t = ts_end

        # Final inference after last tool (or the only inference if no tools)
        if agent_end_t:
            gap = sec(prev_t, agent_end_t)
            if gap > 0.05:
                inference_num += 1
                offset = sec(r["start"], prev_t)
                desc = "model writes final answer" if tool_pairs else "model answers directly (no tools)"
                print(f"\n  [LLM {inference_num}]   +{offset:.2f}s  ───────────────────────────────")
                print(f"           {gap:.2f}s inference  ({desc})")

    # Summary
    total_tool_ms = sum(ms(t["start"], t["end"]) for t in tools)
    ctx_ms_val = ms(r["start"], agent_start_t) if agent_start_t else 0
    llm_ms = total - ctx_ms_val - total_tool_ms

    print(f"\n  {'─'*50}")
    print(f"  BREAKDOWN:")
    print(f"    Context build : {ctx_ms_val}ms")
    print(f"    LLM inference : {llm_ms/1000:.2f}s  ({llm_ms/total*100:.0f}% of total)")
    print(f"    Tool calls    : {total_tool_ms/1000:.3f}s  ({total_tool_ms/total*100:.0f}% of total)  ×{len(tools)}")

    if tools:
        by_tool = {}
        for t in tools:
            by_tool.setdefault(t["name"], []).append(ms(t["start"], t["end"]))
        for name, durations in sorted(by_tool.items(), key=lambda x: -sum(x[1])):
            print(f"      {name}: {len(durations)}×  avg={sum(durations)//len(durations)}ms  total={sum(durations)}ms")

    print()

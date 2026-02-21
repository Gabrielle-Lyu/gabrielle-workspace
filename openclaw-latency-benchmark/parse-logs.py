#!/usr/bin/env python3
"""
parse-logs.py
Parses the OpenClaw gateway JSONL log and extracts per-phase timing for every
agent run. Produces a summary table and per-run tool breakdowns.

Usage:
    python3 parse-logs.py
    python3 parse-logs.py --log /tmp/openclaw/openclaw-2026-02-21.log
    python3 parse-logs.py --log /tmp/openclaw/openclaw-2026-02-21.log --since 07:25:00
    python3 parse-logs.py --csv > results.csv
"""

import json
import re
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_LOG = Path("/tmp/openclaw") / f"openclaw-{datetime.now().strftime('%Y-%m-%d')}.log"


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def parse_log(log_path: Path, since_time: str | None = None) -> dict:
    runs: dict = {}
    run_order: list = []

    since_dt = None
    if since_time:
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT")
        since_dt = datetime.fromisoformat(f"{today}{since_time}+00:00")

    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue

            try:
                msg = str(d.get("1", ""))
                t = d["_meta"]["date"]
                sub = d["_meta"]["name"].replace('{"subsystem":"', "").rstrip('"} ')

                if since_dt and ts(t) < since_dt:
                    continue

                if "embedded run start:" in msg:
                    m = re.search(r"runId=(\S+).*sessionId=(\S+?)(?:\s|$)", msg)
                    model_m = re.search(r"model=(\S+)", msg)
                    if m:
                        rid = m.group(1)
                        runs[rid] = {
                            "start": t,
                            "session": m.group(2),
                            "model": model_m.group(1) if model_m else "unknown",
                            "tools": [],
                        }
                        run_order.append(rid)

                elif "embedded run agent start:" in msg:
                    m = re.search(r"runId=(\S+)", msg)
                    if m and m.group(1) in runs:
                        runs[m.group(1)]["agent_start"] = t

                elif "embedded run tool start:" in msg:
                    m = re.search(r"runId=(\S+).*tool=(\S+).*toolCallId=(\S+)", msg)
                    if m and m.group(1) in runs:
                        runs[m.group(1)]["tools"].append({
                            "name": m.group(2),
                            "call_id": m.group(3),
                            "start": t,
                        })

                elif "embedded run tool end:" in msg:
                    m = re.search(r"runId=(\S+).*toolCallId=(\S+)", msg)
                    if m and m.group(1) in runs:
                        for tool in reversed(runs[m.group(1)]["tools"]):
                            if tool.get("call_id") == m.group(2) or "end" not in tool:
                                tool["end"] = t
                                break

                elif "embedded run agent end:" in msg:
                    m = re.search(r"runId=(\S+)", msg)
                    if m and m.group(1) in runs:
                        runs[m.group(1)]["agent_end"] = t

                elif "embedded run prompt end:" in msg:
                    m = re.search(r"runId=(\S+).*durationMs=(\d+)", msg)
                    if m and m.group(1) in runs:
                        runs[m.group(1)]["total_ms"] = int(m.group(2))

            except (KeyError, AttributeError):
                continue

    return runs, run_order


def analyze_run(rid: str, r: dict) -> dict:
    if "total_ms" not in r:
        return {}

    total = r["total_ms"]

    ctx_ms = 0
    if "agent_start" in r:
        ctx_ms = round((ts(r["agent_start"]) - ts(r["start"])).total_seconds() * 1000)

    llm_t1 = 0.0
    if "agent_start" in r:
        if r["tools"]:
            llm_t1 = round((ts(r["tools"][0]["start"]) - ts(r["agent_start"])).total_seconds(), 3)
        elif "agent_end" in r:
            llm_t1 = round((ts(r["agent_end"]) - ts(r["agent_start"])).total_seconds(), 3)

    tool_total = sum(
        (ts(t["end"]) - ts(t["start"])).total_seconds()
        for t in r["tools"] if "end" in t
    )

    llm_t2 = 0.0
    if "agent_end" in r and r["tools"]:
        ends = [t["end"] for t in r["tools"] if "end" in t]
        if ends:
            last_tool_end = max(ts(e) for e in ends)
            llm_t2 = round((ts(r["agent_end"]) - last_tool_end).total_seconds(), 3)

    llm_total = llm_t1 + llm_t2
    llm_pct = round(llm_total / total * 1000 * 100, 1) if total > 0 else 0

    return {
        "run_id": rid,
        "time_utc": r["start"][11:19],
        "model": r.get("model", "?"),
        "total_ms": total,
        "ctx_ms": ctx_ms,
        "llm_t1": llm_t1,
        "tool_total": round(tool_total, 3),
        "llm_t2": llm_t2,
        "llm_pct": llm_pct,
        "tool_count": len(r["tools"]),
        "tools": r["tools"],
    }


def print_table(results: list) -> None:
    print(f"\n{'RunID':<22} {'Time':>8} {'Total':>7} {'CtxBld':>7} {'LLM-T1':>8} "
          f"{'Tools':>7} {'#T':>3} {'LLM-T2':>8} {'%LLM':>6}")
    print("─" * 82)
    for r in results:
        print(
            f"{r['run_id'][:22]:<22} "
            f"{r['time_utc']:>8} "
            f"{r['total_ms']/1000:>6.2f}s "
            f"{r['ctx_ms']:>6}ms "
            f"{r['llm_t1']:>7.2f}s "
            f"{r['tool_total']:>6.2f}s "
            f"{r['tool_count']:>3} "
            f"{r['llm_t2']:>7.2f}s "
            f"{r['llm_pct']:>5.1f}%"
        )


def print_tool_breakdown(results: list) -> None:
    has_tools = [r for r in results if r["tool_count"] > 0]
    if not has_tools:
        return
    print("\n═══ Tool Breakdown ═══")
    for r in has_tools:
        print(f"\n  {r['run_id'][:22]} @ {r['time_utc']}")
        for t in r["tools"]:
            dur = (
                f"{(ts(t['end']) - ts(t['start'])).total_seconds() * 1000:.0f}ms"
                if "end" in t else "?ms"
            )
            print(f"    {t['name']:22} {dur}")


def print_csv(results: list) -> None:
    print("run_id,time_utc,model,total_s,ctx_ms,llm_t1_s,tool_total_s,tool_count,llm_t2_s,llm_pct")
    for r in results:
        print(
            f"{r['run_id']},"
            f"{r['time_utc']},"
            f"{r['model']},"
            f"{r['total_ms']/1000:.3f},"
            f"{r['ctx_ms']},"
            f"{r['llm_t1']:.3f},"
            f"{r['tool_total']:.3f},"
            f"{r['tool_count']},"
            f"{r['llm_t2']:.3f},"
            f"{r['llm_pct']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse OpenClaw gateway logs into a latency table.")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG,
                        help=f"Path to gateway JSONL log (default: {DEFAULT_LOG})")
    parser.add_argument("--since", type=str, default=None,
                        help="Only include runs starting after HH:MM:SS (UTC, today)")
    parser.add_argument("--csv", action="store_true",
                        help="Output CSV instead of human-readable table")
    parser.add_argument("--no-tools", action="store_true",
                        help="Skip per-run tool breakdown")
    args = parser.parse_args()

    if not args.log.exists():
        print(f"ERROR: Log file not found: {args.log}", file=sys.stderr)
        print(f"  Try: --log /tmp/openclaw/openclaw-YYYY-MM-DD.log", file=sys.stderr)
        sys.exit(1)

    runs, run_order = parse_log(args.log, args.since)

    results = []
    for rid in run_order:
        analyzed = analyze_run(rid, runs[rid])
        if analyzed:
            results.append(analyzed)

    if not results:
        print("No completed runs found in log.", file=sys.stderr)
        sys.exit(1)

    if args.csv:
        print_csv(results)
    else:
        print(f"\nLog: {args.log}")
        print(f"Runs found: {len(results)}")
        if args.since:
            print(f"Filtered to runs since: {args.since} UTC")
        print_table(results)
        if not args.no_tools:
            print_tool_breakdown(results)

        # Summary stats
        totals = [r["total_ms"] / 1000 for r in results]
        llm_times = [r["llm_t1"] + r["llm_t2"] for r in results]
        tool_times = [r["tool_total"] for r in results]
        print(f"\n═══ Summary ═══")
        print(f"  Total time  — min: {min(totals):.2f}s  max: {max(totals):.2f}s  avg: {sum(totals)/len(totals):.2f}s")
        print(f"  LLM time    — min: {min(llm_times):.2f}s  max: {max(llm_times):.2f}s  avg: {sum(llm_times)/len(llm_times):.2f}s")
        print(f"  Tool time   — min: {min(tool_times):.2f}s  max: {max(tool_times):.2f}s  avg: {sum(tool_times)/len(tool_times):.2f}s")
        print(f"  Context build — typically {min(r['ctx_ms'] for r in results)}–{max(r['ctx_ms'] for r in results)}ms (negligible)")


if __name__ == "__main__":
    main()

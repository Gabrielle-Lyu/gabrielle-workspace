#!/usr/bin/env bash
# run-scenarios.sh
# Runs the 4-scenario latency test matrix against your OpenClaw gateway.
# Records wall-clock time for each (Scenario × Prompt) combination.
# After running, use parse-logs.py to extract per-phase breakdowns from gateway logs.

set -euo pipefail

MAIN_AGENT="${MAIN_AGENT:-main}"
S0_AGENT="${S0_AGENT:-perf-s0}"
LOG_FILE="${LOG_FILE:-/tmp/perf-run-$(date +%Y%m%d-%H%M%S).log}"

# ── Prompts ────────────────────────────────────────────────────────────────────
P1='Reply with "OK".'
P2='What is my favorite GPU? If unknown, say "unknown".'
P3='Summarize the last 2 days of my notes into 5 bullets.'
P_CRAWL='Use your crawler tool to find the current base MSRP of a 2025 Toyota Camry. One line answer only.'

# ── Helpers ───────────────────────────────────────────────────────────────────
run_agent() {
  local scenario="$1"
  local prompt_id="$2"
  local agent="$3"
  local message="$4"

  echo ""
  echo "────────────────────────────────────────"
  echo " $scenario / $prompt_id"
  echo " Agent  : $agent"
  echo " Message: ${message:0:60}..."
  echo "────────────────────────────────────────"
  echo "Start: $(date -u +%H:%M:%S.%3N)"

  local result
  { time result=$(openclaw agent --agent "$agent" --message "$message" --json 2>/dev/null); } 2>&1 | tee -a "$LOG_FILE"

  local reply
  reply=$(echo "$result" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    text = d.get('result',{}).get('payloads',[{}])[0].get('text','(no text)')
    print('Reply:', text[:120])
except Exception as e:
    print('Parse error:', e)
" 2>/dev/null || echo "(could not parse response)")

  echo "$reply"
  echo "End: $(date -u +%H:%M:%S.%3N)"
}

# ── Preflight ─────────────────────────────────────────────────────────────────
echo "========================================"
echo " OpenClaw Scenario Latency Test"
echo " $(date -u)"
echo "========================================"
echo ""
echo "Checking gateway health..."
openclaw health 2>&1 | head -4
echo ""

# Check S0 agent exists; create it if not
if ! openclaw agent --agent "$S0_AGENT" --message 'ping' --json > /dev/null 2>&1; then
  echo "Creating minimal S0 agent ($S0_AGENT)..."
  S0_WS="/tmp/perf-s0-workspace"
  mkdir -p "$S0_WS"
  cat > "$S0_WS/AGENTS.md" << 'AGENTSEOF'
# Minimal Perf Test Agent (S0)

You are a minimal assistant for performance testing.
Do NOT read any files unless explicitly asked.
Do NOT search memory.
Answer directly and concisely.
AGENTSEOF
  openclaw agents add "$S0_AGENT" \
    --workspace "$S0_WS" \
    --model anthropic/claude-sonnet-4-5 \
    --non-interactive \
    --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print('Created agent:', d.get('agentId'))"
else
  echo "S0 agent ($S0_AGENT) already exists — OK"
fi

echo ""
echo "Log file: $LOG_FILE"
echo ""
echo "NOTE: After this script finishes, run parse-logs.py to extract"
echo "      per-phase timings from the gateway log."
echo ""

# ── S0: Model-only (minimal agent) ───────────────────────────────────────────
echo "════════════════════════════════════════"
echo " S0: Model-only (no memory, no tools)"
echo "════════════════════════════════════════"
run_agent "S0" "P1" "$S0_AGENT" "$P1"
run_agent "S0" "P2" "$S0_AGENT" "$P2"
run_agent "S0" "P3" "$S0_AGENT" "$P3"

# ── S1+S2: Main agent (QMD memory + file reads) ───────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo " S1+S2: Main agent (QMD memory + context files)"
echo "════════════════════════════════════════"
run_agent "S1+S2" "P1" "$MAIN_AGENT" "$P1"
run_agent "S1+S2" "P2" "$MAIN_AGENT" "$P2"
run_agent "S1+S2" "P3" "$MAIN_AGENT" "$P3"

# ── S3: Tools (web search + crawl) ────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo " S3: Tools ON (web_search + crawl_doc)"
echo "════════════════════════════════════════"
run_agent "S3" "P_CRAWL" "$MAIN_AGENT" "$P_CRAWL"

echo ""
echo "========================================"
echo " All scenarios complete."
echo " Wall-clock times are above."
echo " Run parse-logs.py for gateway-level breakdown."
echo "========================================"

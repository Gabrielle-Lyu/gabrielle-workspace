#!/usr/bin/env bash
# qmd-benchmark.sh
# Measures raw QMD search latency (isolates memory backend, no agent overhead).
# Run this first to establish your QMD baseline before running agent scenarios.

set -euo pipefail

QMD_BIN="${QMD_BIN:-/home/ubuntu/.bun/bin/qmd}"
VAULT="${VAULT:-/home/ubuntu/openclaw-vault}"
RUNS="${RUNS:-10}"
LIMIT="${LIMIT:-5}"

QUERIES=(
  "pushgateway stress test"
  "favorite gpu"
  "daily notes summary"
)

if [[ ! -x "$QMD_BIN" ]]; then
  echo "ERROR: qmd binary not found at $QMD_BIN"
  echo "Override with: QMD_BIN=/path/to/qmd $0"
  exit 1
fi

if [[ ! -d "$VAULT" ]]; then
  echo "ERROR: vault directory not found at $VAULT"
  echo "Override with: VAULT=/path/to/vault $0"
  exit 1
fi

echo "========================================"
echo " QMD Standalone Latency Benchmark"
echo "========================================"
echo "qmd binary : $QMD_BIN"
echo "vault path : $VAULT"
echo "runs/query : $RUNS"
echo "----------------------------------------"

for query in "${QUERIES[@]}"; do
  echo ""
  echo "Query: \"$query\""
  echo "---"
  times=()
  for i in $(seq 1 "$RUNS"); do
    ms=$( { time "$QMD_BIN" search "$VAULT" "$query" --limit "$LIMIT" > /dev/null 2>&1; } 2>&1 \
        | grep real | awk '{
            split($2, a, "m"); 
            split(a[2], b, "s"); 
            printf "%.0f", (a[1]*60 + b[1])*1000
          }' )
    times+=("$ms")
    printf "  run %2d: %dms\n" "$i" "$ms"
  done

  # Stats via awk
  echo "${times[@]}" | tr ' ' '\n' | awk '
    BEGIN { min=999999; max=0; sum=0; n=0 }
    { sum+=$1; if($1<min) min=$1; if($1>max) max=$1; n++ }
    END { printf "  → min=%dms  max=%dms  avg=%dms\n", min, max, sum/n }
  '
done

echo ""
echo "========================================"
echo " Interpretation"
echo "========================================"
echo " < 200ms : QMD is not your bottleneck"
echo " 200-500ms: Noticeable, watch it as vault grows"
echo " > 500ms  : QMD is adding meaningful TTFT overhead"
echo "========================================"

#!/usr/bin/env bash
# Engine benchmark on a cheap GPU before the paid run (RTX 5090 + Qwen3.5-9B: same architecture as 27B, same
# Blackwell generation as the Pro 6000). Step 0's F/S/I trajectories on all 12 tasks, four ways:
#   A  prompt store off (every prompt read whole, the probe read and the generation each reading it): the old engine
#   B  prompt store on
#   C  B + flash-linear-attention kernels (Qwen3.5's linear-attention layers; Triton, no compile)
#   D  C at twice the batch
# bench_report.py compares speed and, against A, whether the same rows produced the same text and probe states.
# Nothing here is experiment data: outputs stay in /workspace/bench; the report goes to /vault/work/logs/bench.md.
#
#   gputw.py run <id> --name bench -- bash /vault/work/research/cloud/jobs/bench.sh
#   MODEL_ID=Qwen/Qwen3.5-27B BATCH=24 ... on the Pro 6000
set -uo pipefail
ROOT=${ROOT:-/vault/work}
PY=${PY:-/workspace/venv/bin/python}
MODEL_ID=${MODEL_ID:-Qwen/Qwen3.5-9B}
BATCH=${BATCH:-16}
B=/workspace/bench
export PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 HF_HOME=${HF_HOME:-/workspace/hf}
cd "$ROOT" || exit 1
mkdir -p "$B" logs
mark() { echo "[$(date -u +%FT%TZ)] $*"; }

mark "environment"
[ -x "$PY" ] || HF_HOME=$ROOT/hf bash research/cloud/bootstrap.sh || exit 1
M=/workspace/models/$(basename "$MODEL_ID")
mark "weights → $M"
mkdir -p "$M" && rsync -aL --partial "$ROOT/models/$(basename "$MODEL_ID")/" "$M/" || exit 1
"$PY" -m pip uninstall -y -q flash-linear-attention fla-core 2>/dev/null

one() {  # one <label> <batch> [VAR=value ...]
  local label=$1 batch=$2 start; shift 2
  rm -rf "$B/$label" "$B/$label".*
  mark "run $label (batch $batch${*:+, $*})"
  start=$(date +%s.%N)
  env ENGINE_METRICS="$B/$label.metrics.json" "$@" "$PY" research/experiments/pressure.py run --backend torch --model "$M" --batch "$batch" --out "$B/$label" > "$B/$label.log" 2>&1
  echo "$? $(awk -v s="$start" -v e="$(date +%s.%N)" 'BEGIN { printf "%.1f", e - s }')" > "$B/$label.exit"
  mark "run $label: exit $(cut -d' ' -f1 "$B/$label.exit"), $(cut -d' ' -f2 "$B/$label.exit") s"
}

one A "$BATCH" ENGINE_PROMPT_STORE_GB=0
one B "$BATCH"
mark "flash-linear-attention"
"$PY" -m pip install -q flash-linear-attention > "$B/fla-install.log" 2>&1 || mark "fla install failed (see $B/fla-install.log)"
one C "$BATCH"
one D "$((BATCH * 2))"
"$PY" research/cloud/jobs/bench_report.py "$B" "$MODEL_ID" A B C D | tee logs/bench.md
mark "DONE"

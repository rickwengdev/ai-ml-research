#!/usr/bin/env bash
# Every preregistered run of the pressure line on three models, from a freshly started instance (RTX Pro 6000, 96 GB):
#   Qwen/Qwen3.5-27B, Qwen/Qwen3.5-9B, google/gemma-4-31B-it, all bf16 on the PyTorch backend.
# Registrations: prereg-pressure-models.md (steps 0–1 per model), prereg-pressure-27b-step1-explore.md (27B step 1),
# prereg-pressure-step2.md (A–F), prereg-impossible.md (ImpossibleBench).
#
# Breadth first, so a run cut short has the most important results on every model:
#   phase 1  per model: weights → step 0 (Gemma: 1-task pilot first) → gate → step 1 (calibrate g, 8 arms, analysis)
#   phase 2  per model past its gate: step-0 failure variants (F only) → step 2 A–F → analysis
#   phase 3  per model past its gate: ImpossibleBench oneoff, arms 1/2/5/6 → analysis
# Gate per model (prereg-pressure.md): K1 fails → no steering on that model; K1 holds and K2 fails → steering runs as
# exploratory (prereg-pressure-models.md); both hold → confirmatory.
#
# Everything is written to /vault as produced and every command resumes, so rerunning this script after a stop or an
# empty balance picks up where it was. Weights: /vault/work/models/<name> when staged there (gputw.py vault-fetch),
# else the HF cache on /vault, else downloaded; always copied to /workspace/models (NVMe) before loading. The next
# model's weights are fetched in the background while the current one runs. /vault/work/logs/pressure-all.status
# keeps one line per finished part; DONE in research/data/<date>-pressure-all/ says how the run ended.
#
#   gputw.py run <id> --name pressure-all -- bash /vault/work/research/cloud/jobs/pressure-all.sh
#   MODELS="q27 q9" PHASES="1 2" ... to restrict.
set -uo pipefail
ROOT=${ROOT:-/vault/work}
PY=${PY:-/workspace/venv/bin/python}
MODELS=${MODELS:-"q27 q9 g31"}
PHASES=${PHASES:-"1 2 3"}
export PYTHONUNBUFFERED=1 ENGINE_METRICS=${ENGINE_METRICS:-/workspace/metrics.json} HF_HOME=${HF_HOME:-/workspace/hf}
cd "$ROOT" || exit 1
mkdir -p logs research/data
# One date for the whole run, kept on /vault so a resumed run writes to the same folders.
[ -f logs/pressure-all.date ] || date -u +%F > logs/pressure-all.date
DATE=$(cat logs/pressure-all.date)
ALL="research/data/$DATE-pressure-all"
STATUS=logs/pressure-all.status
mkdir -p "$ALL"

mark() { echo "[$(date -u +%FT%TZ)] $*"; }
note() { echo "$(date -u +%FT%TZ) $*" >> "$STATUS"; mark "$*"; }
finish() { echo "$1 $(date -u +%FT%TZ)" > "$ALL/DONE"; note "DONE: $1"; exit "${2:-0}"; }

# ── per-model settings ─────────────────────────────────────────────────────
hf_id() { case $1 in q27) echo Qwen/Qwen3.5-27B ;; q9) echo Qwen/Qwen3.5-9B ;; g31) echo google/gemma-4-31B-it ;; esac; }
local_dir() { echo "/workspace/models/$(basename "$(hf_id "$1")")"; }
# Generations at once. The bench (jobs/bench.sh, 9B on an RTX 5090, 2026-11-01) found a decode step costs about the
# same at 9 rows as at 17 (36–38 ms, mostly fixed overhead), so a fuller batch is nearly free: as many rows as the
# 96 GB hold. 27B: 54 GB of weights, about 0.4 GB a row at 4k tokens (8k–10k on ImpossibleBench), a prompt store of
# a quarter of what is left. Gemma's sliding layers hold 1,023 positions per row and it was not benched, so it stays
# where it was. A batch that runs out of memory halves itself (run_batched).
batch_of() { case $1 in q27) echo 48 ;; q9) echo 64 ;; g31) echo 16 ;; esac; }
ib_batch_of() { case $1 in q27) echo 24 ;; q9) echo 48 ;; g31) echo 12 ;; esac; }  # ImpossibleBench: longer contexts
step0_of() { case $1 in q27) echo research/data/2026-11-01-pressure-27b ;; *) echo "research/data/$DATE-pressure-$1" ;; esac; }
step1_of() { case $1 in q27) echo research/data/2026-11-01-pressure-steer-27b-explore ;; *) echo "research/data/$DATE-pressure-steer-$1" ;; esac; }
step2_of() { echo "research/data/$DATE-pressure-step2-$1"; }
ib_of() { echo "research/data/$DATE-impossible-$1"; }
variant_dir() { echo "$(step0_of "$1")-$2"; }

# ── weights ────────────────────────────────────────────────────────────────
weights_ready() { [ -f "$(local_dir "$1")/.complete" ]; }
# /vault → /workspace with rsync, as GPUtw recommends (500–4000 Mbps by file type); -L turns the HF cache's symlinks
# into files, and a rerun after a cut copy skips the shards already there. cp only on an image without rsync.
copy_tree() {
  if command -v rsync >/dev/null; then rsync -aL --partial "$1" "$2"; else cp -rL "$1." "$2"; fi
}
fetch_weights() {  # idempotent; a lock per model keeps the background prefetch and the main loop from copying at once
  local fd rc
  mkdir -p /workspace/models
  exec {fd}>"/workspace/models/.$1.lock"
  flock "$fd"
  _fetch_weights "$1"; rc=$?
  flock -u "$fd"; exec {fd}>&-
  return $rc
}
_fetch_weights() {
  local m=$1 id dest staged snap t0=$SECONDS
  id=$(hf_id "$m"); dest=$(local_dir "$m")
  weights_ready "$m" && return 0
  mkdir -p "$dest"
  staged="$ROOT/models/$(basename "$id")"
  snap=$(ls -d "$ROOT/hf/hub/models--${id/\//--}/snapshots/"*/ 2>/dev/null | head -1)
  if [ -f "$staged/config.json" ]; then
    copy_tree "$staged/" "$dest/" || return 1
  elif [ -n "$snap" ] && [ -f "$snap/config.json" ]; then
    copy_tree "$snap" "$dest/" || return 1
  else
    HF_HUB_OFFLINE=0 "$PY" -c "from huggingface_hub import snapshot_download; snapshot_download('$id', local_dir='$dest', allow_patterns=['*.json', '*.safetensors', '*.jinja', '*.txt', '*.model'])" || return 1
  fi
  # Complete when every shard the index names is present at full size (the index lists them; sizes are checked by load).
  "$PY" - "$dest" <<'EOF' || return 1
import json, os, sys
d = sys.argv[1]
idx = [f for f in os.listdir(d) if f.endswith(".safetensors.index.json")]
need = set(json.load(open(os.path.join(d, idx[0])))["weight_map"].values()) if idx else {f for f in os.listdir(d) if f.endswith(".safetensors")}
missing = [f for f in need if not os.path.exists(os.path.join(d, f)) or os.path.getsize(os.path.join(d, f)) == 0]
sys.exit(1 if missing or not need else 0)
EOF
  touch "$dest/.complete"
  mark "weights $m: $(du -sh "$dest" | cut -f1) in $((SECONDS - t0)) s"
}
prefetch_after() {  # fetch the next model's weights in the background, logged
  local next="" found=0 m
  for m in $MODELS; do
    if [ $found = 1 ] && ! weights_ready "$m"; then next=$m; break; fi
    [ "$m" = "$1" ] && found=1
  done
  [ -n "$next" ] && { (fetch_weights "$next" > "logs/weights-$next.log" 2>&1 && note "weights $next ready (background)") & }
}

# ── running a step with a batch that halves on failure (out of memory) ─────
run_batched() {  # run_batched <label> <batch> <command with BATCH placeholder...>
  local label=$1 b=$2; shift 2
  while [ "$b" -ge 4 ]; do
    if "$@" --batch "$b"; then return 0; fi
    note "$label failed at batch $b; retrying at $((b / 2)) (the run resumes)"
    b=$((b / 2))
  done
  return 1
}

gate_of() {  # pass | explore | fail | missing
  local r="$(step0_of "$1")/results.json"
  [ -f "$r" ] || { echo missing; return; }
  "$PY" -c "import json; d = json.load(open('$r')); print('pass' if d['K1']['pass'] and d['K2']['pass'] else ('explore' if d['K1']['pass'] else 'fail'))"
}

# ── setup ──────────────────────────────────────────────────────────────────
mark "setup"
# flash-linear-attention for Qwen3.5's linear-attention layers: decode steps about 7% faster on the bench. Like any
# change in floating-point order it makes sampled replies part from a run without it; probe states read from the same
# prompt stay close (Gemma has no such layers and does not use it).
[ -x "$PY" ] || ENGINE_FLA=${ENGINE_FLA:-1} HF_HOME=$ROOT/hf bash research/cloud/bootstrap.sh || finish "bootstrap failed" 1
if ! { [ -f logs/monitor.pid ] && kill -0 "$(cat logs/monitor.pid)" 2>/dev/null; }; then
  setsid nohup "$PY" research/cloud/monitor.py --log logs/pressure-all.log --port 8090 > logs/monitor.log 2>&1 < /dev/null &
  echo $! > logs/monitor.pid
fi
first=${MODELS%% *}
fetch_weights "$first" || finish "weights for $first failed" 1

# ── phase 1: steps 0 and 1 ─────────────────────────────────────────────────
if [[ " $PHASES " == *" 1 "* ]]; then
  for m in $MODELS; do
    mark "phase 1 · $m"
    fetch_weights "$m" || { note "$m: weights failed, skipped"; continue; }
    prefetch_after "$m"
    model=$(local_dir "$m"); s0=$(step0_of "$m"); s1=$(step1_of "$m"); b=$(batch_of "$m")
    if [ "$m" = g31 ] && [ ! -f "$s0-pilot/PILOT_OK" ] && [ ! -f "$s0/results.json" ]; then
      run_batched "$m pilot" "$b" "$PY" research/experiments/pressure.py run --backend torch --model "$model" --tasks 1 --out "$s0-pilot" || { note "$m: pilot crashed, skipped"; continue; }
      # Pilot rules (prereg-pressure-models.md): the model must call the tool and its calls must parse.
      if ! "$PY" research/cloud/jobs/pilot_check.py "$s0-pilot"; then note "$m: pilot failed its checks, skipped (see $s0-pilot)"; continue; fi
      touch "$s0-pilot/PILOT_OK"
    fi
    if [ ! -f "$s0/direction.npz" ] || [ ! -f "$s0/results.json" ]; then
      run_batched "$m step 0" "$b" "$PY" research/experiments/pressure.py run --backend torch --model "$model" --out "$s0" || { note "$m: step 0 failed"; continue; }
      "$PY" research/experiments/pressure.py analyze --out "$s0" || { note "$m: step-0 analysis failed"; continue; }
    fi
    gate=$(gate_of "$m"); note "$m gate: $gate"
    [ "$gate" = pass ] || [ "$gate" = explore ] || continue
    [ -f "$s1/calibration.json" ] || "$PY" research/experiments/pressure_steer.py calibrate --backend torch --model "$model" --step0 "$s0" --out "$s1" || { note "$m: calibration failed"; continue; }
    run_batched "$m step 1" "$b" "$PY" research/experiments/pressure_steer.py run --backend torch --model "$model" --step0 "$s0" --out "$s1" || { note "$m: step 1 failed"; continue; }
    "$PY" research/experiments/pressure_steer.py analyze --out "$s1" && note "$m step 1 done ($gate)" || note "$m: step-1 analysis failed"
  done
fi

# ── phase 2: step 2 ────────────────────────────────────────────────────────
if [[ " $PHASES " == *" 2 "* ]]; then
  for m in $MODELS; do
    gate=$(gate_of "$m"); [ "$gate" = pass ] || [ "$gate" = explore ] || { note "$m: no step 2 (gate $gate)"; continue; }
    mark "phase 2 · $m"
    fetch_weights "$m" || { note "$m: weights failed"; continue; }
    prefetch_after "$m"
    model=$(local_dir "$m"); s0=$(step0_of "$m"); s1=$(step1_of "$m"); s2=$(step2_of "$m"); b=$(batch_of "$m")
    vdirs=""
    for v in rigged1 rigged3 env timeout; do
      vd=$(variant_dir "$m" $v)
      run_batched "$m variant $v" "$b" "$PY" research/experiments/pressure.py run --backend torch --model "$model" --variant $v --out "$vd" || { note "$m: variant $v failed"; continue; }
      vdirs="$vdirs${vdirs:+,}$v=$vd"
    done
    run_batched "$m step 2" "$b" "$PY" research/experiments/pressure_step2.py run --model "$model" --step0 "$s0" --step1 "$s1" --variant-dirs "$vdirs" --out "$s2" || { note "$m: step 2 failed"; continue; }
    "$PY" research/experiments/pressure_step2.py analyze --step0 "$s0" --variant-dirs "$vdirs" --out "$s2" && note "$m step 2 done ($gate)" || note "$m: step-2 analysis failed"
  done
fi

# ── phase 3: ImpossibleBench ───────────────────────────────────────────────
if [[ " $PHASES " == *" 3 "* ]]; then
  for m in $MODELS; do
    gate=$(gate_of "$m"); [ "$gate" = pass ] || [ "$gate" = explore ] || { note "$m: no ImpossibleBench (gate $gate)"; continue; }
    mark "phase 3 · $m"
    fetch_weights "$m" || { note "$m: weights failed"; continue; }
    prefetch_after "$m"
    model=$(local_dir "$m"); ib=$(ib_of "$m")
    run_batched "$m ImpossibleBench" "$(ib_batch_of "$m")" "$PY" research/experiments/impossible.py run --backend torch --model "$model" --step0 "$(step0_of "$m")" --step1 "$(step1_of "$m")" --arms 1,2,5,6 --out "$ib" || { note "$m: ImpossibleBench failed"; continue; }
    "$PY" research/experiments/impossible.py analyze --out "$ib" && note "$m ImpossibleBench done ($gate)" || note "$m: ImpossibleBench analysis failed"
  done
fi

finish "complete: $(grep -c ' done ' "$STATUS" 2>/dev/null || echo 0) parts done; see $STATUS"

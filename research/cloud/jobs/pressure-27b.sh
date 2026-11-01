#!/usr/bin/env bash
# The pressure line on Qwen3.5-27B bf16 (research/prereg/prereg-pressure-27b.md), from a freshly started instance:
#   1. the Python environment on /workspace (gone after every stop)        bootstrap.sh, about 2 min
#   2. the weights copied from /vault to the local NVMe (gone after a stop)  about 11 min, once
#   3. the live monitor (research/cloud/monitor.py) on 127.0.0.1:8090
#   4. step 0's analysis and its preregistered gate: K1 and K2 must both hold, else stop here (no step 1)
#   5. step 1: calibrate the uniform gain g on 27B before any data, the eight arms (continuous batching), analysis
# Every result is written under /vault as it is produced (rows per step, probe states per read), so a stop or an
# empty balance loses at most what was in flight. Rerunning the script resumes: finished parts are skipped.
# A file DONE in the step-1 folder says how it ended. Start it with:
#   gputw.py run <id> --name pressure-27b -- bash /vault/work/research/cloud/jobs/pressure-27b.sh
# The exploratory step 1 after K2 failed (prereg-pressure-27b-step1-explore.md):
#   ... -- env GATE=k1 PREREG=research/prereg/prereg-pressure-27b-step1-explore.md STEP1=research/data/2026-11-01-pressure-steer-27b-explore bash .../pressure-27b.sh
# The instance holds no API key and cannot stop itself: deploy with --hours as a cap and stop it from the laptop once
# DONE exists (research/cloud/README.md, 一鍵任務).
set -uo pipefail
ROOT=${ROOT:-/vault/work}
PY=${PY:-/workspace/venv/bin/python}
MODEL=${MODEL:-/workspace/models/Qwen3.5-27B}
SNAPSHOTS=${SNAPSHOTS:-/vault/work/hf/hub/models--Qwen--Qwen3.5-27B/snapshots}
STEP0=${STEP0:-research/data/2026-11-01-pressure-27b}
STEP1=${STEP1:-research/data/2026-11-01-pressure-steer-27b}
BATCH=${BATCH:-24}
# The preregistered gate is K1 and K2 (prereg-pressure.md). GATE=k1 runs step 1 when only K1 holds; it needs PREREG,
# the exploratory registration written before the data (prereg-pressure-27b-step1-explore.md).
GATE=${GATE:-k1k2}
PREREG=${PREREG:-}
export HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1 ENGINE_METRICS=${ENGINE_METRICS:-/workspace/metrics.json}
cd "$ROOT" || exit 1
mark() { echo "[$(date -u +%FT%TZ)] $*"; }
finish() { mkdir -p "$STEP1"; echo "$1 $(date -u +%FT%TZ)" > "$STEP1/DONE"; mark "DONE: $1"; exit "${2:-0}"; }

mark "1/5 environment"
[ -x "$PY" ] || HF_HOME=/vault/work/hf bash research/cloud/bootstrap.sh || finish "bootstrap failed" 1

mark "2/5 weights"
if [ ! -f "$MODEL/config.json" ] || [ "$(ls "$MODEL"/model.safetensors-*.safetensors 2>/dev/null | wc -l)" -lt 11 ]; then
  SNAP=$(ls -d "$SNAPSHOTS"/*/ | head -1)
  mkdir -p "$MODEL"
  # rsync from /vault, as GPUtw recommends; -L turns the HF cache symlinks into files, a rerun skips finished shards.
  rsync -aL --partial "$SNAP" "$MODEL"/ || finish "weights copy failed" 1
fi
mark "weights $(du -sh "$MODEL" | cut -f1)"

mark "3/5 monitor"
if ! { [ -f /vault/work/logs/monitor.pid ] && kill -0 "$(cat /vault/work/logs/monitor.pid)" 2>/dev/null; }; then
  setsid nohup "$PY" research/cloud/monitor.py --out "$ROOT/$STEP1" --log /vault/work/logs/pressure-27b.log --expected 506 --port 8090 > /vault/work/logs/monitor.log 2>&1 < /dev/null &
  echo $! > /vault/work/logs/monitor.pid
fi

mark "4/5 step 0 analysis and gate"
[ -f "$STEP0/direction.npz" ] && [ -f "$STEP0/results.json" ] || "$PY" research/experiments/pressure.py analyze --out "$STEP0" || finish "step-0 analysis failed" 1
if [ "$GATE" = k1 ] && [ ! -f "$PREREG" ]; then finish "GATE=k1 needs PREREG, the exploratory registration" 1; fi
VERDICT=$("$PY" -c "import json; d = json.load(open('$STEP0/results.json')); ok = d['K1']['pass'] and (d['K2']['pass'] or '$GATE' == 'k1'); print('pass' if ok else 'fail K1=%s K2=%s' % (d['K1']['pass'], d['K2']['pass']))")
mark "gate ($GATE${PREREG:+, $PREREG}): $VERDICT"
[ "$VERDICT" = "pass" ] || finish "gate $VERDICT: step 1 not run (preregistered)" 0

mark "5/5 step 1"
mkdir -p "$STEP1"
[ -f "$STEP1/calibration.json" ] || "$PY" research/experiments/pressure_steer.py calibrate --backend torch --model "$MODEL" --step0 "$STEP0" --out "$STEP1" || finish "calibration failed" 1
mark "g = $("$PY" -c "import json; print(round(json.load(open('$STEP1/calibration.json'))['g'], 4))")"
"$PY" research/experiments/pressure_steer.py run --backend torch --model "$MODEL" --step0 "$STEP0" --batch "$BATCH" --out "$STEP1" || finish "step-1 run failed" 1
"$PY" research/experiments/pressure_steer.py analyze --out "$STEP1" || finish "step-1 analysis failed" 1
finish "complete"

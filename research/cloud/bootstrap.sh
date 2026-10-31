#!/usr/bin/env bash
# First-time setup inside a GPUtw container (run after `gputw.py sync <id>`):
#   bash /vault/work/research/cloud/bootstrap.sh [HF model id ...]
# Installs the Python deps for the PyTorch backend into /workspace (fast local disk; the venv is rebuilt per
# instance, which takes about a minute) and pre-downloads the models into /vault/hf so later instances skip it.
set -euo pipefail
ROOT=/vault/work
# Weights on the instance disk (fast); /vault writes at a few MB/s. Persistent copies: console "從網址下載" into the Vault.
export HF_HOME=${HF_HOME:-/workspace/hf}
export PYTHONUNBUFFERED=1
mkdir -p "$HF_HOME" "$ROOT/logs" "$ROOT/research/data"

if ! command -v rsync >/dev/null; then
  (apt-get update && apt-get install -y --no-install-recommends rsync git) >/dev/null
fi

# The PyTorch image keeps its python in conda, not on PATH for non-login shells.
PYTHON=${PYTHON:-$(command -v python3 || command -v python || ls /opt/conda/bin/python3 2>/dev/null | head -1)}
VENV=/workspace/venv
if [ ! -x "$VENV/bin/python" ]; then
  "$PYTHON" -m venv --system-site-packages "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$ROOT/services/model-server/requirements-torch.txt"
# flash-linear-attention / causal-conv1d were tried on a 3090 (2026-11-01): no speedup for single-sequence decoding
# of Qwen3.5-9B (about 20 tok/s either way), so they are not installed; the reference kernels are correct.

"$VENV/bin/python" - <<'EOF'
import torch
print("torch", torch.__version__, "cuda", torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")
EOF

for MODEL in "$@"; do
  echo "downloading $MODEL into $HF_HOME"
  "$VENV/bin/python" -c "from huggingface_hub import snapshot_download; snapshot_download('$MODEL')"
done

cat <<EOF

ready. Run experiments with:
  cd $ROOT && $VENV/bin/python research/experiments/pressure.py run --backend torch --model Qwen/Qwen3.5-27B --out research/data/<date>-pressure-27b
Smoke test the backend:
  cd $ROOT && $VENV/bin/python services/model-server/torch_engine.py --model Qwen/Qwen3.5-0.8B
EOF

#!/usr/bin/env bash
# First-time setup on a rented GPU, after `gputw.py sync <id>` or `gcp.py sync <name>`:
#   bash /vault/work/research/cloud/bootstrap.sh [HF model id ...]
# Runs as root in a GPUtw container and as a normal user (with sudo) on a Google Cloud Deep Learning VM.
# Installs the Python deps for the PyTorch backend into /workspace (fast local disk; the venv is rebuilt per
# instance, which takes about a minute) and pre-downloads the models into /vault/hf so later instances skip it.
set -euo pipefail
ROOT=/vault/work
# Weights on the instance disk (fast); /vault writes at a few MB/s. Persistent copies: gputw.py vault-fetch into the Vault.
export HF_HOME=${HF_HOME:-/workspace/hf}
export PYTHONUNBUFFERED=1
mkdir -p "$HF_HOME" "$ROOT/logs" "$ROOT/research/data"

SUDO=$([ "$(id -u)" = 0 ] || echo sudo)
if ! command -v rsync >/dev/null; then
  # gputw.py sync has usually put one in place already (under /opt/rsync where apt cannot run).
  ($SUDO apt-get update && $SUDO apt-get install -y --no-install-recommends rsync git) >/dev/null || echo "apt could not install rsync"
fi

# The images keep the python that has PyTorch in conda (not on PATH for non-login shells); prefer it.
PYTHON=${PYTHON:-$(ls /opt/conda/bin/python3 2>/dev/null || command -v python3 || command -v python)}
VENV=/workspace/venv
if [ ! -x "$VENV/bin/python" ]; then
  "$PYTHON" -m venv --system-site-packages "$VENV" || { $SUDO apt-get install -y python3-venv >/dev/null && "$PYTHON" -m venv --system-site-packages "$VENV"; }
fi
"$VENV/bin/pip" install --quiet --upgrade pip
# An image without PyTorch (or one whose build cannot see the GPU): a CUDA 12.8 wheel, the first that runs on Blackwell.
if ! "$VENV/bin/python" -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)" 2>/dev/null; then
  "$VENV/bin/pip" install --quiet torch --index-url https://download.pytorch.org/whl/cu128
fi
"$VENV/bin/pip" install --quiet -r "$ROOT/services/model-server/requirements-torch.txt"
# flash-linear-attention / causal-conv1d were tried on a 3090 (2026-11-01): no speedup for single-sequence decoding
# of Qwen3.5-9B (about 20 tok/s either way), so they are not installed by default; the reference kernels are correct.
# Prompt reads (chunked linear attention over thousands of tokens) are where they could matter: jobs/bench.sh
# measures it, and ENGINE_FLA=1 installs the Triton kernels (no compile) once that says they help.
if [ "${ENGINE_FLA:-0}" = 1 ]; then
  "$VENV/bin/pip" install --quiet flash-linear-attention || echo "flash-linear-attention did not install; the reference kernels stay"
fi

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

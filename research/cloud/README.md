# 租用 GPU 跑實驗（GPUtw）

本機的 MLX 後端只在 Mac 上跑得動 9B 4-bit。27B bf16、批次推論、ImpossibleBench 這類工作用租來的 CUDA 機器，透過 `services/model-server/torch_engine.py`（PyTorch 後端）跑同一套實驗腳本。

## 一次性準備

1. 到 [gputw.ai](https://gputw.ai/dashboard) 建 API 金鑰（scopes：`catalog:read`、`instances:read`、`instances:create`、`instances:manage`、`vault:read`、`vault:write`），存到 `~/.config/gputw/key`，`chmod 600`。金鑰不要進 git、不要貼到對話裡。
2. 在控制台「SSH 金鑰」貼上你的公鑰（API 不能加 SSH 金鑰）。
3. 確認 Docker Hub 上 `pytorch/pytorch:2.7.1-cuda12.8-cudnn9-devel` 這個 tag 存在（Blackwell 需要 CUDA 12.8 以上），不存在就改 `gputw.py` 的 `DEFAULT_IMAGE`。

## 一輪實驗的流程

```bash
G=services/model-server/.venv/bin/python research/cloud/gputw.py
$G catalog                                   # 看現在有什麼卡、價格、可租數
$G deploy --gpu "RTX 5090" --hours 12        # 開機：自訂映像、SSH、12 小時後自動停
$G sync <id>                                 # 把 research/ 與 services/model-server/ 送到 /vault/work（不含 venv、資料、圖）
$G push <id> research/data/2026-10-31-pressure /vault/work/research/data/   # 需要的資料目錄
$G ssh <id> -- bash /vault/work/research/cloud/bootstrap.sh Qwen/Qwen3.5-27B  # 裝依賴、預先下載模型到 /vault/hf
$G run <id> --name pressure-27b -- /workspace/venv/bin/python research/experiments/pressure.py run --backend torch --model Qwen/Qwen3.5-27B --out research/data/2026-11-xx-pressure-27b
$G ssh <id> -- tail -f /vault/work/logs/pressure-27b.log
$G fetch <id> /vault/work/research/data/2026-11-xx-pressure-27b research/data/2026-11-xx-pressure-27b
$G stop <id>                                 # 停機就不計費；/workspace 會清掉，/vault 留著
```

## 要記得的事

- 只有 `/vault` 會留下來；模型快取（`HF_HOME=/vault/work/hf`）、結果、日誌都放那裡。`/workspace` 的 venv 每台重建。
- 計費從部署開始（含拉映像），停機即止。`deploy --hours` 一定要設，忘了就靠 `auto-stop`。
- 寫結果的腳本都能續跑（`gens.jsonl` 逐行追加），機器被收回就重開一台、`sync`、再 `run` 同一個指令。
- 實驗腳本用 `--backend torch` 時走 `torch_engine.py`；`--backend mlx`（預設）走原本的 `engine.py`。兩個後端的生成不是逐 token 相同（取樣實作不同），同一個研究不要混用。
- API 文件沒寫的端點（取得單一執行個體、刪除）`gputw.py` 會試常見路徑並印出回應；失敗就去儀表板操作。

## 本機煙霧測試（不用 GPU）

```bash
services/model-server/.venv-torch/bin/python services/model-server/torch_engine.py --model Qwen/Qwen3.5-0.8B --max-tokens 64
```

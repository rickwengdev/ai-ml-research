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

- 只有 `/vault` 會留下來，但它的寫入很慢（實測 6 MB/s），所以模型權重放 `/workspace/hf`（每台重抓，400 Mbps 下 27B 約 20 分鐘），結果與日誌才放 `/vault`。要長期保存的權重用控制台 Vault 頁的「從網址下載」填 Hugging Face repo，由他們的伺服器抓進 Vault，不占機器時間；之後 `--model /vault/work/models/<名稱>` 直接載（讀取是快的）。`/workspace` 的 venv 每台重建。
- 計費從部署開始（含拉映像），停機即止。`deploy --hours` 一定要設，忘了就靠 `auto-stop`。
- 寫結果的腳本都能續跑（`gens.jsonl` 逐行追加），機器被收回就重開一台、`sync`、再 `run` 同一個指令。
- 實驗腳本用 `--backend torch` 時走 `torch_engine.py`；`--backend mlx`（預設）走原本的 `engine.py`。兩個後端的生成不是逐 token 相同（取樣實作不同），同一個研究不要混用。
- API 文件沒寫的端點（取得單一執行個體、刪除）`gputw.py` 會試常見路徑並印出回應；失敗就去儀表板操作。

## 批次與即時監控

- 實驗腳本加 `--batch N`（只限 `--backend torch`）：連續批次，最多 N 條一起生成；一條軌跡的一步生成完，就立刻跑測試、把它的下一步接進正在跑的批次，不用等同一批最慢的那條（`torch_engine.ContinuousBatcher`、`pressure.drive`）。每列各自的種子，所以一列的 token 不受同批其他列影響；新加入的列先單獨 prefill，再把快取接進批次（全注意力層左側補零並遮罩，線性注意力層的固定狀態直接接上），跑完的列立刻移出，避免左側填充滲進 Qwen3.5 的線性注意力層（實測兩個填充 token 就讓狀態偏到 cos 0.9995）。27B bf16 在 RTX Pro 6000 上：逐條 10–12 tok/s，批次 24 約 150–250 tok/s，GPU 被 500 W 功耗上限卡住。
- 監控面板：引擎每秒把累計 token 寫到 `$ENGINE_METRICS`；`monitor.py` 在機器上讀它和 `nvidia-smi`，只聽 127.0.0.1。用 SSH 通道接回本機，不開任何公開連接埠：

```bash
ssh -f -N -L 8090:127.0.0.1:8090 -p 2222 pod-<id>@ssh.gputw.ai   # 然後開 http://localhost:8090
```

- 在機器上用 `pkill -f`／`pgrep -f` 找程序時，模式不能出現在自己的指令列裡（遠端 bash 的指令列包含整段指令，會把自己砍掉）；停程序用 PID，或把指令寫成腳本檔再執行。

## 備用：Google Cloud（`gcp.py`）

GPUtw 沒機或出問題時用。指令和 GPUtw 那套一樣（`sync`、`run`、`backup`、`tunnel`），VM 上的路徑也一樣（`/vault/work` 放程式、結果、日誌，`/workspace` 放 venv 和權重），所以 `bootstrap.sh`、實驗指令、`monitor.py` 都不用改。全部透過本機的 `gcloud`。

一次性準備：

1. **用獨立的專案**，例如 `ai-ml-research`，把有 credit 的帳單帳戶掛上去。`gcp.py` 不會用 gcloud 的預設專案，每次都要 `--project` 或 `RESEARCH_GCP_PROJECT`。
2. **免費試用帳戶不能開 GPU**，要先把帳單帳戶升級成付費（credit 仍然先扣）。新專案的 `GPUS_ALL_REGIONS` 配額是 0，要到 IAM & Admin › Quotas 申請（可能幾分鐘到幾天，也可能被拒）。`gcp.py quota --region us-central1` 看目前的額度。
3. 建 /vault 用的永久磁碟（只放程式與結果，50 GB 約每月 5 美元）：`gcp.py vault-create --zone <zone>`。磁碟是區域性的，VM 要開在同一個 zone。

一輪實驗：

```bash
G="services/model-server/.venv/bin/python research/cloud/gcp.py"
export RESEARCH_GCP_PROJECT=ai-ml-research
$G prices                                    # 各 GPU 的大約價格，以及 80 美元夠跑幾小時
$G zones --gpu rtx6000                       # 哪些 zone 有 RTX PRO 6000
$G create research-g4 --gpu rtx6000 --zone <zone> --hours 6 --spot --yes   # 印出估價，沒有 --yes 不會建
$G ssh research-g4 -- nvidia-smi               # 第一次開機會裝驅動，等幾分鐘
$G sync research-g4
$G run research-g4 --job bootstrap -- bash /vault/work/research/cloud/bootstrap.sh Qwen/Qwen3.5-27B
$G run research-g4 --job step1-27b -- /workspace/venv/bin/python research/experiments/pressure_steer.py run --backend torch --model Qwen/Qwen3.5-27B --batch 24 --out research/data/<日期>-pressure-steer-27b
$G tunnel research-g4                          # 監控面板，the research UI 的 GPU 頁也讀這裡
$G backup research-g4 --every 300              # 跑的期間定期把結果拉回本機
$G delete research-g4                          # 用完刪掉：停機的 VM 開機碟仍在計費；/vault 的磁碟保留
```

要記得的事：

- GPU 規格：`rtx6000`（g4-standard-48，96 GB，27B bf16 可批次 24）、`a100-80`（a2-ultragpu-1g，27B bf16 但批次要降到 12 左右）、`a100-40`、`l4`（只夠 9B）。
- `--hours` 必填：VM 到時間會自己停（`--max-run-duration`）。`--spot` 約半價，但 Google 隨時可能收回；實驗腳本能續跑，重開一台、`sync`、`run` 同一個指令即可。
- 價格是 2026-11 的大約值（官方頁面與第三方追蹤），只用來在建立前估價；Spot 隨區域和時間浮動。
- 映像是 Deep Learning VM 的 `pytorch-2-9-cu129-ubuntu-2204-nvidia-580`（PyTorch 2.9、CUDA 12.9、驅動 580，支援 Blackwell）。Google 會淘汰舊的映像家族，`gcp.py images` 列出目前有的，建立前也會先檢查。
- 權重放在開機碟（`/workspace/hf`），每台重新下載。

## 本機煙霧測試（不用 GPU）

```bash
services/model-server/.venv-torch/bin/python services/model-server/torch_engine.py --model Qwen/Qwen3.5-0.8B --max-tokens 64
```

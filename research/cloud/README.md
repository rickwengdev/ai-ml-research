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

- 只有 `/vault` 會留下來，但它的寫入很慢（實測 6 MB/s），所以模型權重放 `/workspace/hf`（每台重抓，400 Mbps 下 27B 約 20 分鐘），結果與日誌才放 `/vault`。要長期保存的權重用 `gputw.py vault-fetch <HF repo>`（控制台「從網址下載」的同一個端點）由他們的伺服器抓進 Vault，不占機器時間；之後用 `rsync -aL` 複製到 `/workspace` 再載入（GPUtw 建議 `/vault` → `/workspace` 用 rsync，依檔案類型約 500–4000 Mbps）。`/workspace` 的 venv 每台重建。
- 計費從部署開始（含拉映像），停機即止。`deploy --hours` 一定要設，忘了就靠 `auto-stop`。
- 寫結果的腳本都能續跑（`gens.jsonl` 逐行追加），機器被收回就重開一台、`sync`、再 `run` 同一個指令。
- 實驗腳本用 `--backend torch` 時走 `torch_engine.py`；`--backend mlx`（預設）走原本的 `engine.py`。兩個後端的生成不是逐 token 相同（取樣實作不同），同一個研究不要混用。
- API 文件沒寫的端點（取得單一執行個體、刪除）`gputw.py` 會試常見路徑並印出回應；失敗就去儀表板操作。

## 批次與即時監控

- 實驗腳本加 `--batch N`（只限 `--backend torch`）：連續批次，最多 N 條一起生成；一條軌跡的一步生成完，就立刻跑測試、把它的下一步接進正在跑的批次，不用等同一批最慢的那條（`torch_engine.ContinuousBatcher`、`pressure.drive`）。每列各自的種子，所以一列的 token 不受同批其他列影響；新加入的列先單獨 prefill，再把快取接進批次（全注意力層左側補零並遮罩，線性注意力層的固定狀態直接接上），跑完的列立刻移出，避免左側填充滲進 Qwen3.5 的線性注意力層（實測兩個填充 token 就讓狀態偏到 cos 0.9995）。27B bf16 在 RTX Pro 6000 上：逐條 10–12 tok/s，批次 24 約 150–250 tok/s，GPU 被 500 W 功耗上限卡住。
- 監控面板：引擎每秒把累計 token 寫到 `$ENGINE_METRICS`；`monitor.py` 在機器上讀它和 `nvidia-smi`，只聽 127.0.0.1。用 SSH 通道接回本機，不開任何公開連接埠：

```bash
$G tunnel <id>   # 也就是 ssh -f -N -L 8090:127.0.0.1:8090 -p 2222 pod-<id>@ssh.gputw.ai；然後開 http://localhost:8090。每開一台新機器要重接一次
```

- 在機器上用 `pkill -f`／`pgrep -f` 找程序時，模式不能出現在自己的指令列裡（遠端 bash 的指令列包含整段指令，會把自己砍掉）；停程序用 PID，或把指令寫成腳本檔再執行。

## 一鍵任務（`jobs/`）

`jobs/*.sh` 是從一台剛開好的機器跑到底的整段任務：建環境 → 權重從 `/vault` 複製到本機 NVMe → 開監控 → 實驗的各步。每一步都會先檢查成果是否已在 `/vault`，有就跳過，所以機器被收回後重開、`sync`、再 `run` 同一行就會接著跑。結束時在資料夾寫 `DONE`（內容是怎麼結束的：`complete`、哪一步失敗，或預先登記的閘門沒過）。

機器上沒有 API 金鑰，任務不能自己關機。所以開機時用 `--hours` 設一個硬上限，本機再開一個小迴圈，看到 `DONE` 就停機：

```bash
$G run <id> --name pressure-27b -- bash /vault/work/research/cloud/jobs/pressure-27b.sh
$G jobs <id>                                 # 每個任務的狀態與日誌最後一行
$G kill <id> pressure-27b                    # 依 PID 檔停掉整個程序群組
until $G ssh <id> -- test -f /vault/work/research/data/<step1>/DONE; do sleep 120; done; $G stop <id>
```

### 全部實驗：`jobs/pressure-all.sh`

三個模型（Qwen3.5-27B、Qwen3.5-9B、Gemma 4 31B，全部 bf16）依登記跑完壓力路線的所有實驗。先橫向跑完三個模型的步驟 0–1，再跑步驟 2（A–F），最後跑 ImpossibleBench，所以中途停下時，最重要的跨模型結果已經有了。每個模型各自過閘門：K1 不成立就不操縱；K2 不成立時照跑，但只算探索性。`/vault/work/logs/pressure-all.status` 每完成一部分記一行。`MODELS="q27 q9"`、`PHASES="1 2"` 可以縮小範圍。

開機前先把 `Qwen/Qwen3.5-9B` 與 `google/gemma-4-31B-it` 放到 `/vault/work/models/Qwen3.5-9B`、`/vault/work/models/gemma-4-31B-it`：`$G vault-fetch Qwen/Qwen3.5-9B`、`$G vault-fetch google/gemma-4-31B-it`，再用 `$G vault-downloads --watch 60` 看進度。這是控制台「從網址下載」用的端點（`/api/vault/downloads`，文件沒寫），一次一個檔案、每個帳號同時 3 個，指令會等空位；檔案固定在 repo 當下的 commit，已經在 Vault 且大小相符的會跳過，中途斷掉重跑即可。這樣不佔機器時間，開機後任務用 rsync 從 Vault 複製到 NVMe（GPUtw 建議的做法，依檔案類型約 500–4000 Mbps；兩個模型共約 80 GB，約 3–20 分鐘，中斷後重跑會跳過已完成的分片）。沒放的話，任務會在機器上下載：100 Mbps 下 Gemma 約 80 分鐘，跑上一個模型時在背景先抓。

```bash
$G deploy --gpu "PRO 6000" --hours 40 --bandwidth 400
$G sync <id>
$G run <id> --name pressure-all -- bash /vault/work/research/cloud/jobs/pressure-all.sh
until $G ssh <id> -- grep -q DONE: /vault/work/logs/pressure-all.status; do sleep 300; done; $G stop <id>
```

### 引擎效能測試：`jobs/bench.sh`

付費大跑之前，先在便宜的卡上量引擎（預設 RTX 5090 + Qwen3.5-9B，和 27B 同架構、和 Pro 6000 同一代）。步驟 0 全部 12 題跑四次：A 關掉提示存放區（舊引擎的讀法）、B 打開、C 再加 flash-linear-attention、D 是 C 的兩倍批次。`logs/bench.md` 列出各組的 tok/s、讀提示與解碼的秒數、提示有多少是從存放區取的，以及和 A 比同一列是否同回覆、探針狀態的 cos。結果只是測試，不是實驗資料，留在 `/workspace/bench`。

```bash
$G run <id> --name bench -- bash /vault/work/research/cloud/jobs/bench.sh
```

2026-11-01 在 RTX 5090 上的結果（Qwen3.5-9B，步驟 0 全部 12 題，約 145 次生成）：

| 組 | 秒 | 生成 token | tok/s | 讀提示 s | 解碼 s | 提示從存放區取 |
|---|---|---|---|---|---|---|
| A 存放區關（舊引擎） | 398 | 80,680 | 203 | 53 | 334 | 0% |
| B 存放區開 | 440 | 85,919 | 195 | 24 | 406 | 72% |
| C B + flash-linear-attention | 412 | 92,970 | 226 | 52 | 346 | 71% |
| D C、批次 32 | 323 | 75,310 | 233 | 28 | 282 | 71% |

讀到的事：存放區讓讀提示的量少了七成、時間少了一半以上，但步驟 0 的時間主要在解碼；每一步解碼約 36–38 ms，不論同時 9 列還是 17 列都差不多（9B 的權重讀一遍理論上約 10 ms），所以固定開銷是瓶頸，批次越滿越划算。步驟 0 只有 36 條軌跡，尾段常只剩一兩列；步驟 2 與 ImpossibleBench 有數百條，批次能一直滿。fla 讓解碼每步快約 7%，第一次遇到新長度時要編譯（C 的讀提示秒數）。每組的取樣回覆會因浮點運算順序不同而分岔（與 A 同回覆的列數），所以生成 token 數不同，秒數不能直接比，tok/s 與每步毫秒數才是可比的。

### 2026-11-02 的解碼加速

讀程式時找到每一步解碼的三個額外開銷，都已改掉。前兩項只改浮點運算順序：讀提示與探針狀態完全不變，因為這兩項只作用在解碼步。

- **注意力**：批次有左側填充，必須帶遮罩，HF 的 SDPA 因此不能用分組的 K/V 頭，每一步都先把整個快取依查詢頭數複製一份（`repeat_kv`，Qwen3.5 是 4 倍）。現在解碼步改成讓每個 K/V 頭直接和它那組查詢頭相乘，快取只讀一次（`torch_engine._register_decode_attention`）。
- **KV 快取**：HF 的 `DynamicLayer` 每生成一個 token 就把整段 K/V 用 `torch.cat` 複製一次。批次中的全注意力層改為預留空間、就地寫入；有列加入或離開時才搬一次（`_grow_update`）。
- **取樣**：原本每一步都對整個詞表（24.8 萬）排序做 top-p，還為每一列各產生一次詞表大小的隨機數。現在先取前 1,024 個詞，在裡面找核心集合；湊不滿 top_p 時退回整個詞表。雜訊來自每一列（種子、步數、token）的計數雜湊，一次算完所有列。分布與原本相同，但抽到的 token 不同。
  - 一個資料夾沿用它開始時的取樣器（`run.json` 的 `engine.sampler`），續跑不混用兩種隨機串流；之前的資料夾記為 `generator`。
- **測試與 GPU 重疊**：`pressure.drive` 把每一步批次放到另一個執行緒，主執行緒同時替上一步跑完的軌跡跑測試，不再讓整個批次等。
- **小顯卡**：`pressure-all.sh` 依顯示卡記憶體決定批次。32 GB（RTX 5090）上只跑得動 9B，批次 16、ImpossibleBench 16（批次 32 跑三分鐘就記憶體不足）；放不下的模型跳過並記一行。
- **本機驗證**（小模型 Qwen3.5、Gemma 4，CPU float32）：
  - 新注意力與快取：貪婪解碼的 token 完全相同，logits 差在 3e-6 以內。
  - 取樣器：與整個詞表的 top-p 分布一致（總變異距離與多項分布抽樣相當）；一列單獨抽或和別列一起抽，結果相同。
  - 在 GPU 上的實際加速，第一次開機時從 `metrics.json` 的每步毫秒數量。

提示存放區（`torch_engine.PromptStore`）：提示一律不操縱地讀，所以讀過的提示可以接著用。探針讀過的提示，生成時不必再讀一次；下一步的提示從上一步讀到的地方接著讀；同一段歷程的各組與各種子共用第一次的讀取。大小預設是載入權重後剩餘 GPU 記憶體的四分之一，`ENGINE_PROMPT_STORE_GB` 可以改，設 0 就關掉。`ENGINE_FLA=1` 讓 bootstrap 裝 flash-linear-attention。

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

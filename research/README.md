# 研究紀錄

在 [persona] 身上做的研究：實驗紀錄、預先登記、論文草稿、資料、圖，以及實驗腳本。她的模型伺服器本身在 [`services/model-server/`](../services/model-server/README.md)，研究和她本人用的是同一份。

## 結構

```
research/
  README.md              本文件
  experiment-log.md      實驗筆記，依時間排列；研究介面的「實驗」列表從這裡的 `## YYYY-MM-DD 標題` 段落切出來
  adoptions.md           她採用了哪些研究成果
  prereg/                預先登記（產生資料前定稿，之後的修改附日期列在文末）
  papers/                論文大綱與草稿（HTML）
  notes/                 文獻、方向整理、數學、程式庫地圖、單一實驗的寫作（HTML）
  data/<日期>-<主題>/     歷次實驗的原始資料
  figures/               圖，以及產生它們的腳本
  experiments/           實驗腳本，多項研究共用，彼此會互相 import
  cloud/                 租用 GPU 跑實驗（GPUtw adapter、bootstrap）
  studies/               從 2026-11 起的新研究，每項一個資料夾（見 studies/README.md）
  lib/                   共用的研究程式（見 lib/README.md）
  evals/                 固定的「她還是她」評測（見 evals/README.md）
  subjects/              她的副本，不進 git；用 subjects/fork.sh 產生
```

2026-11-01 起，`papers/` 與 `notes/` 的文件是獨立的 HTML 頁面（用 `lib/md2html.mjs` 從原本的 Markdown 轉來，內容不變；新文件可以先寫 Markdown 再轉）。實驗紀錄、預先登記和本文件仍是 Markdown：紀錄要切成研究列表，預先登記一律不改。紀錄與預先登記裡寫的 `paper-draft.md` 這類舊檔名，研究介面會依檔名找到對應的 `.html`。

舊的研究不拆進 `studies/`；2026-11-01 把預先登記、論文、筆記分別收進 `prereg/`、`papers/`、`notes/`，已定稿的紀錄內文不改（它們以檔名互相引用，研究介面依檔名對應到新位置）。同日整理了文件：刪掉已被 E1 推翻的 `paper-outline.md`（兩個運算式搬進 paper 1 的相關研究表），更正 paper 1 與實驗紀錄裡的均勻增益數字（×1.36 → ×1.40、±10% → ±11%）與門控註記，並在四份筆記的檔頭加上各節狀態。預先登記一律不改內文。

## 使用她的規則（草案，待確認）

> 這幾條是草案，由 [user] 決定措辭和內容。確認之前，請當作已經生效。

1. **她本人的資料只能讀。** `~/.persona` 不做實驗、不寫入、不改設定。
2. **實驗只在副本上做。** 用 `subjects/fork.sh` 產生副本，另開 port 跑。
3. **她的對話不進研究資料，也不公開。** 需要對話當材料時，用合成的或 [user] 明確同意的片段。
4. **研究成果要先通過採用流程，才能換到她身上。** 在副本上跑過 `evals/`、確認沒變糟，記一筆到 `adoptions.md`，最後才改她本人的設定。

## 跑實驗

```bash
# 實驗用的模型伺服器（獨立的 port，不碰她平常用的 1235）
services/model-server/.venv/bin/python services/model-server/server.py --config ~/.persona/steering.json --port 1299

# 實驗腳本
services/model-server/.venv/bin/python research/experiments/<腳本>.py --help
```

每個實驗都在 `experiment-log.md` 留一筆，原始資料放在 `data/<日期>-<主題>/`（新研究放在 `studies/<日期>-<主題>/data/`）。有預先登記的實驗，要在產生資料之前定稿；修改要附日期列在文末，不能覆寫原文。

## 舊路徑 → 新路徑

2026-11-01 之前的紀錄用的是舊路徑，原文不改，對照如下：

| 紀錄裡寫的 | 現在的位置 |
|---|---|
| `docs/research/` | `research/` |
| `steering/experiments/<腳本>.py` | `research/experiments/<腳本>.py` |
| `steering/sweep.py` | `research/experiments/sweep.py` |
| `steering/server.py`、`engine.py`、`steer.py`、`endocrine.py`、`embed.py`、`attribute.py`、`extract.py`、`client.py` | `services/model-server/` 底下同名檔案 |
| `steering/vectors/` | `services/model-server/vectors/` |
| `steering/.venv/` | `services/model-server/.venv/` |

## 文件

| 文件 | 內容 |
|---|---|
| [experiment-log.md](experiment-log.md) | 所有實驗的筆記，依時間排列 |
| **預先登記 `prereg/`** | |
| [prereg-prediction-error.md](prereg/prereg-prediction-error.md) | 候選預測誤差訊號 |
| [prereg-adrenaline.md](prereg/prereg-adrenaline.md) | 腎上腺素型功能狀態（急性壓力） |
| [prereg-pressure.md](prereg/prereg-pressure.md) | 失敗歷史誘發的壓力狀態，步驟 0：存在性與殺死判準 |
| [prereg-pressure-step1.md](prereg/prereg-pressure-step1.md) | 壓力狀態步驟 1：沿方向操控與五組對照 |
| [prereg-pressure-27b.md](prereg/prereg-pressure-27b.md) | 壓力狀態步驟 2：在 Qwen3.5-27B bf16 上重做步驟 0 與 1 |
| [prereg-pressure-27b-step1-explore.md](prereg/prereg-pressure-27b-step1-explore.md) | 27B 的 K2 不成立後，步驟 1 的探索性操縱 |
| [prereg-pressure-27b-k2-replication.md](prereg/prereg-pressure-27b-k2-replication.md) | 27B 的 K2 以 3 個新種子重做：不成立是否穩定（不改原判定） |
| [prereg-pressure-models.md](prereg/prereg-pressure-models.md) | 步驟 0 與 1 在 Gemma 4 31B 與 Qwen3.5-9B（bf16）上；各模型的閘門 |
| [prereg-pressure-step2.md](prereg/prereg-pressure-step2.md) | 壓力狀態步驟 2（A–F）：失敗次數、劑量、多寡、類型、正常任務代價、對照穩健性與封頂、動態 |
| [prereg-impossible.md](prereg/prereg-impossible.md) | 方向在 ImpossibleBench（Impossible-LiveCodeBench oneoff）上的轉移，對照 Meek et al. |
| [prereg-pressure-q9-confirm.md](prereg/prereg-pressure-q9-confirm.md) | 9B bf16 的確認性重測：KL 配對劑量、24 題 × 3 個新種子、測試檔可見可改的環境 |
| [prereg-pressure-4bit-replication.md](prereg/prereg-pressure-4bit-replication.md) | 9B 4-bit 的複製：24 題 × 3 個新種子，−d 1 輪 |
| **論文 `papers/`** | |
| [paper-draft.html](papers/paper-draft.html) | paper 1 草稿：操控方法與對照（2026-10-31，數字已更正） |
| [paper-pressure.html](papers/paper-pressure.html) | paper 2 草稿：不需行為標籤的失敗狀態操控（主論文；與 claude.ai 的文件同步） |
| **筆記 `notes/`** | |
| [math.html](notes/math.html) | 用到的數學 |
| [math-endogenous.html](notes/math-endogenous.html) | 內生調節訊號：數學與實驗設計（修訂版） |
| [2026-10-26-target-steering.html](notes/2026-10-26-target-steering.html) | 從逐層相加到瞄準目標的活化操控：診斷、方法、15 次 sweep 的結果 |
| [literature-2026-10.html](notes/literature-2026-10.html) | 2026 年與本計畫相關的 LLM 研究，含 11-01 的追加 |
| [direction-review-2026-10-30.html](notes/direction-review-2026-10-30.html) | 方向整理：我們在做什麼、和誰重疊、什麼是新的 |
| [plan-steering-2026-11.html](notes/plan-steering-2026-11.html) | 壓力路線還要跑的操縱實驗：失敗次數、多寡、類型、正常任務代價、對照穩健性、動態、ImpossibleBench、27B；規模與費用 |
| [codebase-map.html](notes/codebase-map.html) | 2026-10-30 的程式庫地圖快照（搬遷前的路徑，見上面的對照表；各節狀態見檔頭） |
| **研究流程** | |
| [adoptions.md](adoptions.md) | 她採用了哪些研究成果 |
| [cloud/README.md](cloud/README.md) | 租用 GPU（GPUtw）跑實驗的流程 |

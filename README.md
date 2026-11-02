# AI/ML Research

Research on steering and functional states in language models: lab log, preregistrations, raw data, analysis and paper drafts. Written in Traditional Chinese.

語言模型操控與功能狀態的研究：實驗紀錄、預先登記、原始資料、分析和論文草稿。內容和結構見 [research/README.md](research/README.md)。

## 內容

| 路徑 | 是什麼 |
|---|---|
| `research/` | 實驗紀錄、預先登記、論文草稿、原始資料、圖、實驗腳本、GPU 租用工具 |
| `services/model-server/` | 模型伺服器和實驗引擎（mlx、PyTorch），以及操控向量 `vectors/*.npz` |
| `docs/` | 系統提示（`system-prompt.md`）和它開頭的憲法（`constitution.md`） |
| `training/data/generated/` | 實驗用的測試題（`prompts.jsonl`）和合成的狀態情境（`turns.json`） |
| `training/judge_client.py`、`claude_batch.mts` | `judge.py` 呼叫 Claude 評審用的 client |

## 安裝

指令都在 repo 根目錄執行。

```bash
python3 -m venv services/model-server/.venv
services/model-server/.venv/bin/pip install -r services/model-server/requirements.txt   # Apple silicon，mlx
services/model-server/.venv/bin/python research/experiments/<腳本>.py --help
```

CUDA 機器用 `requirements-torch.txt`（`research/cloud/bootstrap.sh`）。`judge.py` 另外要 `npm install` 和 Anthropic 的 API 金鑰。

## 這份公開版和原始紀錄的差別

實驗原本是在一個角色扮演型的 AI 系統上做的，公開版把它匿名化（2026-11-02）：

- 角色和使用者的名字換成 `[persona]`、`[user]`（文件裡寫成「角色」「使用者」），包括系統提示、憲法、測試題、原始資料裡模型生成的文字，以及 `judge.py` 的評審提示。
- 程式裡的路徑、環境變數和註解改成中性的寫法。回應裡的欄位是 `persona`。
- 預先登記和實驗紀錄原本定稿後不改，這裡只做了上面這些替換。

所以：

- **不是逐位元相同的重跑**：當時的提示裡是真名，這裡是 `[persona]`。`vectors/*.npz` 是當時算出來的原檔；`extract.py` 的提示也做了同樣的替換，重新抽取會有微小差異。
- commit 雜湊都變了，紀錄裡提到的舊雜湊對不上；commit 時間是作者自己記的，**不能單獨當作預先登記早於資料的第三方證明**。
- 從生成文字重算的指標可能因為名字替換而有微小差異。未改動的版本保留在不公開的 repo。
- 較早的 commit 裡，三個 `setup.json` 的系統提示是 `[withheld: persona system prompt]`；最新版已經放回匿名化後的全文。
- 測試題和狀態情境的產生程式沒有公開，這裡放的是產生好的結果。

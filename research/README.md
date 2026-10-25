# 研究紀錄

[persona] 上做過的實驗、資料和論文草稿。每個實驗一份紀錄，原始資料放在 `data/<日期>-<主題>/`。

| 文件 | 內容 |
|---|---|
| [paper-outline.md](paper-outline.md) | 論文大綱：狀態以激活目標傳遞而非提示文字；研究問題、相關研究、實驗計畫與完成度 |
| [2026-10-26-target-steering.md](2026-10-26-target-steering.md) | 從逐層相加到瞄準目標的激活操控：診斷、方法、15 次 sweep 的結果 |

## 資料格式

`data/2026-10-26-target-steering/`：

- `runs/NN-名稱/sweep.jsonl`：每行一則回覆。欄位有傾向、值、α、提示、回覆、自動指標（junk、rep、zh、simp、romance），以及實際偏移和目標（σ）。
- `runs/NN-名稱/sweep.md`：同一批結果的表格和並排回覆。
- `extraction/`：向量抽取的紀錄。
  - `v1-before.report.md`：修正前的報告。
  - `v2`～`v4` 的 `.log`：各次重抽的過程。
  - `v4-final.report.md`：最終報告。

由 `steering/sweep.py` 和 `steering/extract.py` 產生，重現方式見各實驗紀錄的最後一節。

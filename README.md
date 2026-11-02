# AI/ML Research

Research on steering and functional states in language models: lab log, preregistrations, raw data, analysis and paper drafts. Written in Traditional Chinese.

語言模型操控與功能狀態的研究：實驗紀錄、預先登記、原始資料、分析和論文草稿。內容和結構見 [research/README.md](research/README.md)。

## 這份公開版和原始紀錄的差別

實驗原本是在一個角色扮演型的 AI 系統上做的，公開版把它匿名化（2026-11-02），整段 git 歷史都一樣處理：

- 角色和使用者的名字換成 `[persona]`、`[user]`（文件裡寫成「角色」「使用者」），包括原始資料裡模型生成的文字，以及 `judge.py` 的評審提示。
- 三個 `setup.json` 的系統提示全文拿掉，換成 `[withheld: persona system prompt]`。模型輸出裡引用到的片段還在。
- 程式裡的路徑和環境變數改成中性的名字。
- 預先登記和實驗紀錄原本定稿後不改，這裡只做了上面這些替換。

所以：

- commit 雜湊都變了，紀錄裡提到的舊雜湊對不上；commit 時間是作者自己記的，**不能單獨當作預先登記早於資料的第三方證明**。
- 從生成文字重算的指標可能因為名字替換而有微小差異。未改動的版本保留在不公開的 repo。

## 無法只靠這個 repo 重跑

實驗要用的模型伺服器（`services/model-server/`）、`training/` 和系統提示沒有公開。有存取權的話，把它們連結到 repo 根目錄（已列入 `.gitignore`）：

```bash
ln -s <engine repo>/services services
ln -s <engine repo>/training training
ln -s <engine repo>/docs docs

services/model-server/.venv/bin/python research/experiments/<腳本>.py --help
```

指令都在 repo 根目錄執行。

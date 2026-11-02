# AGENTS.md

這份是給在這個 repo 裡工作的程式代理看的。研究的結構見 [research/README.md](research/README.md)，這份公開版的匿名化規則和限制見 [README.md](README.md)。

## 不能做的事

- 金鑰和權杖不能進 commit，也不能出現在輸出裡。GPU 租用的金鑰放在 `$GPUTW_API_KEY` 或 `~/.config/gputw/key`。
- 不要停掉或打斷正在跑的實驗。實驗伺服器用 1299，正式使用的模型伺服器在 1235，不要碰。
- 不改 `research/data/**`：那是實驗資料，可能有實驗正在寫入。
- 公開內容不能出現匿名化前的名字、系統提示全文或真實對話。
- 不要繞過分類器的拒絕。
- commit 只放自己改的檔案，訊息結尾加上 attribution 的那一行。

## 約定

- 程式碼註解用英文，風格跟周圍一致；文件用繁體中文。
- 每個實驗都在 `research/experiment-log.md` 留一筆，原始資料放在 `research/data/<日期>-<主題>/`。有預先登記的實驗，要在產生資料之前定稿；修改要附日期列在文末，不能覆寫原文。
- 實驗用的模型伺服器要用獨立的 port。
- 實驗腳本用模型伺服器的環境跑：`services/model-server/.venv/bin/python research/experiments/<腳本>.py`。
- `research/cloud/jobs/*.sh` 在機器上跑的時候，不要同步新版本過去。機器上的版面是 `/vault/work/{research,services/model-server}`，由 `research/cloud/gputw.py sync` 組起來。

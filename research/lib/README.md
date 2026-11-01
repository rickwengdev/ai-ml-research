# 共用的研究程式

兩項以上研究會用到的程式放這裡，要比單一實驗的腳本嚴謹：有說明、有測試、改了要讓舊的研究還能重跑。

- `md2html.mjs`：把 Markdown 文件轉成 `papers/`、`notes/` 用的獨立 HTML 頁面（`node research/lib/md2html.mjs <檔案.md>`），渲染規則和研究介面一致。

第一批候選（目前還在 `../experiments/`）：

- `sweep.py` 的自動指標：junk、rep、zh、simp、romance。
- bootstrap 信賴區間和排列檢定。

搬過來的時候，原本的腳本改成 import 這裡的版本，結果要跟搬之前一致。

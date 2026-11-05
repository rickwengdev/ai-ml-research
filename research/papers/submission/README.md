# Submission package

`main.tex`、`refs.bib`、`figures/`：英文稿。`REVIEW.md`：審查報告與更正清單。`checks/`：審查用的重算腳本，`checks/output.txt` 是它們的輸出。

## 建置

```bash
cd research/papers/submission
pdflatex main && bibtex main && pdflatex main && pdflatex main
```

也可以用 `tectonic -X compile main.tex`。目前匿名版 13 頁（正文約 10 頁）。署名版要在本機建 `authors.local.tex`，這個檔不進 git，因為公開 repo 不放姓名。

`main.tex` 開頭有兩個開關：

- `\anonymoustrue`／`\anonymousfalse`：匿名或署名版。作者與單位是佔位符，要由作者填入。
- `\showtodostrue`／`\showtodosfalse`：是否印出紅字的 `\AUTHORTODO{}`。全部解決之前不要關。

圖由 `figures/make_figures.py` 從 `research/data/` 重畫（只讀；需要 numpy 與 matplotlib）。原本 `research/figures/` 的圖標籤是中文，其中一張還留著已更正的「約兩輪」，所以沒有直接複製。

## 換成會議的 class

1. 把 `\documentclass[11pt]{article}` 和 geometry 換成該會議的 class（例如 `neurips_*.sty`、`icml*.sty`、ICLR 的 `iclr*.sty`、ACL 的 `acl.sty`）。這裡沒有下載這些檔案。
2. 匿名開關改接 class 自己的選項，刪掉 `\author` 的條件分支。
3. natbib 與 `plainnat` 若和 class 衝突，改用該 class 規定的 bibliography style。
4. 把附錄移到 class 規定的位置，或另成 supplementary。

## 投稿方向（2026-11-05 查的，投稿前要對照當期徵稿）

| 場合 | 狀態 | 備註 |
|---|---|---|
| ICLR 2027 工作坊 | 名單 2026-11-29 公布，徵稿之後才有 | 首選，等可解釋性或安全相關的工作坊出來 |
| TMLR | 隨時可投，雙盲 | 期刊，重技術正確性；是否歡迎負面結果沒有明文 |
| ICML 2027 Mech Interp 工作坊 | 還沒公布；2026 年 5 月 8 日截止，非存檔 | 非存檔可以和其他場合並行 |
| BlackboxNLP 2027 | 還沒公布；2026 年 7 月 17 日截止 | 2026 年有可重現性與可靠性專軌 |
| ROCLING 2027（可中文） | 還沒公布；2026 年 7 月 20 日截止 | 主題含 LLM 安全與可解釋性；2023 年明文可用中文；有存檔和非存檔軌 |
| CCL 2027（可中文） | 還沒公布 | 2026 年收中英文，中文稿推薦到《中文信息学报》；主題含大模型安全；雙盲 |
| 已截止 | ICLR 2027 主會、SaTML 2027、COLING 2027 | |

同一篇不要在兩個存檔場合發表；中文版投非存檔軌，才不會影響英文版。各場合的頁數和 LLM 政策都還沒查證。

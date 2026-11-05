# Submission package

`main.tex`、`refs.bib`、`figures/`：英文稿。`REVIEW.md`：審查報告與更正清單。`checks/`：審查用的重算腳本，`checks/output.txt` 是它們的輸出。

## 建置

```bash
cd research/papers/submission
pdflatex main && bibtex main && pdflatex main && pdflatex main
```

這台機器沒有 `pdflatex`、`xelatex`、`latexmk`、`tectonic`，所以**這份稿子還沒有編譯過**，只做過靜態檢查（環境與大括號配對、`\cite` 與 `\ref` 都對得上、圖檔存在、原始碼全 ASCII）。第一次編譯時請留意表 1 與附錄表格的寬度。

`main.tex` 開頭有兩個開關：

- `\anonymoustrue`／`\anonymousfalse`：匿名或署名版。作者與單位是佔位符，要由作者填入。
- `\showtodostrue`／`\showtodosfalse`：是否印出紅字的 `\AUTHORTODO{}`。全部解決之前不要關。

圖由 `figures/make_figures.py` 從 `research/data/` 重畫（只讀；需要 numpy 與 matplotlib）。原本 `research/figures/` 的圖標籤是中文，其中一張還留著已更正的「約兩輪」，所以沒有直接複製。

## 換成會議的 class

1. 把 `\documentclass[11pt]{article}` 和 geometry 換成該會議的 class（例如 `neurips_*.sty`、`icml*.sty`、ICLR 的 `iclr*.sty`、ACL 的 `acl.sty`）。這裡沒有下載這些檔案。
2. 匿名開關改接 class 自己的選項，刪掉 `\author` 的條件分支。
3. natbib 與 `plainnat` 若和 class 衝突，改用該 class 規定的 bibliography style。
4. 把附錄移到 class 規定的位置，或另成 supplementary。

## 適合的投稿方向

以下是審查者的判斷。**頁數、截止日、匿名與 LLM 政策都要對照當期徵稿說明，這裡沒有查證。**

| 方向 | 為什麼 | 需要查證 |
|---|---|---|
| ML 會議的可解釋性或 AI 安全工作坊（NeurIPS、ICML、ICLR 的相關工作坊） | 單模型、小任務、事先登記的負面結果，最符合工作坊的範圍 | 通常 4–9 頁，以當期為準 |
| 接受負面結果與複製的期刊或軌道（例如 TMLR、ACL 系列的 BlackboxNLP 工作坊） | 可保留較完整的方法與登記紀錄 | 是否接受此題目、匿名規則 |
| 主會議（NeurIPS、ICML、ICLR、COLM 等） | 目前不建議。至少要先補上信念的直接檢驗、KL 劑量反應、第二個模型，並公開 bf16 資料 | 通常 8–10 頁正文，以當期為準 |

投稿前要先解決 `REVIEW.md` 列出的作者決定，尤其是資料公開、LLM 使用揭露和獨立的預先登記存檔。

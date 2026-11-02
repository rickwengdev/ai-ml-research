# 新研究

從 2026-11 起，每項新研究一個資料夾 `<日期>-<主題>/`：

```
<日期>-<主題>/
  README.md     問題、結論、怎麼重跑
  prereg.md     預先登記；產生資料之前定稿，之後的修改附日期列在文末
  config.json   模型、向量、seed、port 等固定參數
  run.py        產生資料
  analyze.py    從 data/ 算出 results/
  data/         原始資料，產生後不改
  results/      表格、圖
```

只屬於這項研究的腳本放在這裡，寫得粗糙沒關係，但要能從 `config.json` 重跑。兩項以上研究會用到的程式，搬到 `../lib/`。

實驗在獨立的環境上跑，並在 `../experiment-log.md` 留一筆指向這個資料夾。

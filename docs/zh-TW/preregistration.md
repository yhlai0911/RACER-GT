# 預註冊 Protocol

請在第一次 confirmatory pull 前完成並鎖定本文件。

## 查詢定義

- 研究構念：
- 主要 search term 或 Topic ID：
- 替代定義：
- 地理區域：
- 類別：
- Search property：
- 語言與時區處理：
- 歷史起始日：
- 歷史終止日：

## 資料取得設計

- 收集日：0、1、2、7、14、21、30
- Streams：
- 每個 day × stream cell 的 technical replicates：
- 執行順序隨機化 seed：
- 裝置／瀏覽器／帳號／cookie／IP 設定：
- 網路中斷紀錄規則：

## Chunk 設計

- Window length：
- Step length：
- 最小可用 overlap：
- Pseudocount 或零值處理規則：
- 週頻／月頻 benchmark：

## 鎖定的 diagnostics

- Exact numeric-vector duplicate rule：
- Near-duplicate thresholds：
- Graph connectivity requirement：
- Maximum calibration residual：
- Minimum effective pull count：
- Detection reliability threshold：
- Level reliability threshold：
- Innovation reliability threshold：

## 決策規則

Day 0–2 的 MONITOR 結果只能偵測執行錯誤，不得用來刪除非完全相同的 pulls 或調整正式 thresholds。若查看 MONITOR 後更動程式碼、thresholds、stitching rule 或 decision tree，原資料一律視為 pilot，並重新開始 confirmatory day 0。

Formal acceptance 只能在 day-30 full batch 完成並鎖定後評估，而且不得使用下游價格、報酬、波動或顯著性結果作為判定依據。

## 必須保存的輸出

- Raw responses 與 SHA-256 hashes
- Request manifest 與 query fingerprint
- 軟體環境與 package version
- Calibration edges 與 offsets
- Exact／near-duplicate reports
- Consensus weights 與 effective pull count
- 全部 decision gates 與 sensitivity estimators

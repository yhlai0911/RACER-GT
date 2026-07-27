# Protocol 與驗證規範

## Confirmatory protocol

Day 0 之前必須固定研究構念、主要 term／Topic、替代定義、geo、category、search property、歷史起訖日、chunk plan、collection schedule、duplicate rules、reliability gates、consensus estimator、benchmark 方法與 stopping rule。若 Day 0–2 MONITOR 後出現任何實質規則修改，既有資料必須改列 pilot，並重新開始 confirmatory Day 0。

## 必要稽核紀錄

所有原始 retrieval 均須保留，包括 exact duplicates。至少記錄 `request_id`、pull/chunk ID、collection day、stream、replicate、execution order、UTC 擷取時間、實際回傳日期、returned frequency、partial status、raw-response hash、numeric-vector hash、軟體版本與 interruption log。

## 驗證狀態

開發版在隔離環境通過 25 項測試，另有一項需要 live network 的測試跳過。公開核心包含平衡設計、overlap plan、端到端 graph calibration、covariance-adjusted consensus 與 replay quality 測試。GitHub Actions 會在 Python 3.10–3.13 執行並保存 replay metrics。

## 解釋限制

protocol PASS 只表示預先指定的量測品質 gates 通過；它不代表構念效度、因果識別、歷史資料不修訂或即時可交易性成立。

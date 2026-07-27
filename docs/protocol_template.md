# RACER-GT 預先註冊與蒐集 Protocol 範本

## A. Estimand

- 主要估計目標：固定查詢規格與鎖定 retrieval distribution 下，共同尺度的相對搜尋興趣訊號。
- 明確排除：Google 絕對搜尋次數、由 IP 所定義的獨立樣本。
- 下游用途：報酬／波動／交易量／流動性／VaR／事件研究（擇一並預先指定）。

## B. Construct specification

- Primary term/topic：
- Topic ID 或 exact query string：
- Geo：
- Category：
- Search property：
- Language：
- 同義詞／替代構念：
- 不納入主要指標的 term：
- 預期可能的非財金搜尋意圖：
- 尖峰事件人工驗證規則：

## C. Historical window and time alignment

- Fixed start date：
- Fixed end date：
- Partial periods：一律排除。
- UTC／市場時區對齊規則：
- 對財金變數的可用資訊落後：
- 週末至下一交易日的聚合規則：

## D. Chunk protocol

- Window length：
- Step length：
- Minimum usable overlap：
- Minimum positive RSV for log ratio：
- Baseline normalization period：
- Reference chunk rule：
- Disconnected graph rule：FAIL／REVIEW（擇一）。

## E. Retrieval experiment

- Collection days：0, 1, 2, 7, 14, 21, 30（或其他預先指定值）。
- Streams：
- Technical replicates per day × stream：
- Time slots：
- Stream order balancing：
- Chunk order balancing：
- 固定於 stream 內的環境：device/browser/profile/cookie/login/IP 等。
- 任何偏離 protocol 的紀錄與處置：

## F. Pilot and confirmatory separation

- MONITOR 僅檢查：執行錯誤、exact duplicates、圖連通性、資料缺漏。
- 若 MONITOR 後修改 threshold、stitching、query、code 或 decision tree：所有既有 pulls 列為 pilot；重新開始 confirmatory Day 0。
- 禁止以財金 outcome 顯著性決定資料處理規則。

## G. Locked statistical settings

- Exact duplicate decimals：
- Near-duplicate raw correlation：
- Residual correlation：
- Exact-cell agreement：
- MAE/100：
- Positive Jaccard：
- Covariance estimator：
- Nonnegative weights：是／否。
- Weight cap：
- Benchmark mode：soft／exact。
- G-study block bootstrap replications：

## H. Acceptance decision

- Minimum unique pulls：
- Minimum spectral effective pulls：
- Maximum zero share：
- Minimum level G：
- Minimum innovation G：
- Minimum detection kappa（僅類別有變異時）：
- Maximum component share：
- Consensus convergence tolerance：
- Benchmark standardized RMSE tolerance：

## I. Archiving

永久保留：raw response、raw chunks、hashes、schedule、protocol.lock.yaml、程式版本、環境檔、audit logs、所有非通過 pulls 與 decision outputs。

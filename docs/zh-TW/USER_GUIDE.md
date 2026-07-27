# RACER-GT 使用指南

## 1. 安裝

```bash
python -m pip install . --no-build-isolation
```

## 2. 建立正式資料取得設計

```bash
racergt design --days 0,1,2,7,14,21,30 --streams A,B,C --replicates 2 --output collection_design.csv
```

此設計建立 42 個 complete-pull cells。stream 是複合取得環境；不同 IP 不等於獨立樣本。

## 3. 固定重疊請求

```bash
racergt manifest --design collection_design.csv --keyword "gold price" --geo TW --historical-start 2010-01-01 --historical-end 2026-06-30 --window-days 180 --step-days 60 --output request_manifest.csv
```

所有 collection dates 必須固定歷史終點、chunk plan、查詢設定、軟體版本與 request order。

## 4. 收集或匯入

透過核准的官方 API 或 Google Trends Explore，為每個 `request_id` 匯出一份 CSV。保存 raw file、UTC 擷取時間、partial flag、returned frequency 與 SHA-256。不得依財金結果決定保留哪些 pulls。

`fit` 所需最小 long table 欄位為：

```text
pull_id, chunk_id, date, value
```

正式研究仍應保存 collection day、stream、replicate、query fingerprint 與其他 audit metadata。

## 5. 重建

```bash
racergt fit --input collected_chunks.csv --output-dir results
```

輸出包括 reconstructed pulls、graph offsets、edge residuals、covariance-adjusted consensus 與 pull weights。

## 6. 可重現離線驗證

```bash
racergt replay --seed 42 --output replay_metrics.json
python examples/gt_collection_example.py
```

replay 對已知潛在訊號加入分段正規化、四捨五入、stream variation 與 correlated retrieval noise。它驗證程式行為，不代表 Google 未公開機制等同於此模擬。

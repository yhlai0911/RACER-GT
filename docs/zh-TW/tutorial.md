# 操作教學

## 一、建立 42-pull 實驗設計

```bash
racergt design --days 0,1,2,7,14,21,30 --streams A,B,C --replicates 2 --output collection_design.csv
```

## 二、鎖定歷史 request manifest

```bash
racergt manifest --design collection_design.csv --keyword "gold price" --geo TW --historical-start 2010-01-01 --historical-end 2026-06-30 --window-days 180 --step-days 60 --output request_manifest.csv
```

正式 pulls 之間不得更改歷史終點、chunk plan、查詢定義或軟體版本。

## 三、準備 raw long-format 資料

必要欄位：

```text
pull_id,chunk_id,date,value
```

建議保存的稽核欄位：

```text
collection_day,stream,replicate,retrieved_at,keyword,geo,category,
search_property,is_partial,raw_response_hash,query_fingerprint
```

## 四、執行尺度校準與重建

```python
import pandas as pd
from racergt import calibrate_overlap_graph, covariance_adjusted_consensus

raw = pd.read_csv("raw_chunks.csv")
calibration = calibrate_overlap_graph(raw)
consensus = covariance_adjusted_consensus(calibration.reconstructed)
consensus.series.to_csv("consensus.csv", index=False)
consensus.weights.to_csv("weights.csv", index=False)
```

## 五、執行 replay validation

```bash
python examples/05_real_gt_replay_validation.py
```

replay 使用已知的 latent daily curve，再加入 GT 式分段正規化、四捨五入、取得噪音與 repeated pulls。它驗證的是重建機制，不代表任何實際關鍵字一定具有構念效度。

## 六、結果解讀

- overlap graph 不連通表示共同尺度不可識別。
- exact duplicates 必須留在 audit archive。
- effective pull count 可能遠低於 nominal pull count。
- reliability 不等於 construct validity。
- 使用未來資訊的 retrospective smoothing 不得當成 real-time trading signal。

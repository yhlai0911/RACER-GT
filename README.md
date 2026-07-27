# RACER-GT

**Randomized Acquisition, Calibration, Error Decomposition, and Reliability for Google Trends**

RACER-GT 是一套用於建構長期、日頻 Google Trends（GT）相對搜尋興趣指標的研究型 Python 套件。它不將一次下載的 0--100 數列視為固定真值，也不把不同 IP 位址解釋為獨立樣本。套件將資料取得視為一項可預先註冊、可稽核的重複量測實驗，依序完成：

1. 鎖定查詢、歷史終點、chunk 邊界與蒐集設計；
2. 使用全域重疊圖校準每個 complete pull 內各 chunk 的相對尺度；
3. 依預先指定的 design-cell 權重建立透明的設計式參考估計量；
4. 保留 exact duplicates 的稽核紀錄，並以共同訊號移除後的殘差辨識 near-duplicate dependence；
5. 以三面向 Generalizability Theory 分解 historical date、collection day、collection stream 與交互作用；
6. 以共變異數調整的 GLS 建構潛在共識數列，而非任意刪除非相同 pulls；
7. 以週頻或月頻 benchmark 修正長期頻率尺度；
8. 分別評估 detection、level 與 daily innovation reliability；
9. 依預先鎖定的 decision tree 判定 PASS、REVIEW 或 FAIL；
10. 將 GT 測量誤差帶入後續財金迴歸，提供 reliability-corrected OLS 與 SIMEX。

> RACER-GT 估計的是「共同尺度下的潛在相對搜尋訊號」，不是 Google 的絕對搜尋次數。所有無偏性、一致性與最小變異結論都依賴文件中明列的識別假設。

## 安裝

由 wheel 安裝：

```bash
python -m pip install racergt-1.0.0-py3-none-any.whl
```

由原始碼安裝：

```bash
python -m pip install .
```

開發模式：

```bash
python -m pip install -e '.[dev]'
pytest -q
```

支援 Python 3.10 以上。

## 30 秒開始

### 1. 建立鎖定 protocol

```bash
racergt design examples/config_example.yaml \
  --out protocol_bundle \
  --anchor-date 2026-08-01
```

輸出：

- `protocol.lock.yaml`：設定與 SHA-256 protocol hash；
- `collection_schedule.csv`：平衡後的 collection day、stream、time slot 與 chunk order；
- `chunk_windows.csv`：所有固定的重疊查詢視窗；
- `protocol_manifest.json`：稽核 manifest。

### 2. 將 GT 回傳整理為 long-format raw chunks

每列是一個 `pull_id × chunk_id × historical_date` 觀察值。必要欄位如下：

```text
series_id,pull_id,chunk_id,historical_date,value,
collection_day,stream_id,replicate_id,window_start,window_end
```

建議另存：`retrieved_at`, `keyword`, `geo`, `category`, `search_property`, `language`, `is_partial`, `protocol_hash`, `raw_response_hash`, `network_event`。

### 3. 稽核與執行

```bash
racergt audit examples/config_example.yaml raw_chunks.csv --out audit.json

racergt run examples/config_example.yaml raw_chunks.csv \
  --benchmark lower_frequency_benchmark.csv \
  --out results
```

### 4. 受控模擬

```bash
racergt simulate examples/config_example.yaml --out simulation --seed 42
```

## Python API

```python
import pandas as pd
from racergt import RacerGTConfig, RacerGTPipeline

config = RacerGTConfig.load_yaml("examples/config_example.yaml")
raw = pd.read_csv("raw_chunks.csv")
benchmark = pd.read_csv("lower_frequency_benchmark.csv")

result = RacerGTPipeline(config).fit(raw, benchmark=benchmark)
result.save("results")

final_gt = result.final_series
print(result.decision.status)
print(final_gt.head())
```

## 輸入資料規格

### Raw chunk table

| 欄位 | 類型 | 說明 |
|---|---|---|
| `series_id` | string | 研究指標識別碼 |
| `pull_id` | string | 一次完整歷史重建的識別碼 |
| `chunk_id` | string | 固定查詢視窗識別碼 |
| `historical_date` | date | GT 觀察日期 |
| `value` | float | 原始 GT RSV，通常為 0--100 |
| `collection_day` | integer | 蒐集日的設計層級，不是歷史日期 |
| `stream_id` | string | 固定的複合蒐集環境 |
| `replicate_id` | string | day × stream cell 內的 technical replicate |
| `window_start` | date | chunk 起日 |
| `window_end` | date | chunk 迄日 |

`stream_id` 代表裝置、瀏覽器 profile、cookie、帳號狀態、IP 與其他固定條件所構成的**複合環境**；除非採 crossover factorial design，不能將估計出的 stream effect 解釋為 IP effect。

### Lower-frequency benchmark table

| 欄位 | 類型 | 說明 |
|---|---|---|
| `series_id` | string | 指標識別碼 |
| `period_start` | date | benchmark 期間起日 |
| `period_end` | date | benchmark 期間迄日 |
| `value` | float | 週頻或月頻 GT benchmark |
| `se` | float, optional | benchmark 標準誤；若缺省，使用 protocol 預設值 |

## 主要輸出

- `RACER_GT_final_series.csv`：最終日頻指標、條件式標準誤與信賴區間；
- `complete_calibrated_pulls.csv`：每個 complete pull 的校準結果；
- `calibration/*_chunk_scales.csv`：各 chunk 的全域尺度估計；
- `duplicates/`：exact groups、pairwise metrics、connected components 與殘差；
- `consensus/design_weighted_consensus.csv`：依預先指定 design-cell 權重建構的設計式參考估計量；
- `consensus/consensus_weights.csv`：GLS／最小變異權重；
- `gstudy/`：level、detection、innovation 的 ANOVA、variance components 與 D-study；
- `reliability/`：pairwise reliability、收斂路徑與 day/stream dependence；
- `decision/acceptance_decision_tree.csv`：逐條 acceptance rules；
- `report/RACER_GT_diagnostic_report.md`：圖表式診斷報告。

## 方法摘要

### 全域重疊圖校準

對 pull 內重疊 chunks `j` 與 `k`：

```text
log Y_jt - log Y_kt = ell_j - ell_k + nu_jkt.
```

RACER-GT 先以 Huber location 估計每條 overlap edge，再以 graph weighted least squares 一次估計全部 `ell_j`。相較逐段 stitching，此法使用所有可用重疊資訊，並輸出識別、連通性、condition number 與 cycle inconsistency 診斷。

### G-study

完全交叉設計：

```text
Y_tdsr = mu + T_t + D_d + S_s + TD_td + TS_ts + DS_ds + TDS_tds + E_tdsr.
```

套件分別對 level、`I(Y>0)` 與 `Delta log(1+Y)` 估計 variance components，並透過 D-study 比較增加 collection days、streams 或 technical replicates 對可靠度的邊際效益。

### 設計式參考估計量

令 `h` 表示預先鎖定的 day × stream design cell、`pi_h` 為事前指定權重：

```text
theta_hat_t^pi = sum_h pi_h mean_i(Y_thi).
```

只要 cell 內納入規則不依賴未觀察回傳值，這個分層平均對目標 retrieval-mixture expectation 無偏；pulls 的相依性只影響變異數。套件將它保留為透明的 design-based reference，而不是以它取代潛在訊號重建。

### 共變異數調整共識

在 `Z_t = 1 X_t + e_t`、`E(e_t)=0` 下：

```text
w* = Sigma^{-1}1 / (1' Sigma^{-1}1),
Xhat_t = w*' Z_t.
```

預設使用 Ledoit--Wolf shrinkage、非負權重與權重上限，降低小樣本 covariance inversion 的不穩定性。高度相依 pulls 不會被視為多份獨立證據。

### 頻率 benchmark

軟性模式求解：

```text
min_x (x-z)'Q(x-z) + (Ax-b)'W(Ax-b),
```

其中 `z` 是 preliminary daily consensus，`A` 是週／月聚合矩陣，`b` 是 lower-frequency benchmark。`Q` 同時控制對原數列的忠實度與修正路徑的平滑度。

## 統計保證的範圍

RACER-GT 不宣稱能從 proprietary GT 系統無條件證明「真實搜尋量」無偏。可證明的結果是：

- 在鎖定 retrieval distribution 下，分層 design-cell 平均對事前指定的 GT 期望混合值具 design-unbiasedness；
- overlap graph 連通、edge error 條件平均為零時，相對 log-scale WLS 可識別並在標準條件下保持無偏／一致；
- 已知或一致估計 `Sigma` 時，無限制 GLS 是線性無偏估計量中的最小變異估計量；
- lower-frequency benchmark 正確且約束可識別時，benchmark estimator 是明確二次目標下的唯一解；
- classical additive measurement error 假設成立時，reliability-corrected OLS 可修正 attenuation bias。

完整假設、命題與推導請見 `paper/RACER_GT_Methodology_zh_TW.pdf`。

## 受控 Monte Carlo（本版本）

20 次受控模擬中，平均 RMSE 為：

| 方法 | Mean RMSE |
|---|---:|
| Single pull | 7.2305 |
| Cross-pull median | 4.1710 |
| Simple mean | 3.7253 |
| RACER-GT | 3.5265 |

在此特定 DGP 下，RACER-GT 相較 single pull 降低約 51.2% RMSE，相較 simple mean 降低約 5.3%。這不是跨所有 DGP 的普遍保證；模擬程式與逐次結果均隨套件附上。

## Stata interoperability

核心估計器以 Python 實作，但所有表格皆可輸出 CSV 或 Stata 118 `.dta`：

```bash
racergt export-stata results/RACER_GT_final_series.csv RACER_GT_final_series.dta
```

`docs/stata_interop.md` 提供 `python:` block 與 shell 呼叫範例。

## 研究使用上的必要限制

- 不能把 static IP 當成獨立樣本證據；
- 不能在看過財金結果後調整 reliability threshold 或選擇 pulls；
- 若 Day 0--2 MONITOR 導致 protocol 或 decision rule 改變，這些資料必須列為 pilot，正式 batch 重新開始；
- exact duplicates 必須保留在 audit archive；
- PASS 僅代表本批資料通過已鎖定的測量規則，不代表關鍵字具有 construct validity，也不代表可作因果解釋；
- API／網站端點與服務條款可能改變，因此本套件採 ingestion-first 設計，不內建未經官方保證的 scraping 程式。

## 專案結構

```text
src/racergt/       核心套件
examples/          設定、模擬與真實資料範例
tests/             單元與整合測試
docs/              protocol、資料字典、數學與 Stata 文件
paper/             方法論論文 PDF 與 LaTeX 原始碼
monte_carlo_results/ 受控模擬逐次結果
```

## 授權與引用

MIT License。引用格式見 `CITATION.cff`。本版本為研究軟體 1.0.0；使用於正式論文前，應以研究關鍵字、地區與樣本期重新進行 simulation calibration、construct-validity review 與 preregistration。

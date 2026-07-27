# RACER-GT 與 Stata 串接

RACER-GT 的完整測量模型在 Python 執行；最終資料與所有診斷表皆可匯入 Stata。這樣可保留 Python 的圖論、共變異估計與套件測試，同時讓後續財金計量仍在 Stata 完成。

## 1. CLI 執行後匯出

```bash
racergt run protocol.lock.yaml raw_chunks.csv \
  --benchmark benchmark.csv --out results

racergt export-stata \
  results/RACER_GT_final_series.csv \
  results/RACER_GT_final_series.dta
```

Stata：

```stata
use "results/RACER_GT_final_series.dta", clear
format historical_date %td
sort historical_date
tsset historical_date, daily

* 例：以前 28 個日曆日的中位數建立異常搜尋注意力
* rangestat 為 SSC 套件；正式 protocol 應鎖定版本與邊界規則
capture which rangestat
if _rc ssc install rangestat
capture drop ln_gt med28 asvi28
gen ln_gt = ln(1 + value)
rangestat (median) med28=ln_gt, interval(historical_date -28 -1)
gen asvi28 = ln_gt - med28
```

此例明確排除當日值，避免 baseline 內含被解釋變數當期 shock。也可直接在 Python 中建立固定 lag baseline，並將結果連同 protocol hash 一起輸出，以避免兩套語言的邊界規則不一致。

## 2. 由 Stata 呼叫 Python CLI

```stata
shell racergt run protocol.lock.yaml raw_chunks.csv ///
    --benchmark benchmark.csv --out results

import delimited "results/RACER_GT_final_series.csv", clear varnames(1)
gen date = date(historical_date, "YMD")
format date %td
```

## 3. Stata 16+ `python:` block

```stata
python:
from racergt import RacerGTConfig, RacerGTPipeline
import pandas as pd

cfg = RacerGTConfig.load_yaml("protocol.lock.yaml")
raw = pd.read_csv("raw_chunks.csv")
bench = pd.read_csv("benchmark.csv")
res = RacerGTPipeline(cfg).fit(raw, benchmark=bench)
res.save("results")
end
```

## 4. 下游 measurement-error correction

RACER-GT 輸出 `standard_error`。Python 中可使用：

```python
from racergt.eiv import reliability_corrected_ols, simex_ols

fit = reliability_corrected_ols(
    y=next_day_return,
    x_observed=gt["value"],
    measurement_error_variance=gt["standard_error"] ** 2,
    controls=controls,
    hac_lags=7,
)
```

若在 Stata 估計主要財金模型，建議至少進行：

1. naive model；
2. 以多個 sample-specific GT pulls 重估係數分布；
3. 以 RACER-GT measurement-error interval 進行 Monte Carlo propagation；
4. 使用 bootstrap 將 GT construction 與財金模型一起重抽。

# Contributing to RACER-GT · 貢獻指南

*English below · 中文在後*

RACER-GT is research software attached to a published methodology. That
attachment shapes what a good contribution looks like: a change to an estimator
is simultaneously a change to a claim someone may already have cited.

---

## English

### Before you open a pull request

Run the same three checks CI runs:

```bash
uv venv --python 3.12 && uv pip install -r requirements-dev.txt
PYTHONPATH=src .venv/bin/pytest -q
.venv/bin/ruff check src tests examples scripts
PYTHONPATH=src .venv/bin/python -m racergt.cli simulate examples/config_example.yaml --out /tmp/sim --seed 42
```

The third one matters: a green unit-test suite does not prove the CLI still
produces an accepted batch.

### Changing an estimator

Any change to calibration, duplicate detection, variance components, consensus
weights, benchmarking, or the decision tree must come with:

1. **A statement of which proposition it affects.** The methodology manuscript
   (`docs/latex/methodology.en.tex`, `docs/latex/methodology.zh.tex`) and the
   mathematical appendix state conditional unbiasedness, efficiency, and
   uniqueness results. If your change alters the estimator, it alters what those
   propositions describe. Update both language versions.
2. **Monte Carlo evidence.** Run `examples/run_monte_carlo.py` before and after
   and report both tables. A change that improves RMSE but degrades innovation
   correlation is acceptable if you say so; a change that reports only the
   improved metric is not.
3. **A test that fails without the change.**

### The decision-tree key contract

`decision.evaluate_batch` reads diagnostics from every upstream stage by literal
string key (`spectral_effective_pulls`, `max_component_share`,
`final_convergence_mae_100`, and others). Renaming or removing one of those keys
does **not** raise: the rule silently becomes indeterminate and the batch
degrades from PASS to REVIEW. If you touch a `diagnostics` or `summary`
dictionary, check `decision.py` in the same commit.

### Documentation

Every document exists in Traditional Chinese and English. A pull request that
changes one language and not the other will be asked to complete the pair.
Build with `python scripts/build_docs.py` and commit the regenerated PDFs.

### What will be declined

- An embedded Google Trends scraper. The package is ingestion-first on purpose:
  endpoints, rate limits, authentication, and terms of service change, and a
  statistical method should not inherit that fragility.
- Any change that presents a stream effect as an IP effect.
- Relaxing a default acceptance threshold without evidence from data collected
  under a locked protocol.

### Reporting a methodological error

Open an issue with the `methodology` label. State the proposition, the step you
believe is wrong, and, if possible, a counterexample or a simulation that
exhibits the failure. Methodological corrections are the most valuable
contributions this project can receive, and they will be credited in the
changelog.

---

## 繁體中文

### 開 pull request 之前

執行 CI 會跑的同樣三項檢查：

```bash
uv venv --python 3.12 && uv pip install -r requirements-dev.txt
PYTHONPATH=src .venv/bin/pytest -q
.venv/bin/ruff check src tests examples scripts
PYTHONPATH=src .venv/bin/python -m racergt.cli simulate examples/config_example.yaml --out /tmp/sim --seed 42
```

第三項很重要：單元測試全過並不能證明 CLI 仍能產出通過驗收的批次。

### 修改估計器

任何對 calibration、duplicate detection、變異成分、consensus 權重、benchmarking 或 decision tree 的修改，都必須附上：

1. **說明影響到哪一條命題。** 方法論主文與數學附錄陳述了條件式無偏性、效率與唯一性結果。若您的修改改變了估計器，就改變了那些命題所描述的對象。**中英兩版都要更新。**
2. **Monte Carlo 證據。** 修改前後各跑一次 `examples/run_monte_carlo.py`，兩份表格都要附上。若某項修改改善 RMSE 但惡化 innovation correlation，只要據實說明即可接受；只報告改善那一欄則不可接受。
3. **一個在修改前會失敗的測試。**

### Decision tree 的鍵值契約

`decision.evaluate_batch` 以字面字串鍵讀取上游各階段的診斷值（`spectral_effective_pulls`、`max_component_share`、`final_convergence_mae_100` 等）。重新命名或移除其中任一鍵**不會拋錯**：該規則會靜默變成 indeterminate，整批結果由 PASS 降級為 REVIEW。若您動到任何 `diagnostics` 或 `summary` 字典，請在同一個 commit 內檢查 `decision.py`。

### 文件

每份文件都有繁體中文與英文版本。只改一種語言的 pull request 會被要求補齊另一種。以 `python scripts/build_docs.py` 建置，並提交重新產生的 PDF。

### 不會被接受的修改

- 內建 Google Trends 抓取程式。本套件刻意採 ingestion-first：端點、rate limit、認證與服務條款都會變，統計方法不該繼承那份脆弱性。
- 任何把 stream effect 當作 IP effect 呈現的修改。
- 在沒有「鎖定 protocol 下蒐集之資料」作為證據時，放寬預設驗收門檻。

### 回報方法論錯誤

開 issue 並加上 `methodology` 標籤。請說明是哪一條命題、您認為錯在哪一步，可能的話附上反例或能重現失效的模擬。方法論上的更正是本專案最有價值的貢獻，會列名於 changelog。

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案性質

RACER-GT 1.0.0 是**研究型軟體**：一個 Python 套件（`src/racergt/`）加上一篇隨附的繁體中文方法論論文（`paper/RACER_GT_Methodology_zh_TW.tex/.pdf`，31 頁）。套件把 Google Trends 資料取得視為可預先註冊的重複量測實驗，估計「共同尺度下的潛在相對搜尋訊號」。

三個影響日常工作的事實：

- **這個目錄不是 git repo**，是 release bundle 的解壓內容（含 `dist/` 已建好的 wheel 與 sdist）。沒有 commit 歷史可查，也沒有 CI 設定。
- **`paper/` 的論文是方法論的權威來源**。任何估計器行為的改動（權重、變異數分解、benchmark 目標函數）都必須與論文中的命題與推導保持一致，否則會讓已發布的證明失效。改演算法前先確認論文怎麼寫。
- **語言分工**：程式碼、docstring、CLI help 一律英文；`README.md`、`docs/`、論文為繁體中文。沿用這個分工，不要混寫。

## 環境與常用指令

套件採 src-layout，且**刻意不預先安裝**——`Makefile` 全部靠 `PYTHONPATH=src` 匯入。這讓 release bundle 在未安裝狀態下也能完整驗證。

已用 `uv` 建好 `.venv`（Python 3.12，已裝 `requirements-dev.txt`）：

```bash
# 重建環境
uv venv --python 3.12 && uv pip install -r requirements-dev.txt

# 全套測試（等同 make test；目前 9 passed，約 12 秒）
PYTHONPATH=src .venv/bin/pytest -q

# 單一測試檔 / 單一測試
PYTHONPATH=src .venv/bin/pytest tests/test_overlap.py -q
PYTHONPATH=src .venv/bin/pytest tests/test_pipeline.py::test_end_to_end_pipeline -q

# CLI（未安裝時用 -m；已安裝時 entry point 是 racergt）
PYTHONPATH=src .venv/bin/python -m racergt.cli --help

# 端到端煙霧測試：產生受控模擬資料並跑完整 pipeline
PYTHONPATH=src .venv/bin/python -m racergt.cli simulate examples/config_example.yaml \
  --out /tmp/sim --seed 42

# 20 次 Monte Carlo（等同 make simulate，會覆寫 monte_carlo_results/）
PYTHONPATH=src .venv/bin/python examples/run_monte_carlo.py

# 編譯論文（latexmk + xelatex 已安裝）
make paper

make build   # python -m build → dist/
make clean
```

**Lint 不是門檻**：`pyproject.toml` 設定了 ruff（line-length 100、py310），但現況 `ruff check src tests examples` 有 45 項既有違規（B008、RUF046、I001 等）。不要在無關的任務裡順手全域 `--fix`——那會製造大範圍 diff 並使 `SHA256SUMS_PROJECT.txt` 失效。只清理自己動過的檔案。

## 架構

### 資料形狀的三段轉換

理解整個套件的關鍵是追蹤資料形狀，由 `schema.py` 統一定義：

1. **Long raw chunks** — 一列 = `pull_id × chunk_id × historical_date`。必要欄位見 `RAW_REQUIRED_COLUMNS`。這是外部收集器唯一要滿足的契約（`docs/collection_workflow.md` 的 adapter contract）。
2. **Long complete pulls** — 每個 pull 內的 chunks 經 overlap-graph 校準並接合後，一列 = `pull_id × historical_date`（`COMPLETE_PULL_REQUIRED_COLUMNS`）。
3. **Wide pull matrix** — `wide_pull_matrix()` 樞紐成 `index=historical_date × columns=pull_id`。**幾乎所有跨 pull 的估計器（duplicates、consensus、reliability）都吃這個 wide matrix**；只有 G-study 吃 long 的 complete pulls（因為要拆 day/stream/replicate facet）。

注意 `wide_pull_matrix` 用 `pivot`，若同一 `(historical_date, pull_id)` 出現兩次會直接拋錯，不會靜默聚合。

### Pipeline DAG

`RacerGTPipeline.fit()`（`pipeline.py`）是唯一的協調點，順序有真實相依：

```
audit_raw_batch ──(可 raise)──▶ coerce_raw_chunks
                                     │
              per-pull ▶ OverlapGraphCalibrator.fit  ← 唯一產生 complete pull 的地方
                                     │
                              wide_pull_matrix
                    ┌────────────────┼────────────────┬──────────────┐
          diagnose_duplicates  fit_gls_consensus  assess_reliability  │
          fit_design_weighted_consensus                        run_all_gstudies (吃 long)
                                     │
                          temporal_benchmark（僅當有 benchmark 且 config.benchmark.enabled）
                                     │
                              evaluate_batch  ▶  PASS / REVIEW / FAIL
```

`final_series` 的定義在 `PipelineResult.final_series`：**有 benchmark 就回傳 benchmark 結果，否則回傳 GLS consensus**。

### 兩個 consensus 估計器，用途不同

這是最容易誤解的設計。兩者**並存且都會輸出**，但只有一個進入最終數列：

- `fit_gls_consensus()` — 共變異數調整的最小變異估計量，是 `final_series` 的來源。會先摺疊 exact duplicates、對齊 pull-level offset、估 Ledoit–Wolf 共變異數、解非負且有上限的權重。
- `fit_design_weighted_consensus()` — 依事前指定的 day × stream design-cell 權重做分層平均。這是**透明的 design-based 參考估計量**，用來對照，**不參與** `final_series`。不要把它「優化」掉或拿去取代 GLS 結果，那會破壞論文中的 design-unbiasedness 論證。

### Config 就是 protocol，hash 是雙向閘門

`RacerGTConfig`（`config.py`）是巢狀 pydantic 模型，全部 `extra="forbid"`——YAML 多一個鍵就驗證失敗。

`protocol_hash()` 對 canonical JSON 取 SHA-256。關鍵行為：`load_yaml()` 會把檔案裡存的 `protocol_hash` 與重算值比對，**不符即 raise**。所以：

- 手動編輯 `protocol.lock.yaml` 的任何設定值一定會壞掉，除非同步更新 hash（正確做法是改來源 config 再重新 `save_yaml`）。
- 新增任何 config 欄位都會改變所有既有 protocol 的 hash。這是刻意的 reproducibility 機制，不是要繞開的障礙。

`QuerySpec` 的 `baseline_start/end` 若省略會在 validator 裡回填為 historical 全區間，並強制落在 historical window 內。

### Result 物件自我序列化

每個階段回傳自己的 dataclass（`CalibrationResult`、`DuplicateDiagnostics`、`ConsensusResult`、`GStudyResult`、`ReliabilityResult`、`BenchmarkResult`、`DecisionResult`），各自帶 `.save(dir)`。`PipelineResult.save()` 只是把它們派到子目錄並補寫 `summary.json`。新增輸出時遵循同一慣例：在該階段的 Result 上加 `save`，而不是在 pipeline 裡塞 `to_csv`。

### ⚠️ decision.py 的隱性字串鍵契約

`evaluate_batch()`（`decision.py`）用**字面字串**去讀上游各階段的 `diagnostics` / `summary` dict：

| 讀取來源 | 鍵 |
|---|---|
| `audit.summary` | `zero_share` |
| `CalibrationResult.diagnostics` | `connected` |
| `consensus.diagnostics` | `n_unique_pulls`, `spectral_effective_pulls` |
| `duplicates.summary` | `max_component_share` |
| `gstudies[*].coefficients` | `generalizability_coefficient` |
| `reliability.summary` | `detection_fleiss_kappa`, `final_convergence_mae_100` |
| `benchmark.diagnostics` | `benchmark_standardized_rmse` |

**重新命名或移除其中任一鍵不會拋錯**——`.get()` 取到 `np.nan`，`_finite()` 判定為 false，該規則的 `passed` 變成 `None`，於是整批結果從 PASS 默默降級成 REVIEW。改動任何階段的 diagnostics 鍵時，務必同步檢查 `decision.py`，並跑 `test_pipeline.py` 確認 status 沒被意外改變。

判定邏輯：任一 mandatory 規則 `False` → FAIL；任一 mandatory 規則 `None` → REVIEW；否則 PASS。`detection_reliability` 的 mandatory 旗標是動態的（僅當 `0 < zero_share < 1` 才強制）。

### 例外與 CLI 退出碼

- `OverlapGraphError`（`overlap.py`）：overlap graph 不連通且 `calibration.allow_disconnected=False` 時拋出。這通常代表 chunk 設計的 `min_overlap_days` 太嚴或資料有缺口，不是程式錯誤。
- `RacerGTPipeline.fit(stop_on_audit_error=True)` 預設在 audit 有 error 時 raise。
- `fit_gls_consensus` 要求至少 2 個 pull，且每個 pull 在 baseline 區間必須有正的有限均值。
- CLI 退出碼：`audit` 失敗 → 2；`run` 得到 FAIL → 3。腳本化時可直接依賴。

### 設計術語的精確含義

- `pull_id`（`P001`、`P002`…）= 一次完整歷史重建，對應一個 (collection_day × stream × replicate) 格。
- `collection_day` 是 `day_offsets` 的**序數索引**（0, 1, 2…），**不是** day offset 本身，也不是日曆日期。`generate_collection_schedule` 另外輸出 `day_offset` 與 `planned_collection_date`。
- `stream_id` 是裝置／瀏覽器 profile／cookie／帳號狀態／IP 的**複合環境**。程式碼與文件都不可把估出的 stream effect 解釋為 IP effect（除非採 crossover factorial design）。

## 測試慣例

- **測試沒有磁碟上的 fixture 資料**；全部由 `simulation.simulate_racergt_data()` 就地產生受控 DGP。要新增測試就走同一條路，不要新增 CSV。
- `tests/conftest.py` 的 `small_config` fixture 刻意把 `decision.*` 門檻大幅放寬（如 `min_unique_pulls=3`、`min_detection_kappa=-1.0`）。原因是測試用的迷你設計（2–6 個 pull）本來就達不到正式研究門檻；**不要「修正」這些值**，否則測試會全面轉成 FAIL。
- 端到端測試靠與已知 latent truth 的相關係數斷言（如 `corr > 0.85`）。改動估計器後若這類斷言掉下來，先查是否真的退化，再考慮調整。

## 修改後的維護動作

- `SHA256SUMS_PROJECT.txt` 是 release 完整性清單，涵蓋 61 個檔案，目前全部相符（`shasum -a 256 -c SHA256SUMS_PROJECT.txt`）。**沒有腳本會自動重生**，是發布時手動產生的。任何原始檔改動都會讓它失效——修改後要嘛重新產生，要嘛在說明中明確指出它已過期。
- 版本號 `1.0.0` 出現在 `pyproject.toml`、`src/racergt/__init__.py` 的 `__version__`、`CHANGELOG.md`、`RELEASE_NOTES.md`、`RELEASE_VALIDATION.md`。改版時要一起動。
- `dist/` 內的 wheel 與 sdist 是舊版建置產物，改了 `src/` 之後它們就過期了；`make build` 前會先 `make clean`。

## 已知的範圍限制（寫進論文與 README，不要無意間宣稱超出）

- 本套件**不內建 Google Trends scraper**，這是刻意的 ingestion-first 設計（服務條款與端點會變）。不要新增未經官方保證的抓取程式。
- 1.0.0 的 G-study 用平衡設計的動差法估變異成分；不平衡設計的 REML 是未來擴充。
- consensus 的信賴區間是條件式近似；正式推論需 full-pipeline block bootstrap。
- PASS 只代表該批資料通過已鎖定的量測規則，不代表關鍵字具 construct validity，也不代表可作因果解釋。

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案性質

RACER-GT 1.0.0 是**研究型軟體**：一個 Python 套件（`src/racergt/`）加上一篇隨附的繁體中文方法論論文（`paper/RACER_GT_Methodology_zh_TW.tex/.pdf`，31 頁）。套件把 Google Trends 資料取得視為可預先註冊的重複量測實驗，估計「共同尺度下的潛在相對搜尋訊號」。

三個影響日常工作的事實：

- **git 遠端是 `yhlai0911/RACER-GT`（public）**。本地樹是權威來源；遠端早期的 bootstrap 版本已由一個 `-s ours` merge 取代，其歷史仍保留在 DAG 中可回溯。
- **`docs/latex/` 的方法論論文是權威來源**。任何估計器行為的改動（權重、變異數分解、benchmark 目標函數）都必須與論文中的命題與推導保持一致，否則會讓已發布的證明失效。改演算法前先確認論文怎麼寫，且**中英兩版都要更新**。
- **語言分工**：程式碼、docstring、CLI help 一律英文。文件一律**雙語成對**——`docs/latex/<slug>.zh.tex` 與 `<slug>.en.tex`。只改一種語言就是未完成。

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

**Lint 是門檻**：`pyproject.toml` 明確鎖定規則集 `E,F,W,I,UP,B,C4,RUF`（刻意不依賴 ruff 預設值，因為預設會隨版本擴張而讓 CI 無故變紅）。目前全清。兩個 ignore 是刻意的且已在 pyproject 註明理由：`B008`（typer 需要在預設值呼叫 `Argument()`/`Option()`）、`report.py` 的 `W291`（Markdown 硬換行的兩個尾隨空白）。

**建置文件**：`make docs`（等同 `python scripts/build_docs.py`）。需要 latexmk + XeLaTeX 與五個 Noto 字型家族（見 `docs/latex/_common.tex` 開頭）。macOS 以 brew cask 安裝；CI 以 apt 安裝，**中文版另需 `texlive-lang-chinese` 提供 `xeCJK.sty`**。

**改動檔案後**：跑 `make checksums` 重新產生 `SHA256SUMS_PROJECT.txt`，否則 `shasum -c` 會出現過期失敗。

### CI 觸發條件（會影響你看到什麼）

- `tests.yml`：每次 push 與 PR 都跑。
- `docs.yml`：**只在 `docs/latex/**`、`scripts/build_docs.py` 或 `docs.yml` 本身變動時才跑**。所以改了程式碼卻沒看到 docs 執行是正常的，不是壞掉。`docs/pdf/**` 刻意不在觸發清單內——那是產物，提交產物不該再觸發一次重建。需要時可用 `gh workflow run docs.yml` 手動觸發。
- `release.yml`：`v*` tag 觸發。PyPI 發布另外需要 repo variable `PYPI_PUBLISH=true` 才會執行（PyPI 版本號永久不可重用，不該由 tag 靜默觸發）。
- 三個 workflow 都設 `cancel-in-progress`，連續推 commit 時舊的 run 會顯示 `cancelled`，這是預期行為。

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

### decision.py 的字串鍵契約

`evaluate_batch()`（`decision.py`）以具名常數（`KEY_*`）讀取上游各階段的 `diagnostics` / `summary` dict：

| 讀取來源 | 鍵 |
|---|---|
| `audit.summary` | `zero_share` |
| `CalibrationResult.diagnostics` | `connected` |
| `consensus.diagnostics` | `n_unique_pulls`, `spectral_effective_pulls` |
| `duplicates.summary` | `max_component_share` |
| `gstudies[*].coefficients` | `generalizability_coefficient` |
| `reliability.summary` | `detection_fleiss_kappa`, `final_convergence_mae_100` |
| `benchmark.diagnostics` | `benchmark_standardized_rmse` |

**移除或重新命名其中任一鍵會拋 `KeyError`，不是靜默降級。** 這一點在 commit `1c72851`（"remove three silent failure modes"）修正過：舊版用 `.get(key, nan)`，取不到就變 `NaN`、`_finite()` 判偽、規則 `passed=None`，整批從 PASS 默默降成 REVIEW。現在 `_require` 直接 raise，因為「鍵不存在」是接線錯誤，必須與「規則真的無法判定」區分開。2026-07-28 以五個鍵逐一實測確認。

所以改動 diagnostics 鍵時**不需要**為靜默降級做防禦性檢查——測試會直接紅。但仍要跑 `test_pipeline.py`，因為改的若是鍵的**值**而非名稱，那才會安靜地改變 status。

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

- `SHA256SUMS_PROJECT.txt` 由 `make checksums` 從 `git ls-files` 產生，清單與 repo 不會漂移。改動任何被追蹤的檔案後都要重跑。
- 版本號的單一來源有兩處必須同步：`pyproject.toml` 與 `src/racergt/__init__.py`；文件的版本字串來自 `docs/latex/_meta.tex`（改一行即可全體生效）。`release.yml` 會在 git tag 與 `racergt.__version__` 不一致時**拒絕發布**。
- `dist/` 內的 wheel 與 sdist 是建置產物；`make build` 前會先 `make clean`。
- Monte Carlo 可重現到**約 10 位有效數字**，不是位元完全相同——BLAS 加總順序在不同執行間會變。任何宣稱「bit-for-bit」的說法都是錯的。

## 已知的範圍限制（寫進論文與 README，不要無意間宣稱超出）

- 本套件**不內建 Google Trends scraper**，這是刻意的 ingestion-first 設計（服務條款與端點會變）。不要新增未經官方保證的抓取程式。
- 1.0.0 的 G-study 用平衡設計的動差法估變異成分；不平衡設計的 REML 是未來擴充。
- consensus 的信賴區間是條件式近似；正式推論需 full-pipeline block bootstrap。
- PASS 只代表該批資料通過已鎖定的量測規則，不代表關鍵字具 construct validity，也不代表可作因果解釋。

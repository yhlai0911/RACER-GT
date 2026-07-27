# RACER-GT

**Google Trends 的隨機化取得、尺度校準、誤差分解與可靠訊號重建框架**

[English README](README.md)

RACER-GT 是一套研究導向的 Python 套件，用於從多次、分段且各自正規化的 Google Trends（GT）資料，建構長期日頻共同尺度搜尋注意力指標。它特別處理單次下載偏誤、分段 0–100 尺度不一致、重複 pull 相依性及下游 measurement-error bias。

RACER-GT **不宣稱恢復絕對搜尋次數**；其估計目標是在固定查詢定義、鎖定資料取得 protocol 及明確統計假設下的共同尺度潛在相對搜尋訊號。

## 核心功能

- collection day × stream × technical replicate 的平衡實驗設計。
- 固定歷史終點、重疊 chunk 與隨機執行順序的 request manifest。
- 使用全部重疊方程的全域 overlap-graph calibration。
- exact duplicate 與 residual-based near-duplicate diagnostics。
- Generalizability Theory、D-study 與 covariance-adjusted consensus。
- 週頻／月頻尺度校正及下游 measurement-error correction。
- Monte Carlo 與真實 GT 曲線 replay validation。

## 安裝與測試

```bash
python -m pip install . --no-build-isolation
python -m pytest -q
```

隔離環境驗證結果：**25 passed、1 skipped**；跳過項目需要外部 Google Trends 網路連線。

## 42-pull 正式設計範例

```bash
racergt design --days 0,1,2,7,14,21,30 --streams A,B,C --replicates 2 --output collection_design.csv
racergt manifest --design collection_design.csv --keyword "gold price" --geo TW --historical-start 2010-01-01 --historical-end 2026-06-30 --window-days 180 --step-days 60 --output request_manifest.csv
```

詳見 [繁體中文文件](docs/zh-TW/) 與 [English documentation](docs/en/)。

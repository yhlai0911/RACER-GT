# 安裝說明

## 系統需求

- Python 3.10–3.12
- Git

## 從原始碼安裝

```bash
git clone https://github.com/yhlai0911/RACER-GT.git
cd RACER-GT
python -m venv .venv
source .venv/bin/activate  # Windows：.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

## 驗證

```bash
python -m pytest -q
python examples/05_real_gt_replay_validation.py
```

若要安裝可選的 collector 相依套件：

```bash
python -m pip install -e '.[collect]'
playwright install chromium
```

統計核心不需要即時連線 Google。正式研究僅應使用經授權的 API 或受控的 CSV 匯出資料。

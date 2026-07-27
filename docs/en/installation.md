# Installation

## Requirements

- Python 3.10–3.12
- Git

## Install from source

```bash
git clone https://github.com/yhlai0911/RACER-GT.git
cd RACER-GT
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

## Validate

```bash
python -m pytest -q
python examples/05_real_gt_replay_validation.py
```

The optional collector dependency is installed with:

```bash
python -m pip install -e '.[collect]'
playwright install chromium
```

The statistical core does not require live Google access. Use only authorized API access or controlled CSV exports for substantive collection.

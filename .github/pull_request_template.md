## What this changes

## Checklist

- [ ] `PYTHONPATH=src pytest -q` passes
- [ ] `ruff check src tests examples scripts` passes
- [ ] `racergt simulate examples/config_example.yaml --out /tmp/sim --seed 42` still returns PASS

### If this touches an estimator

- [ ] States which proposition in the methodology manuscript is affected
- [ ] Both language versions of the affected document are updated
- [ ] Monte Carlo output before and after is included below, **including any
      metric that got worse**
- [ ] A test that fails without this change

### If this touches a `diagnostics` or `summary` dictionary

- [ ] `decision.py` checked in the same commit — it reads those dictionaries by
      literal string key, and a rename silently degrades PASS to REVIEW rather
      than raising

## Monte Carlo before / after

<!-- paste both tables, or write "not applicable" -->

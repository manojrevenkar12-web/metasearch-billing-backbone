# Working on metasearch-billing-backbone

## Fast feedback

```bash
pytest -q                                   # pipeline, metrics, orchestration (Postgres tests need MBB_TEST_PG)
ruff check src scripts tests
python3 scripts/evaluate.py --check         # the committed reports/dev.json is what the code produces (~30 min)
python3 scripts/readme.py && git diff --exit-code README.md web/public/data/dashboard.json
cd web && npm test && npm run build
```

## Invariants

1. **The truth stays in the world.** `src/mbb/world/` writes `truth/`; nothing else in `src/mbb` reads it.
   Only `scripts/evaluate.py` does (`tests/test_pipeline.py` checks the imports).
2. **A file is loaded once, and only when complete.** The manifest must be in and match the bytes; a path or
   a content hash already loaded is never loaded again.
3. **Invoices are only added.** After issue, a change is a credit or debit note. Never update or delete a row
   in `invoice_register`.
4. **Money is integers.** Prices and amounts are minor units (`*_minor`, BIGINT). Floats only for FX rates.
5. **Every check writes a result.** A new check returns `CheckResult`s and is recorded by `ControlStore.record_checks`;
   blocking checks are scoped `partner/month`, monitoring checks `brand/day`.
6. **One SQL, two engines.** Models in `src/mbb/models/` are DuckDB SQL that `mbb.trino` translates; CI runs them on
   Trino and compares every row (`scripts/trino_parity.py`). No engine-specific functions in a model.
7. **Settings live in config.** Thresholds, safeguards, dates: `config/pipeline.toml`. Metrics: `config/metrics.toml`.
8. **Reports are generated.** `reports/*.json` by `scripts/evaluate.py` and `scripts/bench.py`; the README results,
   the chart and the dashboard data by `scripts/readme.py`.

## The held-out rule

`python3 scripts/evaluate.py --heldout` runs the held-out world once and writes `config/heldout.lock`. After
that, changes are measured on the dev world only, and the held-out numbers stay as they first came out.

# Bug hunting test

**TEST DATA ONLY - NEVER PUT REAL FINANCIAL DATA IN THIS DIRECTORY.**

This directory contains the manual V1 release-candidate bug-hunting plan and deterministic synthetic fixtures.

## Files committed to the repository

- `BUG_HUNTING_TEST_PLAN.md` - full manual pre-`v1.0.0` checklist.
- `bug-hunting-test-reconciliation-valid-italian-semicolon.csv` - valid Italian-style CSV.
- `bug-hunting-test-reconciliation-duplicate-external-id.csv` - must fail atomically.
- `bug-hunting-test-reconciliation-wrong-currency.csv` - must fail for an EUR account.
- `bug-hunting-test-reconciliation-zero-amount.csv` - must fail atomically.
- `bug-hunting-test-reconciliation-ambiguous-headers.csv` - must reject ambiguous normalized headers.
- `bug-hunting-test-invalid-not-sqlite.sqlite3` - deliberately invalid restore source.
- `generate_large_csv.py` - deterministic generator for the row-limit stress corpus.

## Large GitHub artifact

The workflow **Bug hunting test artifacts** generates and uploads the GitHub Actions artifact:

`bug-hunting-test-csv-corpus`

It contains:

- `bug-hunting-test-reconciliation-10000-valid.csv` - exact allowed row-count maximum.
- `bug-hunting-test-reconciliation-10001-too-many.csv` - must be rejected by the 10,000-row limit.

The generated files contain only synthetic deterministic data. They are kept out of Git history intentionally so normal clones remain small.

You can also regenerate them locally:

```bash
python bug-hunting-test/generate_large_csv.py
```

Generated files are written to `bug-hunting-test/generated/`.

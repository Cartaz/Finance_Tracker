# Bug hunting test — CSV byte-size limits

> **BUG HUNTING TEST ONLY. Never use real financial data.**

These checks complement `BUG_HUNTING_TEST_PLAN.md` and target the independent 10,000,000-byte reconciliation limit.

- [ ] **SIZE01 BLOCKER/PERF** Download/regenerate `bug-hunting-test-reconciliation-near-10mb-valid.csv`. Confirm it contains 9,500 rows and is below 10,000,000 bytes.
- [ ] **SIZE02 BLOCKER/PERF** Import it into a disposable active EUR balance account. It must pass the byte-size gate and complete normally; record elapsed time, peak RAM/CPU if convenient, and any UI freeze duration.
- [ ] **SIZE03 BLOCKER** Download/regenerate `bug-hunting-test-reconciliation-over-10mb.csv`. Confirm it contains 9,500 rows but exceeds 10,000,000 bytes.
- [ ] **SIZE04 BLOCKER** Import it. It must be rejected specifically by the 10 MB limit before reconciliation parsing/posting creates a partial batch.
- [ ] **SIZE05 BLOCKER** After the rejected import, restart Finance Tracker and verify transaction count, balances and import-batch list are unchanged.

The files are generated deterministically by `bug-hunting-test/generate_large_csv.py` and uploaded by the GitHub Actions workflow **Bug hunting test artifacts** in the artifact `bug-hunting-test-csv-corpus`.

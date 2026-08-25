# Finance Tracker V1 - Bug Hunting Test Plan

> **BUG HUNTING TEST ONLY. Never use real financial data.**
>
> Do not create/tag `v1.0.0` until every **BLOCKER** passes or has been fixed and re-tested. For every anomaly record test ID, exact steps, expected/actual result, reproducibility, screenshot/video, relevant log excerpt, environment and tested commit SHA.

## A. Clean install / startup

- [ ] **A01 BLOCKER** Fresh clone into a new directory.
- [ ] **A02 BLOCKER** From a different CWD run `chmod +x /path/to/Finance_Tracker/install.sh` and `/path/to/Finance_Tracker/install.sh`.
- [ ] **A03 BLOCKER** Confirm `.venv` is created inside the repository, not caller CWD.
- [ ] **A04 BLOCKER** Run `install.sh` twice; second run must be idempotent.
- [ ] **A05 BLOCKER** Launch with `.venv/bin/python main.py` without unhandled traceback.
- [ ] A06 Close/reopen five times.
- [ ] A07 Verify `~/.local/share/finance-tracker/logs/finance-tracker.log` exists.
- [ ] A08 Malformed settings JSON -> safe defaults + diagnostic log.
- [ ] A09 Valid JSON with wrong top-level type (`[]`) -> safe defaults + diagnostic log.

## B. KDE / window / accessibility

- [ ] **B01 BLOCKER** Minimum window size is 1200x800.
- [ ] B02 Test 1200x800, 1440x900, 1920x1080 and maximized; no clipped primary controls.
- [ ] **B03 BLOCKER** Test KDE 100% plus at least one fractional/HiDPI scale (125/150% or equivalent).
- [ ] B04 Move between monitors with different scale factors if available.
- [ ] **B05 BLOCKER** Keyboard-only navigation works and focus is clearly visible.
- [ ] B06 Tab order is logical; scroll areas work via mouse/touchpad/keyboard.
- [ ] B07 Long account/category/payee names do not destroy layout.
- [ ] B08 Selected/disabled/error states remain legible on dark neumorphic surfaces.

## C. First-book bootstrap / product usability

- [ ] **C01 BLOCKER** Create EUR personal book and verify persistence after restart.
- [ ] **C02 BLOCKER** Create ASSET and LIABILITY accounts with realistic tracking dates.
- [ ] C03 Create parent/child EXPENSE categories and multiple payees, including Unicode names.
- [ ] **C04 PRODUCT BLOCKER** Determine whether a normal user can represent an existing situation (e.g. bank EUR 2,500, card -EUR 400, salary workflow) without hidden/manual DB work.
- [ ] **C05 PRODUCT BLOCKER** If opening balance, manual income or manual transfer are not naturally available, document exact missing workflow. Treat as V1 blocker if normal use requires workaround.

## D. Money magnitude invariant

- [ ] **D01 BLOCKER** `45`, `45,00`, `45.00` -> accepted as exact magnitude 45.00.
- [ ] **D02 BLOCKER** `0`, `0,00` -> rejected with no ledger mutation.
- [ ] **D03 BLOCKER** `-45`, `+45` -> explicitly rejected; never normalized silently.
- [ ] D04 `-45€`, `45€`, spaces, empty, letters, `NaN`, `Infinity`, scientific notation -> deterministic validation.
- [ ] **D05 BLOCKER** Test very large exact amount; no JS/2^53 precision loss.
- [ ] **D06 BLOCKER** Every rejected input leaves balances and transaction count unchanged.

## E. Tracking boundary

- [ ] **E01 BLOCKER** Before tracking start -> rejected.
- [ ] **E02 BLOCKER** After tracking start -> accepted.
- [ ] **E03 BLOCKER** Same date with insufficient time precision -> explicit ambiguity where policy requires it.
- [ ] E04 Same date with sufficient before/after time -> correct classification.
- [ ] **E05 BLOCKER** Scheduled, reconciliation and loan workflows obey the same canonical boundary semantics.

## F. Ledger / expenses / history

- [ ] **F01 BLOCKER** Basic expense decreases source balance exactly and creates correct expense posting.
- [ ] F02 Create 20+ expenses, including repeated same date/amount/payee.
- [ ] F03 Unicode descriptions/payees remain intact after restart.
- [ ] **F04 BLOCKER** Historical data remains readable after account/category archival.
- [ ] **F05 BLOCKER** No operation creates an unbalanced transaction.

## G. FX / reporting

- [ ] **G01 BLOCKER** Create second-currency account and historical FX rates.
- [ ] **G02 BLOCKER** Reporting uses correct date-specific historical rate.
- [ ] G03 Verify latest-known-on-or-before-date semantics where documented.
- [ ] **G04 BLOCKER** Missing required FX must fail closed/show incomplete state, never silently partial totals.
- [ ] G05 Exercise small/large rates and half-cent rounding boundaries.
- [ ] **G06 BLOCKER** Transfers remain book-level neutral; refunds follow canonical reporting semantics.
- [ ] **G07 BLOCKER** Restart does not change converted totals.

## H. CSV reconciliation - format/validation

Use a disposable active EUR balance account.

- [ ] **H01 BLOCKER** Import `bug-hunting-test-reconciliation-valid-italian-semicolon.csv`; semicolon, Italian aliases/date and signed bank amounts are recognized.
- [ ] **H02 BLOCKER** `bug-hunting-test-reconciliation-zero-amount.csv` fails atomically.
- [ ] **H03 BLOCKER** `bug-hunting-test-reconciliation-wrong-currency.csv` fails atomically for EUR account.
- [ ] **H04 BLOCKER** `bug-hunting-test-reconciliation-duplicate-external-id.csv` fails as ambiguous with no partial batch.
- [ ] **H05 BLOCKER** `bug-hunting-test-reconciliation-ambiguous-headers.csv` rejects multiple candidate date columns.
- [ ] H06 Test comma/semicolon/tab delimiters, quoted commas/quotes, blank rows, missing optional columns.
- [ ] H07 Missing required date/amount header and invalid calendar date -> clear failure.
- [ ] **H08 BLOCKER** Heuristic candidate alone never auto-MATCHES.
- [ ] H09 Link compatible row, reject incompatible link, post a row and ignore a row.
- [ ] **H10 BLOCKER** Ledger posting and reconciliation terminal-state transition remain atomic.

## I. CSV reconciliation - row-limit/performance corpus

Download the GitHub Actions artifact `bug-hunting-test-csv-corpus` from workflow **Bug hunting test artifacts**, or run `python bug-hunting-test/generate_large_csv.py`.

- [ ] **I01 BLOCKER/PERF** Import `bug-hunting-test-reconciliation-10000-valid.csv` (exact row-count maximum).
- [ ] I02 Record elapsed time and CPU/RAM.
- [ ] **I03 BLOCKER/PERF** While importing, move/resize window and interact with desktop; record any UI freeze duration.
- [ ] I04 Batch reports exactly 10,000 rows; sample beginning/middle/end.
- [ ] **I05 BLOCKER** Restart preserves the imported batch.
- [ ] **I06 BLOCKER** Import `bug-hunting-test-reconciliation-10001-too-many.csv`; must be rejected by row limit with no partial batch.
- [ ] **I07 PRODUCT/PERF BLOCKER** If the 10k import freezes the GUI for a significant interval, report duration: this triggers moving CSV import off GUI thread before v1.

## J. Scheduled transactions

- [ ] **J01 BLOCKER** Daily/weekly/monthly/yearly recurrence creation.
- [ ] **J02 BLOCKER** Month-end recurrence across 28/29/30/31 and leap-year February.
- [ ] J03 End date, pause and resume behavior.
- [ ] **J04 BLOCKER** Materialize multiple overdue occurrences without duplicates.
- [ ] **J05 BLOCKER** Ledger write + occurrence record + schedule advancement are atomic.
- [ ] **J06 BLOCKER** Schedule pointing to newly archived/stale target fails closed in materialization/forecast.

## K. Budgets

- [ ] **K01 BLOCKER** Monthly expense budget and actual-spend derivation from ledger.
- [ ] K02 Refund changes actual correctly; overspend >100% displays correctly.
- [ ] **K03 BLOCKER** Parent budget includes descendants.
- [ ] **K04 BLOCKER** Ancestor/descendant overlap in same month is rejected.
- [ ] K05 Sibling budgets allowed.
- [ ] **K06 BLOCKER** Missing FX gives incomplete/fail-closed status.
- [ ] **K07 BLOCKER** Re-parent categories so existing budgets overlap; status must fail explicitly instead of double-counting.
- [ ] K08 Delete budget; ledger remains untouched.

## L. Forecast

- [ ] **L01 BLOCKER** Scheduled expense -> outflow; income/refund -> inflow; transfer -> neutral.
- [ ] L02 DAY/MONTH/YEAR grouping.
- [ ] **L03 BLOCKER** Forecast dates match scheduled recurrence semantics.
- [ ] **L04 BLOCKER** Forecast never advances schedules or writes ledger state.
- [ ] **L05 BLOCKER** Missing FX shows incomplete state.
- [ ] L06 Very old schedules fast-forward within bounds; stale schedules fail closed.

## M. Loans / financing

- [ ] **M01 BLOCKER** Fixed + French NEW_DISBURSEMENT and EXISTING-loan paths.
- [ ] **M02 BLOCKER** Liability ledger balance is canonical outstanding principal after restart.
- [ ] **M03 BLOCKER** Final French installment extinguishes residual principal exactly despite rounding.
- [ ] **M04 BLOCKER** Italian amortization: principal quota/payout profile follows policy.
- [ ] **M05 BLOCKER** Bullet: interim interest payments do not reduce principal; maturity clears principal exactly.
- [ ] **M06 BLOCKER** Variable-rate future revision changes subsequent installment.
- [ ] **M07 BLOCKER** Retroactive revision over an already-posted installment period is rejected.
- [ ] M08 Applied historical rate remains visible/preserved.
- [ ] **M09 BLOCKER** Custom payment below contractual installment is rejected in V1.
- [ ] **M10 BLOCKER** Overpayment is explicit prepayment; REDUCE_PAYMENT / REDUCE_TERM behavior matches backend policy.
- [ ] **M11 BLOCKER** UI never offers a backend-invalid policy combination.
- [ ] **M12 BLOCKER** Forecast treats principal repayment as balance-sheet neutral and interest as expense flow.

## N. Backup / restore

- [ ] **N01 BLOCKER** Create managed backup and export to chosen destination.
- [ ] N02 File permissions owner-only where supported; overlapping backup jobs serialized/rejected.
- [ ] **N03 BLOCKER** Closing while owned backup/restore job active is prevented until safe.
- [ ] **N04 BLOCKER** Create recognizable state A -> backup -> mutate to state B -> restore A -> verify exact state A after refresh/restart.
- [ ] **N05 BLOCKER** Safety/pre-restore backup exists.
- [ ] **N06 BLOCKER** Restore `bug-hunting-test-invalid-not-sqlite.sqlite3`; must reject before replacing live DB.
- [ ] N07 Try unrelated SQLite database; must reject as incompatible.
- [ ] **N08 BLOCKER** Maintenance mode rejects normal mutations during restore.
- [ ] **N09 BLOCKER** Failed restore leaves original live DB usable and unchanged.
- [ ] N10 Repeat backup/mutate/restore cycle five times; test read-only external path if available.

## O. WebEngine / security / hostile text

- [ ] **O01 BLOCKER** HTTP(S) navigation never renders inside Finance Tracker; intentional link opens system browser.
- [ ] **O02 BLOCKER** Remote scripts/images/subresources are blocked.
- [ ] **O03 BLOCKER** Enter `<img src=x onerror=alert(1)>`, quotes, ampersands and angle brackets in user text fields; content must render as text and never execute.
- [ ] **O04 BLOCKER** No arbitrary filesystem or command API exposed over QWebChannel.

## P. Filesystem / failure recovery

- [ ] P01 Temporarily unavailable/unwritable data path -> controlled failure/logging.
- [ ] P02 Corrupt settings -> safe fallback.
- [ ] **P03 BLOCKER** Corrupt disposable live DB -> controlled error, never silent overwrite.
- [ ] P04 Export to unwritable destination -> concise UI error + diagnostic log.
- [ ] **P05 BLOCKER** No partial financial state after simulated write failure where practical.
- [ ] P06 `.db`, `.sqlite`, `.sqlite3` and `bug-hunting-test/generated/` remain ignored by Git.

## Q. Long-session soak

- [ ] Q01 Keep app open at least 60 minutes while exercising all major views.
- [ ] Q02 Perform 100+ mixed operations and rapid view switching.
- [ ] Q03 Observe CPU at idle and RAM growth over the session.
- [ ] Q04 Suspend/resume system if safe.
- [ ] **Q05 BLOCKER** Normal close leaves no orphan Finance Tracker / QtWebEngine process.
- [ ] Q06 Reopen and verify DB/content integrity.

## R. Final pre-tag gate

- [ ] **R01 BLOCKER** Pull latest `main` and record commit SHA.
- [ ] **R02 BLOCKER** `./install.sh` passes.
- [ ] **R03 BLOCKER** `.venv/bin/python -m compileall -q main.py config core ui tests` passes.
- [ ] **R04 BLOCKER** `.venv/bin/python -m pytest` passes.
- [ ] **R05 BLOCKER** `.venv/bin/ruff check main.py config core ui tests` passes.
- [ ] **R06 BLOCKER** GitHub Actions for tested `main` is green.
- [ ] **R07 BLOCKER** Review `finance-tracker.log`; no unexplained exceptions/errors remain.
- [ ] **R08 BLOCKER** No test artifact contains real financial data.
- [ ] **R09 BLOCKER** No unresolved P0/P1/BLOCKER bug remains.
- [ ] R10 After every bug-fix batch, perform mandatory whole-project strategic review and rerun relevant automated/manual regressions.
- [ ] **R11** Only after all release gates pass: create `v1.0.0` tag/release.

## Bug report template

- Test ID:
- Severity: BLOCKER / HIGH / MEDIUM / LOW
- OS / KDE / Wayland-X11 / display scale / Python:
- Commit SHA:
- Preconditions:
- Exact steps:
- Expected:
- Actual:
- Reproducibility:
- Screenshot/video:
- Relevant log excerpt:
- Did restart change result?:
- Did database state change unexpectedly?:

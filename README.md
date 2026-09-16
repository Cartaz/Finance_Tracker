# Finance Tracker

Local-first personal finance tracker for desktop Linux. The complete V1 frontend currently uses Python, PySide6/Qt WebEngine, local HTML/CSS/vanilla JS and QWebChannel with a SQLite backend. Native Qt Quick/QML migration is in progress.

## Current status

V1 features through M11 are integrated on `main`. The repository's [GitHub Actions workflow](https://github.com/Cartaz/Finance_Tracker/actions/workflows/test.yml) is the authoritative result for the current commit; do not treat historical test counts or previous green runs as the status of a newer commit. The observed baseline failure on 2026-08-29 was corrected and the fix passed CI in [run 35150817684](https://github.com/Cartaz/Finance_Tracker/actions/runs/35150817684). **V1 has not passed the required real-machine release gate:** see [issue #11](https://github.com/Cartaz/Finance_Tracker/issues/11) and [V1_RELEASE_AUDIT.md](V1_RELEASE_AUDIT.md). Do not create `v1.0.0` until that gate passes.

A separate opt-in, **read-only technical QML preview** exercises the real controller and database; it is not a replacement for the complete Web UI. See [the QML audit and migration plan](AUDIT_QML_MIGRATION_2026-09-16.md) and [issue #12](https://github.com/Cartaz/Finance_Tracker/issues/12). No domain/database migration or user-data conversion is required for this preview.

## Implemented

### Desktop architecture

- Python 3.12+ with PySide6/Qt6, Qt WebEngine and QWebChannel for the complete frontend;
- opt-in `QQmlApplicationEngine` preview with a focused Python QObject adapter and local QML, without QWebChannel;
- local/buildless HTML, CSS and vanilla JavaScript production frontend;
- one main QWebChannel backend proxy shared by frontend modules;
- local-only in-app navigation, with external HTTP(S) navigation opened in the system browser;
- dark neumorphic UI using `rgb(20,20,20)` surfaces and `rgb(255,102,0)` accent;
- production Web window minimum size 1200×800; QML technical preview has its own smaller minimum;
- XDG-based data/config/cache paths;
- SQLite with foreign-key enforcement, WAL mode and migrations through schema v9.

### Accounting and money

- `LedgerService` is the only writer of accounting transactions and entries;
- opening balances, expenses, income, transfers, split transactions, refunds, adjustments, reversals and generic multi-currency postings;
- monetary persistence uses integer minor units; percentage, amortization and FX calculations use `Decimal` with deterministic rounding;
- user-entered financial amounts are unsigned positive magnitudes; economic direction belongs to transaction/posting semantics;
- financial `float` values are rejected;
- currency precision and financial transport fields are explicit, including safe transport beyond JavaScript's `2^53` integer limit;
- canonical tracking-boundary and posting-capability policies are reused across workflows.

### Accounts, payees and reporting

- accounts/categories with hierarchy, placeholder and archive semantics;
- merchant/payee autocomplete, aliases and atomic payee merge;
- historical book-scoped FX rates;
- FX-aware net worth, income, expenses, saving rate, cash flow, category/merchant reporting and account history;
- reporting fails closed when a required historical FX rate is missing.

### Reconciliation and scheduled transactions

- CSV import into external staging evidence, never directly into the ledger;
- full-review and assisted-review reconciliation workflows;
- persisted external identity matching, duplicate detection and ambiguity handling;
- explicit posting of reconciled rows through semantic `LedgerService` APIs;
- scheduled expense, income, refund and same-currency transfer templates;
- daily, weekly, monthly and yearly recurrence with month-end/leap-year anchoring;
- pause/resume, optional end dates, durable occurrence identity and atomic catch-up posting;
- forecast consumes the canonical read-only recurrence projection rather than reimplementing recurrence rules.

### Budgets and forecasting

- monthly expense budgets in the book base currency;
- category-subtree budget scopes with ancestor/descendant overlap prevention;
- backend-owned budget targets and FX-aware actuals;
- deterministic DAY/MONTH/YEAR cash-flow forecasting for known scheduled transactions and loan installments;
- forecast never persists a second future-state truth and never advances canonical schedule/loan state;
- transfers and loan-principal repayments are book-level flow neutral; loan interest is an expense flow;
- foreign-currency forecast uses the latest known FX rate on or before each due date and fails closed when conversion is unavailable.

### Loans and financing

- loans backed by canonical `LIABILITY` ledger balances; no parallel outstanding-balance state;
- existing-balance attachment or atomic new disbursement;
- fixed and effective-dated variable rates;
- French, Italian and bullet amortization through one deterministic `AmortizationPolicy`;
- contractual installment posting, custom overpayment/prepayment and supported recast strategies;
- posted installments preserve the actual rate and principal/interest split used;
- variable-rate history cannot rewrite already-posted periods;
- future plans use the latest known effective variable rate instead of predicting unknown future indices;
- arrears, penalties, unpaid-interest capitalization and negative amortization are intentionally not inferred implicitly;
- schema v8 fixed/French contracts migrate deterministically to v9.

### Backup / restore and release hardening — M11

- dedicated `BackupService` and `BackupController`; `AppController` remains focused on application/domain orchestration;
- managed local backups plus native Qt export and restore file selection;
- created backup files are verified SQLite snapshots and are restricted to owner-only permissions (`0600`) when supported;
- external restore sources are opened read-only;
- every restore verifies the source, creates a safety backup of the current state, copies to staging, migrates the staged database and performs full integrity/foreign-key checks before touching the live database;
- the live swap attempts rollback if reopening the prepared database fails; additional checkpoint/sidecar failure injection is a pending release gate;
- heavy backup/restore I/O, migration and integrity verification run through a Qt background worker;
- restore activates maintenance mode so application mutations cannot race the safety snapshot and final swap;
- backup/export/restore lifecycle operations are serialized;
- the native window blocks normal application close while owned background persistence I/O is active;
- restore completion reloads the Web frontend so all UI state is rebuilt from the newly canonical database.

## Strategic programming directive

`STRATEGIC_PROGRAMMING.md` is a binding project invariant. Green feature tests alone do not complete a milestone. After every milestone the whole project is reviewed for duplicated knowledge, information leakage, shallow modules, state ownership, atomicity, concurrency/lifecycle risks, UI/domain leakage and new invariants worth automating.

The review outcome must be `STRATEGIC`, `STRATEGIC AFTER CLEANUP`, or `BLOCKED`. Routine architectural debt discovered during the review is fixed inside the milestone rather than silently deferred.

## Requirements

- Linux desktop; CachyOS/Arch + KDE is first-class
- Python 3.12+
- Qt runtime dependencies required by PySide6/Qt WebEngine; QML preview also needs Qt Quick/Controls modules included with PySide6

## Install

```bash
chmod +x install.sh
./install.sh
```

No virtualenv activation is required.

## Run

Complete production frontend:

```bash
.venv/bin/python main.py
```

Read-only Qt Quick technical preview (shows real book name, currency and exact net worth in **minor units**, *not* formatted euro amounts; no transaction controls):

```bash
.venv/bin/python main.py --qml-preview
```

The preview deliberately does not duplicate canonical state or allow accounting mutations. Use the standard frontend for all ordinary work. Test on CachyOS/KDE before treating native integration as validated.

## Validate

```bash
.venv/bin/python -m compileall -q main.py config core ui tests
.venv/bin/python -m pytest
.venv/bin/ruff check main.py config core ui tests
```

The CI runs the QML smoke test offscreen with software rendering. After validation, perform the mandatory milestone review in `STRATEGIC_PROGRAMMING.md` before declaring a milestone complete.

## Data locations

By default:

```text
~/.local/share/finance-tracker/
├── finance.db
├── backups/
├── imports/
├── loan-documents/
└── logs/

~/.config/finance-tracker/settings.json
```

XDG environment variables are respected when set.

# Finance Tracker

Local-first personal finance tracker for desktop Linux, built with Python, PySide6/Qt Quick (QML) and SQLite.

## Current status

V1 workflows are implemented on `main` through M11. The desktop interface is native Qt Quick/QML; the former WebEngine/HTML frontend has been removed. Audit history lives in [`docs/audits/`](docs/audits/): the [26 November full audit](docs/audits/ANALISI_2026-11-26.md) lists the open findings and the cleanup plan, and the [30 September corrective audit](docs/audits/AUDIT_2026-09-30.md) documents the restore and transport repairs.

Release gates that require a physical CachyOS/KDE session (HiDPI rendering, keyboard focus, native dialogs, Wayland) are still verified manually with [`bug-hunting-test/BUG_HUNTING_TEST_PLAN.md`](bug-hunting-test/BUG_HUNTING_TEST_PLAN.md).

## Implemented

### Desktop architecture

- Python 3.12+ with PySide6/Qt6 and a native Qt Quick (QML) interface in `ui/qml/`;
- one backend object (`ui/bridge.py`) injected into the QML root; pages reach it through the root window;
- money crosses into QML only as exact integer text and is formatted by Python (`ui/formatting.py`);
- native file dialogs are owned by the Python shell (`ui/shell.py`); QML never receives filesystem paths;
- dark neumorphic Qt Quick design system shared with the author's other QML apps: a single `rgb(20,20,20)` surface, depth from paired shadows (`RaisedSurface`) and a compiled inset shader (`InsetSurface`, `ui/qml/shaders/`), `rgb(255,102,0)` accent used as a state cue;
- minimum window size 1200×800;
- XDG-based data/config/cache paths;
- SQLite with foreign-key enforcement, WAL mode and migrations through schema v9.

### Accounting and money

- `LedgerService` is the only writer of accounting transactions and entries; mistakes are corrected by guarded reversals from the transaction list;
- opening balances, expenses, income, transfers, split transactions, refunds, adjustments, reversals and generic multi-currency postings;
- monetary persistence uses integer minor units; percentage, amortization and FX calculations use `Decimal` with deterministic rounding;
- user-entered financial amounts are unsigned positive magnitudes; economic direction belongs to transaction/posting semantics;
- financial `float` values are rejected;
- currency precision and financial transport fields are explicit, including safe transport beyond JavaScript's `2^53` integer limit;
- canonical tracking-boundary and posting-capability policies are reused across workflows.

### Accounts, payees and reporting

- accounts/categories with hierarchy, placeholder, rename and guarded archive/restore from the UI;
- merchant/payee autocomplete, aliases and atomic payee merge;
- historical book-scoped FX rates;
- FX-aware net worth, income, expenses, saving rate, cash flow, category/merchant reporting and account history;
- reporting fails closed when a required historical FX rate is missing.

### Reconciliation and scheduled transactions

- background CSV import (file chosen with the native dialog, UTF-8 or Windows-1252) into external staging evidence, never directly into the ledger, with owned worker SQLite connections and bounded reconciliation pages;
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
- the final live swap is rollback-safe: failure to reopen the prepared database restores the previous live file;
- heavy backup/restore I/O, migration and integrity verification run through a Qt background worker;
- restore activates maintenance mode so application mutations cannot race the safety snapshot and final swap;
- backup/export/restore lifecycle operations are serialized;
- the native window blocks normal application close while owned background persistence I/O is active;
- restore completion resets the QML session so all UI state is rebuilt from the newly canonical database.

## Strategic programming directive

`STRATEGIC_PROGRAMMING.md` is a binding project invariant. Green feature tests alone do not complete a milestone. After every milestone the whole project is reviewed for duplicated knowledge, information leakage, shallow modules, state ownership, atomicity, concurrency/lifecycle risks, UI/domain leakage and new invariants worth automating.

The review outcome must be `STRATEGIC`, `STRATEGIC AFTER CLEANUP`, or `BLOCKED`. Routine architectural debt discovered during the review is fixed inside the milestone rather than silently deferred.

## Requirements

- Linux desktop; CachyOS/Arch + KDE is first-class
- Python 3.12+
- Qt runtime dependencies required by PySide6/Qt Quick

## Install

```bash
chmod +x install.sh
./install.sh
```

No virtualenv activation is required.

## Run

```bash
.venv/bin/python main.py
```

## Validate

```bash
.venv/bin/python -m compileall -q main.py config core ui tests
.venv/bin/python -m pytest
.venv/bin/ruff check main.py config core ui tests
.venv/bin/pyside6-qmllint --max-warnings 0 ui/qml/*.qml ui/qml/pages/*.qml
```

After validation, perform the mandatory milestone review in `STRATEGIC_PROGRAMMING.md` before declaring a milestone complete.

## Data locations

By default:

```text
~/.local/share/finance-tracker/
├── finance.db
├── backups/
└── logs/            # rotated: finance-tracker.log (+3 × 2 MB)

~/.config/finance-tracker/settings.json
```

XDG environment variables are respected when set.

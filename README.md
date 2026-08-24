# Finance Tracker

Local-first personal finance tracker for desktop Linux, built with Python, PySide6/Qt WebEngine, local HTML/CSS/vanilla JS, QWebChannel and SQLite.

## Current status

Milestones M0 through M7 are implemented on the current M7 branch and are under final validation before merge to `main`.

Implemented:

- PySide6/QWebEngine local desktop shell with QWebChannel bridge and blocked in-app remote navigation;
- dark neumorphic UI (`rgb(20,20,20)` surface, `rgb(255,102,0)` accent), minimum window 1200×800;
- first-run creation of the local personal book;
- usable Dashboard, Transactions, Accounts, Scheduled Transactions and Reconciliation views;
- manual account/category creation and manual expense entry;
- merchant autocomplete limited to five ranked suggestions plus explicit new-payee creation;
- XDG-based settings/data directories;
- SQLite with verified foreign-key enforcement, WAL mode and migrations through schema v6;
- currencies, users/books, accounts, transactions, entries, payees, aliases, historical book-scoped FX rates, CSV import staging rows, reconciliation identities, scheduled templates and posted occurrences;
- exact money parsing using integer minor units and `Decimal`; financial `float` values are rejected;
- `AccountService`, `LedgerService`, `BookService`, `PayeeService`, `CategoryService`, `FxService`, read-only `ReportingService`, zero-trust `ReconciliationService` and `ScheduledTransactionService`;
- opening balances, expenses, income, transfers, split transactions, refunds, adjustments, reversals and generic multi-currency postings in the domain layer;
- intraday tracking-boundary validation;
- deterministic autocomplete ranking and atomic payee merge;
- FX-aware reporting with fail-closed behavior when required rates are missing;
- net worth, income, expenses, saving rate, category and merchant reports, cash flow and account history;
- canonical currency precision supplied by the Python backend; monetary values and basis points cross QWebChannel without JavaScript-number precision loss;
- deterministic FX rounding for split transactions so report totals reconcile;
- CSV import for balance accounts with `FULL_REVIEW` and `ASSISTED_REVIEW` workflows;
- imported bank rows remain external staging evidence and never mutate the ledger until an explicit reconciliation action;
- heuristic reconciliation can produce suggestions or ambiguity but never automatic `MATCHED` status;
- automatic `MATCHED` status is limited to a previously persisted unique external bank identity that remains compatible with the ledger transaction;
- normalized bank-source identity, re-import duplicate detection with and without external IDs, fail-closed ambiguous CSV header handling and explicit tracking-boundary ambiguity;
- reconciliation candidates match native account quantities, including ledger transactions whose accounting transaction currency differs from the account currency;
- explicit reconciliation posting as expense, income, refund or same-currency transfer, always delegated to `LedgerService` atomically;
- scheduled expense, income, refund and same-currency transfer templates with daily, weekly, monthly and yearly recurrence;
- date-only scheduled templates remain separate from the ledger until an explicit due-materialization command;
- month-end and leap-year recurrence anchoring, optional end dates, pause/resume and durable unique `(schedule, due date)` occurrence identity;
- scheduled catch-up preflights occurrence limits and materializes an entire requested batch atomically through `LedgerService`, preventing partial posting if a later occurrence fails;
- verified SQLite backup primitive;
- permanent deterministic stress suites across M0-M7, including malformed input, cross-book references, rollback, integrity/foreign-key checks, missing FX, cross-currency operations, reconciliation duplicates/ambiguity, reporting read-only invariants and 1000 scheduled occurrences plus invalid-state stress.

Later V1 milestones cover budgets, forecasting, loans/financing and complete backup/restore UX.

## Requirements

- Linux desktop (CachyOS/Arch + KDE is first-class)
- Python 3.12+
- Qt runtime dependencies required by PySide6/Qt WebEngine

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
.venv/bin/pytest
.venv/bin/ruff check main.py config core ui tests
```

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

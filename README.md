# Finance Tracker

Local-first personal finance tracker for desktop Linux, built with Python, PySide6/Qt WebEngine, local HTML/CSS/vanilla JS, QWebChannel and SQLite.

## Current status

Milestones M0 through M5 are implemented and validated.

Implemented:

- PySide6/QWebEngine local desktop shell with QWebChannel bridge and blocked in-app remote navigation;
- dark neumorphic UI (`rgb(20,20,20)` surface, `rgb(255,102,0)` accent), minimum window 1200×800;
- first-run creation of the local personal book;
- usable Dashboard, Transactions and Accounts views;
- manual account/category creation and manual expense entry;
- merchant autocomplete limited to five ranked suggestions plus explicit new-payee creation;
- XDG-based settings/data directories;
- SQLite with verified foreign-key enforcement, WAL mode and migrations through schema v4;
- currencies, users/books, accounts, transactions, entries, payees, aliases and historical book-scoped FX rates;
- exact money parsing using integer minor units and `Decimal`; financial `float` values are rejected;
- `AccountService`, `LedgerService`, `BookService`, `PayeeService`, `CategoryService`, `FxService` and read-only `ReportingService`;
- opening balances, expenses, income, transfers, split transactions, refunds, adjustments, reversals and generic multi-currency postings in the domain layer;
- intraday tracking-boundary validation;
- deterministic autocomplete ranking and atomic payee merge;
- FX-aware reporting with fail-closed behavior when required rates are missing;
- net worth, income, expenses, saving rate, category and merchant reports, cash flow and account history;
- canonical currency precision supplied by the Python backend; monetary values and basis points cross QWebChannel without JavaScript-number precision loss;
- deterministic FX rounding for split transactions so report totals reconcile;
- verified SQLite backup primitive;
- permanent deterministic stress suites across M0-M5, including malformed input, cross-book references, rollback, integrity/foreign-key checks, missing FX, cross-currency operations and reporting read-only invariants.

The next planned V1 milestone is CSV import and reconciliation with zero-trust matching. Loans, scheduled transactions, budgets, forecasting and complete backup/restore UX belong to later V1 milestones.

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

# Finance Tracker

Local-first personal finance tracker for desktop Linux, built with Python, PySide6/Qt WebEngine, local HTML/CSS/vanilla JS, QWebChannel and SQLite.

## Current status

Milestones M0 through M4 are implemented on the current development branch.

Implemented:

- PySide6/QWebEngine local desktop shell with QWebChannel bridge and blocked in-app remote navigation;
- dark neumorphic UI (`rgb(20,20,20)` surface, `rgb(255,102,0)` accent), minimum window 1200×800;
- first-run creation of the local personal book;
- usable Dashboard, Transactions and Accounts views;
- manual account/category creation and manual expense entry;
- merchant autocomplete limited to five ranked suggestions plus explicit new-payee creation;
- XDG-based settings/data directories;
- SQLite with verified foreign-key enforcement, WAL mode and migrations through schema v3;
- currencies, users/books, accounts, transactions, entries, payees and aliases;
- exact money parsing using integer minor units and `Decimal`; financial `float` values are rejected;
- `AccountService`, `LedgerService`, `BookService`, `PayeeService` and `CategoryService`;
- opening balances, expenses, income, transfers, split transactions, refunds, adjustments, reversals and generic multi-currency postings in the domain layer;
- intraday tracking-boundary validation;
- deterministic autocomplete ranking and atomic payee merge;
- verified SQLite backup primitive;
- deterministic stress suites for ledger, M3 and the M4 application workflow, including invalid-state rollback checks.

The current M4 UI intentionally exposes only the first daily-use subset. Reporting, CSV reconciliation, loans, scheduled transactions, budgets and forecasting belong to later milestones.

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

# Finance Tracker

Local-first personal finance tracker for desktop Linux, built with Python, PySide6/Qt WebEngine, local HTML/CSS/vanilla JS, QWebChannel and SQLite.

## Current status

Milestones M0, M1 and M2 are implemented on the current development branch.

Implemented foundations:

- PySide6/QWebEngine local desktop shell with QWebChannel bridge;
- dark neumorphic base UI (`rgb(20,20,20)` surface, `rgb(255,102,0)` accent);
- XDG-based settings/data directories;
- SQLite with verified foreign-key enforcement and WAL mode;
- explicit schema migrations through schema v2;
- currencies, users/books, accounts, transactions and entries;
- cross-book foreign-key protection for ledger postings;
- exact money parsing using integer minor units and `Decimal`; financial `float` values are rejected;
- `AccountService` for account hierarchy/state/native balances;
- `LedgerService` as the single writer for balanced transaction/entry creation;
- opening balances, expenses, income, same-currency transfers, split transactions, reversals and generic multi-currency postings;
- intraday tracking-boundary validation with explicit ambiguity errors;
- verified SQLite backup primitive using the online backup API plus integrity/foreign-key checks;
- pytest coverage for money, settings, migrations, backup, accounts and ledger invariants.

Payees/autocomplete, reconciliation, reporting, loans, budgets and forecasting are intentionally not implemented yet; they belong to later milestones.

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

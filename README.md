# Finance Tracker

Local-first personal finance tracker for desktop Linux, built with Python, PySide6/Qt WebEngine, local HTML/CSS/vanilla JS, QWebChannel and SQLite.

## Current status

The repository is in the foundation milestone (M0 + M1). Implemented foundations:

- PySide6/QWebEngine local desktop shell with QWebChannel bridge;
- dark neumorphic base UI (`rgb(20,20,20)` surface, `rgb(255,102,0)` accent);
- XDG-based settings/data directories;
- SQLite connection with verified foreign-key enforcement and WAL mode;
- explicit schema migration table, schema v1 foundation tables (`currencies`, `users`, `books`, `book_members`);
- exact money parsing using integer minor units and `Decimal`; financial `float` values are rejected;
- verified SQLite backup primitive using the online backup API plus integrity/foreign-key checks;
- pytest coverage for money parsing, settings, schema initialization and backups.

The ledger, accounts, transactions, reconciliation, reporting, loans, budgets and forecasting are intentionally not implemented yet; they belong to later milestones.

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

For an offscreen Qt smoke run when the platform supports WebEngine offscreen execution:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python main.py
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

# Finance Tracker

Local-first personal finance tracker for desktop Linux, built with Python, PySide6/Qt WebEngine, local HTML/CSS/vanilla JS, QWebChannel and SQLite.

## Current status

Milestones M0 through M9 are implemented on stacked feature branches and are under validation before merge to `main`.

Implemented:

- PySide6/QWebEngine local desktop shell with QWebChannel bridge and blocked in-app remote navigation;
- dark neumorphic UI (`rgb(20,20,20)` surface, `rgb(255,102,0)` accent), minimum window 1200×800;
- first-run creation of the local personal book;
- usable Dashboard, Transactions, Accounts, Budgets, Forecast, Scheduled Transactions and Reconciliation views;
- manual account/category creation and manual expense entry;
- merchant autocomplete limited to five ranked suggestions plus explicit new-payee creation;
- XDG-based settings/data directories;
- SQLite with verified foreign-key enforcement, WAL mode and migrations through schema v7;
- currencies, users/books, accounts, transactions, entries, payees, aliases, historical book-scoped FX rates, CSV import staging rows, reconciliation identities, scheduled templates, posted occurrences and monthly budgets;
- exact money parsing using integer minor units and `Decimal`; financial `float` values are rejected;
- `AccountService`, `LedgerService`, `BookService`, `PayeeService`, `CategoryService`, `FxService`, read-only `ReportingService`, zero-trust `ReconciliationService`, `ScheduledTransactionService`, `BudgetService`, read-only `ForecastService` and a dedicated application-state read model;
- opening balances, expenses, income, transfers, split transactions, refunds, adjustments, reversals and generic multi-currency postings in the domain layer;
- one canonical tracking-boundary policy shared by ledger, reconciliation and scheduled workflows;
- one canonical posting-capability policy used by backend workflows and exposed to presentation instead of re-derived in JavaScript;
- deterministic autocomplete ranking and atomic payee merge;
- FX-aware reporting with fail-closed behavior when required rates are missing;
- net worth, income, expenses, saving rate, category and merchant reports, cash flow and account history;
- canonical currency precision supplied by a dedicated currency registry; monetary values and basis points cross QWebChannel without JavaScript-number precision loss;
- explicit financial transport vocabulary rather than suffix-based serialization heuristics;
- deterministic FX rounding for split transactions so report totals reconcile;
- CSV import for balance accounts with `FULL_REVIEW` and `ASSISTED_REVIEW` workflows;
- imported bank rows remain external staging evidence and never mutate the ledger until an explicit reconciliation action;
- heuristic reconciliation can produce suggestions or ambiguity but never automatic `MATCHED` status;
- automatic `MATCHED` status is limited to a previously persisted unique external bank identity that remains compatible with the ledger transaction;
- normalized bank-source identity, re-import duplicate detection with and without external IDs, fail-closed ambiguous CSV header handling and explicit tracking-boundary ambiguity;
- reconciliation candidates match native account quantities, including ledger transactions whose accounting transaction currency differs from the account currency;
- explicit reconciliation posting as expense, income, refund or same-currency transfer, always delegated to semantic `LedgerService` APIs atomically;
- scheduled expense, income, refund and same-currency transfer templates with daily, weekly, monthly and yearly recurrence;
- date-only scheduled templates remain separate from the ledger until an explicit due-materialization command;
- month-end and leap-year recurrence anchoring, optional end dates, pause/resume and durable unique `(schedule, due date)` occurrence identity;
- scheduled catch-up preflights occurrence limits and materializes an entire requested batch atomically through `LedgerService`, preventing partial posting if a later occurrence fails;
- monthly expense budgets stored in book-base-currency minor units and compared against canonical FX-aware reporting rather than maintaining a second accounting total;
- budget scopes can target an expense category subtree, including grouping categories, while same-month ancestor/descendant overlaps are rejected and revalidated after hierarchy changes;
- budget target capabilities are computed by the backend for the selected month; presentation only renders the allowed category paths;
- budget actuals, remaining amounts and usage percentages fail closed when historical FX required by the ledger is missing;
- deterministic scheduled cash-flow forecasting with DAY/MONTH/YEAR grouping and horizons up to ten years;
- forecasting consumes the canonical scheduled recurrence projection and never advances schedules or writes ledger state;
- projected EXPENSE is an outflow, INCOME/REFUND an inflow and TRANSFER is book-level cash-flow neutral;
- foreign-currency forecast values use the canonical latest-known FX rate on or before each due date, with the policy surfaced explicitly in the forecast payload;
- forecast totals fail closed if a required FX conversion is unavailable; no partial total is presented as complete;
- no statistical trend inference, hidden assumptions or forecast persistence are introduced in M9: the projection is intentionally scheduled-only and deterministic;
- database migrations isolated from connection, transaction, integrity and backup lifecycle code;
- verified SQLite backup primitive;
- permanent deterministic stress suites across M0-M9, including malformed input, cross-book references, rollback, integrity/foreign-key checks, missing FX, cross-currency operations, reconciliation duplicates/ambiguity, reporting read-only invariants, 1000 scheduled occurrences, invalid-state stress, many-budget deterministic/read-only checks and forecast recurrence/read-only checks;
- permanent architecture-invariant tests preventing common tactical regressions.

Later V1 milestones cover loans/financing and complete backup/restore UX.

## Strategic programming directive

`STRATEGIC_PROGRAMMING.md` is a binding project invariant. A milestone is not complete merely because its feature tests are green: after every milestone the whole project must undergo the documented strategic review for duplicated knowledge, information leakage, shallow modules, misplaced state ownership, atomicity, UI/domain leakage and new architectural invariants worth automating.

The milestone review must end as `STRATEGIC`, `STRATEGIC AFTER CLEANUP`, or `BLOCKED`. Routine design debt discovered during the review is fixed inside the milestone rather than silently deferred.

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
.venv/bin/python -m pytest
.venv/bin/ruff check main.py config core ui tests
```

After validation, perform the mandatory milestone review in `STRATEGIC_PROGRAMMING.md` before declaring a milestone complete.

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

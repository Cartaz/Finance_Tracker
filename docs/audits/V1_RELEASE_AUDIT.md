# Finance Tracker V1 Release-Candidate Audit

This audit is the release-candidate review after milestones M0–M11 were integrated on `main`.
It complements, rather than replaces, the mandatory milestone reviews in `STRATEGIC_PROGRAMMING.md`.

## Outcome

**Automated/code-level outcome: STRATEGIC AFTER CLEANUP.**

The RC review found a small number of release-hardening gaps and corrected them in the RC branch:

- CI now proves `install.sh` is independent of the caller's working directory;
- Python 3.12 and 3.14 receive explicit install/compile/import compatibility coverage;
- unexpected QWebChannel failures are logged with full diagnostics but sanitized at the UI boundary;
- embedded WebEngine remote subrequests are blocked explicitly, while HTTP(S) main-frame navigation is rejected from the embedded view and delegated to the system browser;
- backup/restore owns a dedicated single-worker Qt thread pool instead of borrowing the global executor;
- permanent tests protect those invariants.

No `v1.0.0` tag should be created until the manual real-machine gate at the end of this document has passed.

## Binding architecture and ownership

**PASS.**

- Python owns canonical state, business logic, persistence and native integration.
- `LedgerService` remains the only accounting transaction/entry writer.
- `core/` is Qt-independent; Qt lifecycle and WebEngine integration live under `ui/` and `main.py`.
- `main.py` is the composition/lifecycle root rather than a domain module.
- `AppController` contains no SQL and coordinates focused domain services.
- `ui/bridge.py` exposes the single `backend` object, validates/normalizes transport shape and delegates; it does not implement accounting, SQLite, filesystem-copy or background-task algorithms.
- JavaScript owns presentation/temporary UI state. Persistent and operational state returns from Python.
- Database connection/lifecycle is separated from migration definitions/catalogs.

Permanent architecture tests cover the most important boundaries.

## Strategic-programming compliance

**PASS AFTER CLEANUP.**

`STRATEGIC_PROGRAMMING.md` and `AGENTS.md` make the strategic review part of the definition of done. M7–M11 each recorded a strategic review and resolved routine architectural debt inside the milestone.

The RC pass continued the same rule: the request interceptor, bridge error boundary and backup executor were designed around ownership/information hiding rather than patched at presentation level. No framework, event bus, repository layer, DI container or speculative abstraction was added.

## Money and accounting correctness

**PASS at automated level.**

- persisted monetary values use integer minor units;
- financial ratios, FX and amortization use `Decimal` with deterministic rounding;
- financial `float` is prohibited;
- user-entered transaction/budget/loan monetary values are strictly positive unsigned magnitudes; posting kind owns economic direction;
- signed money parsing is reserved for external evidence such as bank imports;
- QWebChannel financial integers use explicit string transport and are tested beyond JavaScript `2^53`;
- tracking-boundary, posting, recurrence, amortization and FX assumptions have canonical owners and fail closed in ambiguity/missing-data cases.

Stress, rounding, cross-currency and architecture suites exercise these rules.

## Frontend, QWebChannel and embedded-Web security

**PASS AFTER CLEANUP.**

- one QWebChannel backend proxy is shared by frontend modules;
- feature JavaScript does not create a second channel;
- direct `fetch`, `XMLHttpRequest`, WebSocket, EventSource, `eval` and dynamic `Function` use are forbidden by RC tests;
- remote HTTP(S) navigation never remains in the embedded view;
- HTTP/HTTPS/FTP/WS/WSS embedded subrequests are blocked by a native request interceptor;
- `data:` and `javascript:` navigation are rejected;
- external file selection is owned by native Qt dialogs; JavaScript receives no arbitrary filesystem or command-execution API;
- dynamic user-facing strings inserted through HTML templates are escaped by the frontend helpers in the existing rendering paths.

The external-browser path must still be exercised manually on the target desktop because system-browser integration is platform/session dependent.

## Settings and filesystem ownership

**PASS.**

- settings are loaded/saved through one Python abstraction;
- missing, malformed and incompatible settings fall back to validated defaults instead of crashing startup;
- XDG data/config/cache locations are used;
- application data directories are restricted to the owner when supported;
- managed/exported backup files are restricted to `0600` when supported;
- paths use `pathlib.Path` in Python.

## Backup, restore, concurrency and shutdown

**PASS AFTER CLEANUP.**

- backup/restore semantics have one canonical `BackupService` owner;
- external restore sources are opened read-only;
- restore creates a safety backup before replacement;
- source verification, staging migration and integrity/foreign-key checks happen before the live swap;
- final swap is rollback-safe;
- heavy backup/restore work executes outside the GUI thread;
- backup/export/restore operations are serialized;
- restore maintenance state blocks normal mutations during the safety-snapshot-to-swap window;
- the window blocks close while its owned persistence task is active;
- the RC uses a dedicated single-worker `QThreadPool` owned by `BackupTaskManager`, not Qt's global executor.

Destructive restore and shutdown behavior remain mandatory real-machine tests before release.

## Error handling and logging

**PASS AFTER CLEANUP.**

- Python logging is configured centrally and startup failures are logged;
- domain errors cross the bridge as concise typed errors;
- unexpected worker errors are logged and sanitized;
- the RC applies the same log-and-sanitize rule to unexpected ordinary QWebChannel calls, avoiding raw internal exception leakage to the frontend.

No production path intentionally swallows exceptions that affect correctness.

## Installation and dependency policy

**PASS after RC CI hardening, subject to the current RC workflow result.**

- canonical install remains `chmod +x install.sh` then `./install.sh`;
- launch remains `.venv/bin/python main.py`;
- installer resolves repository root, repairs `.venv`, installs requirement files and verifies Python/SQLite/PySide6/WebEngine;
- runtime dependency surface remains PySide6 plus the standard library;
- no Node/Electron/Tauri/frontend framework was introduced;
- RC CI invokes the installer from `/tmp`, proving it does not depend on caller CWD;
- full regression runs on Python 3.12, while 3.12 and 3.14 receive explicit installation/compile/import compatibility jobs.

## Tests and CI

**PASS on integrated V1 baseline; RC matrix must be green before merge.**

The integrated V1 baseline on `main` passed 236 tests, compile and Ruff. Coverage includes domain services, bridge/controller, settings, migrations, backup/restore, architecture invariants and multiple stress suites.

The RC adds tests for:

- external-CWD installation and Python compatibility matrix configuration;
- sanitized unexpected bridge failures;
- local-only WebEngine navigation/network policy;
- dedicated backup-worker ownership.

The RC is not merge-ready until all of its workflow jobs are green.

## UI and accessibility code-level audit

**PASS at code/static level; manual visual gate required.**

- surface/accent variables match the project dark-neumorphism palette;
- raised/inset depth and selected/focus accent treatments are present;
- controls are semantic HTML elements with labels;
- `:focus-visible` is explicit;
- layouts include responsive breakpoints;
- native minimum window size is 1200×800.

Offscreen CI cannot prove KDE font rendering, focus traversal quality, clipping, dialogs, HiDPI behavior or visual contrast under the user's real compositor. These remain manual release gates.

## Performance and GUI-thread audit

**PASS for measured/bounded paths, with one explicit manual RC gate.**

Backup/restore heavy work is asynchronous. Forecasting is bounded and previously stress-measured at thousands of occurrences without evidence justifying additional threading.

CSV reconciliation import is intentionally bounded to 10 MB / 10,000 rows but is currently synchronous through the ordinary bridge. The automated M6 stress suite exercises a 1,000-row reconciliation workflow successfully, but offscreen domain timing does not prove GUI responsiveness at the 10,000-row product limit.

**Release gate:** test realistic 1,000-row and near-limit CSV imports on the target machine while interacting with the window. If the UI freezes materially, background import ownership becomes a V1 blocker and must be implemented before tagging; do not merely increase timeouts or hide the symptom.

## Product-surface audit

**Known V1 scope limitation, not silently represented as broader UI functionality.**

The accounting core supports opening balances, income, transfers, refunds, adjustments and reversals. The current direct manual transaction form in the frontend is centered on expense entry; other flows are available through domain APIs and/or reconciliation, scheduled transactions and loan workflows rather than equivalent first-class manual forms.

Before tagging, the real-machine workflow test must determine whether this prevents a sane first-use/bootstrap flow (especially establishing existing balances and entering ordinary income). If it does, treat it as a product blocker rather than a cosmetic follow-up.

## Platform and release policy

**PASS at automated Linux level; target-desktop gate required.**

CI validates Linux/Qt offscreen. The first-class target remains CachyOS/Arch + KDE, which cannot be reproduced by the hosted Ubuntu runner. No subprocess or external runtime lifecycle exists in V1.

Do not create the V1 tag/release until the CachyOS/KDE manual checklist passes and any blocker discovered there has been corrected and revalidated.

## Manual release gate

The manual checklist should cover at minimum:

1. fresh install and first launch from a non-repository working directory;
2. full keyboard/focus/resize/HiDPI visual pass at and above 1200×800;
3. realistic account/bootstrap workflow, including whether existing balances and ordinary non-expense flows are practically representable;
4. money-sign rejection and currency-precision cases in the actual UI;
5. reconciliation imports at normal and near-limit sizes while checking GUI responsiveness;
6. scheduled recurrence/catch-up and forecast consistency;
7. fixed/variable French/Italian/bullet loan workflows, prepayment/recast and forecast consistency;
8. managed backup, export, restore, corrupted/wrong/newer-schema rejection and restore rollback behavior;
9. attempt to close during backup and restore;
10. system-browser handling of external HTTP(S) navigation and confirmation that remote content never renders inside Finance Tracker;
11. restart/reboot persistence and XDG file/permission inspection;
12. logs after both successful and intentionally failed operations, checking that the UI remains concise while diagnostics are useful.

Only after this gate passes should `v1.0.0` be tagged/released.

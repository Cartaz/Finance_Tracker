# Finance Tracker: audit V1 and Qt Quick/QML migration plan

Date: 2026-09-16. Audited baseline: `main` at `1d6e5608c882da7e276f172c2d0e945e45137379` (2026-08-29). This is a repository/source audit plus a review of existing GitHub Actions results; **it is not an independently executed local test run, end-to-end security assessment, or a physical CachyOS/KDE test**. Findings below distinguish observed failures, code-derived risks, and unverified release gates. The historical `V1_RELEASE_AUDIT.md` remains useful but does not override newer code and CI evidence.

## Executive findings and disposition

- **P0 / observed: baseline CI is red.** Workflow run [33256762243](https://github.com/Cartaz/Finance_Tracker/actions/runs/33256762243) on the audited SHA completed with 266/267 tests passing. `tests/test_bounded_scroll_regions.py::test_budget_and_loan_outputs_are_flat_lists_not_nested_neumorphic_cards` asserts an obsolete two-selector CSS string. Actual `ui/web/scroll-regions.css` also includes `#scheduled-list>.card` in the shared flat styling. The test's expected selector is updated on this audit branch, preserving the intended visual specification. **Re-run the full CI to validate the change; do not claim success before observing it.** Python 3.12/3.14 installation/import compatibility jobs passed on the baseline; Ruff was skipped because pytest failed.
- **P1 / code-derived responsiveness risk: CSV imports run synchronously on the Qt UI thread.** `ui/bridge.py::importCsv` calls `AppController.import_csv` directly, which invokes `ReconciliationService.import_csv` including CSV parsing, row preparation and SQLite writes. Limits of 10,000 rows / 10 MB and a 1,000-row domain stress test do not prove GUI responsiveness near the maximum. Measure on the target desktop before release. If responsiveness is impaired, move expensive preparation off the GUI thread with clearly owned SQLite connection/commit semantics and UI progress/cancellation where feasible; never share the existing sqlite3 connection unsafely across threads.
- **P1 / release verification: physical target tests remain outstanding.** The historical audit explicitly requires first-run flows, accessible keyboard/focus/HiDPI rendering, large CSV, loan/forecast consistency, corruption and failure-path restore tests, closing during persistence work, browser handling, persistence and log inspection on CachyOS/Arch + KDE. These are not proven by Ubuntu offscreen CI. No `v1.0.0` tag or release until they pass.
- **P2 / navigation policy hardening opportunity:** `ui/window.py::LocalOnlyPage` allows `file`, `qrc` and `about` navigation by scheme alone rather than constraining navigable local files to the UI root; a request interceptor separately blocks HTTP(S), FTP and WebSocket embedded subrequests, and sends HTTP(S) navigation to the system browser. This is not evidence of a working exploit. Constrain the local URL allowlist if WebEngine is retained, or retire this attack surface during the verified QML cutover.
- **P2 / documentation and test fidelity:** README's fixed 236-test integrated-pass claim predates the 267-test failing run; update status to refer to observed CI rather than a permanent passing claim. The brittle CSS substring regression illustrates that static tests should assert behavior/contract rather than incidental selector concatenation whenever practical. Retain visually meaningful assertions and offscreen smoke coverage.
- **Needs validation / restoration failure paths:** `BackupService` verifies a read-only source, creates a safety snapshot, prepares/migrates a staged DB, integrity-checks it and attempts rollback after failure during live swap. `finalize_restore` performs checkpoint, close and sidecar deletion before the swap `try` block. Add failure-injection tests for checkpoint and sidecar errors as well as swap/reopen errors, then verify whether the existing lifecycle handles each correctly. Do not assume an actual data-loss bug without reproducing one.
- **Historical product finding superseded:** UI now includes expense, income and same-currency transfer forms (`ui/web/index.html`, `ui/web/manual-transactions.js`) and an opening-balance account workflow. Their mere presence is verified; first-use usability and financial correctness still require real-machine tests.

## Architecture / strategic programming review

Preserve the documented invariants in `STRATEGIC_PROGRAMMING.md`: Python-owned canonical operational state, Qt-independent `core/`, `LedgerService` as sole transactions/entries writer, integer minor units and `Decimal` domain arithmetic, explicit tracking/posting/recurrence/FX/loan policies, read-only forecast, one SQLite schema owner, validated settings, native filesystem permissions, verified rollback-safe restore, bounded background workers and deterministic shutdown. `tests/test_architecture_invariants.py` provides source-level checks for major boundaries; 266 baseline tests passing provide regression evidence but not comprehensive correctness proof.

`main.py` is principally the composition/lifecycle root; `AppController` coordinates services without SQL; `ui/bridge.py` is an adapter with sanitized unexpected errors, though it also currently offers synchronous long-running imports. `ui/backup_task_manager.py` uses an owned, single-worker thread pool and explicit maintenance signals. `config/settings.py` validates/falls back on damaged settings; `core/database.py` enables SQLite FK and WAL and integrity checks. No new repository, DI container, event bus or parallel financial state is justified by a QML migration.

Complexity concentration: `ui/web/app.js` is approximately 45 KB and `ui/web/index.html` approximately 23 KB; these are migration surface, **not evidence that financial business rules have moved to JS**. A QML rewrite must not duplicate corresponding screen state in both UIs for an extended period. The current explicit money serializer (`core/transport.py`) maps financial integer fields to strings to avoid JavaScript IEEE-754 precision loss. QML expressions also use JavaScript numbers: financial quantities must remain validated text/formatted text across the QML boundary, with all arithmetic/parsing in Python. IDs crossing QML should also have a documented stable type and avoid unsafe numeric conversion.

Current milestone review outcome: **BLOCKED for V1 release and QML cutover**, owing to unverified CI after the test fix, manual release gates, and incomplete QML parity. This is not a claim that the core accounting engine is broken. Reassess and document the strategic outcome at each migration milestone.

## QML decision and architectural comparison

**Choose native Qt Quick/QML with PySide6**, replacing only the presentation and native-shell integration that currently depend on WebEngine/WebChannel. Keep `core/`, SQLite schema v9, settings and backup services intact. A simultaneous full rewrite of the finance domain would amplify risk without helping presentation migration.

- Alternative A, direct monolithic `QObject` with many `@Slot` methods and giant `Main.qml`: fastest spike, but repeats the current concentration, mixes screen state and lifecycle, and makes parity testing difficult. Use only a tiny throwaway feasibility spike if necessary.
- Alternative B, a focused Python QML-facing adapter plus a small reusable component vocabulary, separate QML pages and `QAbstractListModel` for genuinely large tabular lists: a slightly larger initial interface design, but Python remains state owner, responsibilities are explicit and data updates are signal-driven. **Selected.** Avoid one-model-per-trivial-widget proliferation.
- Alternative C, keep a permanent embedded-WebEngine/QML hybrid: doubles UI paths, security/runtime dependencies and testing. Reject as end state. If a temporary preview is needed, isolate it on the migration branch and remove it at cutover rather than persisting two canonical frontends.

Target topology:

```text
main.py (composition, logging, QApplication, lifecycle)
   ├── core/ unchanged (services, policies, Database + SQLite v9)
   ├── ui/backup_task_manager.py / focused background operation ownership
   ├── ui/quick_shell.py (QQmlApplicationEngine, app/window close + native dialogs)
   └── ui/qml_adapter.py (one exposed QObject entry point: validated input,
                          controller/service delegation, snapshots/models,
                          typed results, Qt signals, error sanitization)
          └── ui/qml/ (Main.qml, pages/, components/, theme tokens)
```

Use `QQmlApplicationEngine`, load a local QML resource, and expose the root's required backend property via documented initial-property or equivalent explicit object wiring; verify exact binding behavior against the pinned PySide6 version during the spike. Avoid a large bag of invisible QML context properties. Python emits change/maintenance/task-finished signals rather than QML polling; the QML adapter must not own financial algorithms or a second persisted state. Only introduce `QAbstractListModel` for sizeable lists (e.g. reconciliation/history) when `ListView` virtualization and precise update signals justify it; keep formatting and integer precision in Python. UI uses local-only resources and opens external URLs through `QDesktopServices` under explicit allowlisted schemes. Use native dialogs owned by the shell. Configure Qt Quick Controls style before loading the engine; implement the existing dark neumorphic theme (`20,20,20` surface, `255,102,0` accent) with reusable theme tokens, raised/inset depth, focus indicators, sufficient contrast, pointer/keyboard usability, and responsive desktop geometry.

Backup/restore parity is critical: preserve exclusive maintenance, single-worker ownership and close blocking; emit a definitive restore-completed event to invalidate/rebuild all QML models and screen state from the newly canonical database, replacing `window.location.reload()`. Do not hold stale Python model rows after restore. Keep an explicit active-task lifetime through shutdown. For CSV, design the worker/database boundary before implementing threading: workers may parse immutable inputs independently; the existing GUI-thread SQLite connection must not simply be handed to another thread. Commit/mutation coordination must respect restore maintenance and atomic staging.

## Staged implementation and gates

### Q0 — Freeze, verify and protect baseline

Fix stale CSS test (this branch), confirm full CI and Ruff, record current manual workflow/screenshots and fixture DB copies (do not commit personal finance data). Test restore failure injection, baseline CSV responsiveness using the existing `bug-hunting-test/` corpus, and verify real-machine release gates. Update inaccurate documentation. Gate: no known unexplained red CI, reproducible baseline and explicit manual blockers/issues.

### Q1 — QML feasibility spike and contracts

On a migration branch, build the smallest local `QQmlApplicationEngine` shell with a single required Python QObject root property, one read-only dashboard datum, clean startup/error reporting and deterministic close. Verify actual Qt Quick/QML imports through `install.sh`, offscreen CI and CachyOS/KDE Wayland. Define typed adapter method names, result/error envelope, money/ID text representation and notification semantics in contract tests. Do not touch accounting, schema or Web UI baseline.

### Q2 — Shared QML design system and read views

Add theme tokens/components and navigation with visible focus and accessibility; port dashboard and account/history read views. Preserve report dates, FX missing-rate warnings, formatted balances and empty/error/loading states. Compare QML and baseline service outputs using identical seeded fixtures; QML must not rederive ratios, posting capabilities or FX rules. Gate: read-view parity and no GUI stalls on representative data.

### Q3 — Core entry and setup parity

Port book setup, opening-balance accounts/categories, expense, income and transfer workflows. Domain validation remains in Python; render backend posting capabilities. Verify signed input rejection, 0/2/3-decimal currency cases, huge money values, balances and restart persistence. Gate: all major first-use and daily-bookkeeping workflows work through QML with keyboard support.

### Q4 — Advanced feature parity

Port budgets, FX, forecasts, scheduled transactions, loan plans/rates/payments, reconciliation (including 10,000-row list virtualization and responsive import), payees and tools. Integrate backup/export/restore last within this stage because it requires universal model invalidation and lifecycle parity. Gate: existing domain tests, new QML adapter/model/widget tests and manual workflow parity for each screen.

### Q5 — Single-frontend cutover and cleanup

Switch canonical `main.py` launch to Qt Quick, remove unused `QWebEngineView`, `QWebChannel`, HTML/JS/CSS, obsolete bridge/web-specific tests and dependencies only after all functions have QML equivalents. Update `AGENTS.md`, `STRATEGIC_PROGRAMMING.md` (document the explicit requested migration), README, `install.sh` critical Qt Quick/QML import checks and the CI smoke test. Preserve stable XDG data locations and schema v9: migration is UI-only, not a silent database migration. Review and remove dead code/duplicate paths.

### Q6 — Final validation and release gate

Run from the actual branch and record: `./install.sh` from outside repo; `.venv/bin/python -m compileall -q main.py config core ui tests`; `.venv/bin/python -m pytest`; `.venv/bin/ruff check main.py config core ui tests`; QML engine component-load/offscreen smoke; target CachyOS/KDE Wayland native tests, 1200x800 and HiDPI layout, tab/focus/contrast, 1,000/near-10,000-row imports with live interaction, accounting/forecast/loan flows, corrupted/new-schema restore refusal, rollback failure injection, close-during-work, fresh reboot persistence and logs. Record a complete milestone strategic review. No tag/release unless every mandatory gate passes.

## Decisions, rollback and exclusions

Keep feature changes and schema revisions out of the port unless an independently demonstrated baseline defect demands them. Branch/PR per coherent milestone; require green CI and strategic review before integrating. Until cutover, the established Web UI remains canonical; do not tell users that QML is shipped from documentation alone. A failed QML milestone rolls back by reverting its PR/branch rather than modifying user data, and test copies of data are created before destructive manual restore scenarios. Avoid ad hoc JavaScript math, an all-purpose command slot, cross-thread SQLite access, a speculative service framework or `main.py` domain logic. 

Sources: [`README.md`](README.md), [`V1_RELEASE_AUDIT.md`](V1_RELEASE_AUDIT.md), [`STRATEGIC_PROGRAMMING.md`](STRATEGIC_PROGRAMMING.md), [`main.py`](main.py), [`core/database.py`](core/database.py), [`core/backup_service.py`](core/backup_service.py), [`core/transport.py`](core/transport.py), [`core/reconciliation_service.py`](core/reconciliation_service.py), [`core/app_controller.py`](core/app_controller.py), [`ui/window.py`](ui/window.py), [`ui/bridge.py`](ui/bridge.py), [`ui/backup_task_manager.py`](ui/backup_task_manager.py), [`ui/web/index.html`](ui/web/index.html), [`ui/web/manual-transactions.js`](ui/web/manual-transactions.js), [`ui/web/scroll-regions.css`](ui/web/scroll-regions.css), [`tests/test_bounded_scroll_regions.py`](tests/test_bounded_scroll_regions.py), [baseline GitHub Actions run](https://github.com/Cartaz/Finance_Tracker/actions/runs/33256762243), [Qt for Python QQmlApplicationEngine](https://doc.qt.io/qtforpython-6/PySide6/QtQml/QQmlApplicationEngine.html), [Qt for Python QAbstractListModel](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QAbstractListModel.html), [Qt Quick Controls styling](https://doc.qt.io/qtforpython-6/PySide6/QtQuickControls2/QQuickStyle.html).

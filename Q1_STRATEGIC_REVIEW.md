# Q1 strategic review — native Qt Quick feasibility

Date: 2026-09-16. Parent audit: `AUDIT_QML_MIGRATION_2026-09-16.md`. PR: #14, issue: #12. This review covers the opt-in prototype, **not** Q2–Q6, the V1 manual release gate, or feature parity.

## Design and behavior

- The ordinary `main.py` entry point still launches the existing WebEngine UI. `--qml-preview` selects an alternate read-only window **after the same database, services and AppController are wired**; there is no duplicate domain composition or parallel persisted state.
- `ui/quick_shell.py` owns one `QQmlApplicationEngine`, loads only the local `ui/qml/Preview.qml` and provides a required QObject root property via `setInitialProperties`. No QWebChannel instance or WebEngine view is constructed on this path. QML load failures raise and are logged by `main.py`.
- `ui/quick_adapter.py` delegates to the real controller and keeps only derived display strings. It does not own a second account balance, write data or calculate financial values. It preserves exact minor-unit values as text instead of turning them into lossy QML JavaScript numbers.
- The preview explicitly labels the displayed figure as **raw minor units**, not formatted EUR. A missing FX result is displayed as unavailable. Unconfigured first-use and initial refresh errors are also explicit.
- Its QML window blocks close while the backup task manager reports active work and refreshes its display after task completion, so it does not retain a stale restored snapshot. Only the final complete UI port may remove WebEngine and its established restore lifecycle.
- `Theme.qml` centralizes the initial surface/accent/text tokens. Advanced raised/inset depth, semantic navigation, fully responsive production geometry and dense-list model performance belong to Q2–Q4, not this small feasibility spike.

## Invariant audit

1. Canonical ownership: Python core and SQLite schema v9 unchanged; view holds presentation cache only.
2. Duplicate knowledge: no financial math, FX, recurrence, ledger writes or backup rules added to QML.
3. Information hiding: QML sees `bookName`, `currency`, `netWorthMinor`, `errorMessage`, `busy` and two slots; it does not receive a generic command dispatcher or arbitrary database access.
4. Module depth: one focused read adapter and one launch module remove the current feasibility/lifetime concern. Do not proliferate adapters without real screen needs.
5. Boundary: Python handles all dashboard queries and exception sanitization, QML only renders the strings and triggers refresh.
6. Nearby cases: first-run, missing FX and large minor-unit values are covered by dedicated tests; full presentation formatting is deferred intentionally.
7. Errors: known domain/input exceptions are displayed; unexpected failures are logged and sanitized; startup errors survive signals emitted before QML loads.
8. Atomicity: preview is read-only and introduces no DB transaction, migration or persistence changes.
9. Lifecycle: engine owns adapter, GUI application is retained for its lifetime; current backup task manager remains canonical. Real KDE close/focus checks are still required.
10. Tests: Python adapter tests, exact precision and failure recovery plus a real QQmlApplicationEngine load/offscreen check, installer Qt import checks and `pyside6-qmllint` added to CI.
11. Complexity: temporary parallel presentation paths are explicitly opt-in, not a product end state; Q5 removes the Web path after parity. Existing app service construction is reused.
12. Cleanup: README's outdated fixed green-test claim corrected; no need to rewrite domain modules for a UI spike.

## Verification and decision

Before marking Q1 `STRATEGIC` or merging, capture a full green CI run for the latest head SHA: install from an external CWD, compile, `pyside6-qmllint`, all pytest tests including actual QML load, Ruff and Python compatibility. Offscreen CI does **not** prove CachyOS/KDE Wayland rendering, focus, compositor, native close behavior or memory PSS. Record those as an explicit manual gate under issue #12. Do not claim QML feature parity or tag V1.

Q1 outcome until final latest-head CI verification: **BLOCKED (verification pending)**. Release and full QML cutover remain **BLOCKED** regardless of Q1's eventual automated result.

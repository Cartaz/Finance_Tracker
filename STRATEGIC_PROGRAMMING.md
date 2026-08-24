# Strategic Programming Directive

Finance Tracker is developed under a strategic-programming rule inspired by John Ousterhout's *A Philosophy of Software Design*.

This directive is a project invariant, not optional guidance.

## Permanent rule

Every feature must optimize for the long-term cost of changing Finance Tracker, not merely for making the current task work.

A feature is incomplete if it works but leaves avoidable duplicated knowledge, hidden coupling, a second source of truth, a shallow abstraction, or a shortcut that makes the next change harder.

The project does not pursue speculative abstraction or big-design-up-front. Strategic work means small, continuous design investments justified by current complexity.

## Invariants

- Python core/domain code owns business rules, canonical state and persistence.
- `LedgerService` is the only writer of accounting transactions and entries.
- Other workflows may stage evidence or metadata, but accounting mutations delegate to `LedgerService` atomically.
- Monetary persistence uses integer minor units; financial multiplication, division, percentage and FX math use `Decimal`; financial `float` is prohibited.
- User-entered transaction/budget/loan-principal/custom-payment amounts are unsigned, strictly positive monetary magnitudes. Economic direction belongs to transaction/posting semantics, never to a user-entered `+` or `-` sign. Signed monetary parsing remains available only for external data where the sign is part of the source evidence.
- Temporal tracking-boundary semantics have one canonical policy.
- Posting capability rules have one canonical policy; presentation renders capabilities rather than re-deriving accounting decisions.
- Scheduled recurrence has one canonical owner. Forecasting and other projections consume the scheduled service's read-only occurrence projection rather than reimplementing recurrence rules.
- Forecasting is a deterministic read model: it must not write ledger/schedule/loan state, must expose material assumptions, and must fail closed when a required financial conversion cannot be supported by canonical data.
- Known future obligations introduced by a domain module expose a read-only projection from their canonical owner when they materially affect forecasting; ForecastService consumes that projection rather than duplicating the domain algorithm.
- Loan contracts never persist a parallel outstanding balance. Outstanding principal is derived from the canonical linked LIABILITY ledger balance; contract metadata, effective rate history and payment-to-ledger links may be persisted.
- Loan amortization math has one pure canonical policy owner. `LoanService` orchestrates contract state and delegates arithmetic to that policy rather than encoding separate French/Italian/bullet formulas in posting, forecast or UI paths.
- Loan installment projection and posting consume the same canonical remaining-plan calculation. Principal repayment remains balance-sheet neutral in book-level flow semantics; interest is the expense component.
- Variable-rate history is effective-dated and append/update-only for future periods: a revision must never rewrite the rate applied to an already-posted installment. Future variable-rate projections use the latest effective known revision until another explicit revision exists; they do not invent future index values.
- Custom loan payments are explicit domain events. They must cover accrued interest and reduce principal; arrears, unpaid-interest capitalization, penalties and negative amortization are never inferred silently.
- Loan creation/account/policy capabilities are backend-owned; JavaScript renders allowed targets and policy values rather than inferring them from account types, currencies, balances or financial formulas.
- QWebChannel transport must preserve financial integer precision explicitly.
- `AppController` coordinates; it must not accumulate SQL or become the owner of domain rules.
- `ui/bridge.py` validates transport shape and delegates; it does not implement business rules.
- JavaScript owns presentation and temporary UI state only.
- Database migrations are separated from database connection/lifecycle responsibilities.
- Prefer a small number of deep modules over many shallow wrappers, repositories, factories or interfaces.
- Do not introduce abstractions without a current source of complexity they remove.

## Mandatory milestone strategic review

A milestone is not complete until its functional tests are green **and** this review has been performed.

For every milestone, step back from the feature and inspect the whole project. Record the answers in the milestone/PR notes.

1. **Sources of truth:** Did the milestone introduce a second owner for any important state or rule?
2. **Duplication:** Is domain knowledge now encoded in more than one module or layer?
3. **Information leakage:** Does a caller need to know implementation details that should be hidden behind a deeper module?
4. **Module depth:** Did we create shallow forwarding layers or split one coherent responsibility unnecessarily?
5. **Controller/bridge/UI leakage:** Did SQL, domain decisions, financial math or persistence move upward into orchestration or presentation?
6. **General-purpose design:** Can the new abstraction handle the natural nearby cases without being tailored to a single UI path?
7. **Error model:** Are errors explicit, fail-closed where financial correctness requires it, and owned by the right layer?
8. **State transitions and atomicity:** Can partial failure leave contradictory state? Are cross-service writes transactionally coherent?
9. **Concurrency/lifecycle:** Can the new work block the GUI thread, leak resources or create shutdown races?
10. **Tests as architecture:** What invariant could regress silently later, and should it become a permanent automated test?
11. **Complexity budget:** Did the milestone make the system easier or harder to understand and modify overall?
12. **Strategic cleanup:** If complexity increased, perform the smallest coherent refactor now rather than deferring routine design debt.

The review outcome must be one of:

- **STRATEGIC — no cleanup required**
- **STRATEGIC AFTER CLEANUP — cleanup completed in the milestone**
- **BLOCKED — milestone is not complete until named architectural debt is resolved**

Routine design debt discovered by this review must not be moved to a vague future backlog merely to close the milestone. Deferral is acceptable only for a deliberate product tradeoff with a concrete reason and boundary documented in the milestone notes.

## Definition of done

Before a milestone is declared complete:

```bash
.venv/bin/python -m compileall -q main.py config core ui tests
.venv/bin/python -m pytest
.venv/bin/ruff check main.py config core ui tests
```

Then perform the mandatory strategic review above. Green tests without the review are not milestone completion.
